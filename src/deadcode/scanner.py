"""Dead code scanner for TypeScript/React/Next.js projects.

Detects:
- Unused exports (functions, classes, constants, types)
- Dead routes (Next.js pages/api routes with no incoming links)
- Orphaned CSS classes (CSS classes not referenced in any component)
- Unreferenced components (React components never imported)
"""

from __future__ import annotations

import os
import re
from bisect import bisect_right
from dataclasses import dataclass, field
from html.entities import name2codepoint
from pathlib import Path

import pathspec

from ._typescript import class_property_positions, class_usage_source, class_value_positions

# ── Data structures ───────────────────────────────────────────────────


@dataclass
class Finding:
    """A single dead code finding."""

    file: str
    line: int
    name: str
    category: str  # unused_export, dead_route, orphaned_css, unreferenced_component
    detail: str = ""
    removable: bool = False  # Whether safe auto-removal is possible


@dataclass(frozen=True)
class _CssDefinition:
    file: str
    line: int
    global_scope: bool
    rule: int | None = None
    multiline_header: bool = False


@dataclass
class ScanResult:
    """Aggregated scan results."""

    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def unused_exports(self) -> list[Finding]:
        return [f for f in self.findings if f.category == "unused_export"]

    @property
    def dead_routes(self) -> list[Finding]:
        return [f for f in self.findings if f.category == "dead_route"]

    @property
    def orphaned_css(self) -> list[Finding]:
        return [f for f in self.findings if f.category == "orphaned_css"]

    @property
    def unreferenced_components(self) -> list[Finding]:
        return [f for f in self.findings if f.category == "unreferenced_component"]


# ── Patterns ──────────────────────────────────────────────────────────

# export const/let/var/function/class/type/interface/enum.
# Deliberately does NOT match `export default ...`: with `default` in the
# alternation the capture group grabbed the keyword `function`/`class` as
# the export name, flagging every default export as removable dead code.
# Default exports are entry-point conventions and are skipped entirely.
_EXPORT_PATTERN = re.compile(
    r"^\s*export\s+"
    r"(?:const|let|var|function|class|type|interface|enum)\s+"
    r"([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)

# export { name } — may span multiple lines; [^}] matches newlines too
_EXPORT_LIST_PATTERN = re.compile(
    # `(?!\s*from)` excludes re-export forwarding (`export { X } from '...'`),
    # which is handled by _REEXPORT_PATTERN as a *use* of the source module's
    # exports rather than a new local export definition.
    r"export\s*\{([^}]+)\}(?!\s*from)",
    re.DOTALL,
)

# React component: function Name or const Name = ...
_COMPONENT_PATTERN = re.compile(
    r"(?:function|const)\s+([A-Z][A-Za-z0-9]*)\s*(?:=\s*|\(|<)",
)

# Next.js routes: app/.../page.tsx, app/.../route.ts, pages/....
_ROUTE_PATTERN = re.compile(
    r"(?:app|src/app|pages|src/pages)/(.*?)/(?:page|route)\.(?:tsx|ts|jsx|js)$",
)

# CSS escapes include up to six hexadecimal digits and their optional single
# whitespace terminator. Consume them inside the identifier before interpreting
# punctuation as selector syntax (for example, .foo\\:bar and .foo\\.bar).
_CSS_ESCAPE = r"\\(?:[0-9a-fA-F]{1,6}(?:\r\n|[ \t\r\n\f])?|[^\r\n\f0-9a-fA-F])"
_CSS_NAME_START = rf"(?:[a-zA-Z_]|[^\x00-\x7f]|{_CSS_ESCAPE})"
_CSS_NAME_CHAR = rf"(?:[a-zA-Z0-9_-]|[^\x00-\x7f]|{_CSS_ESCAPE})"
_CSS_IDENTIFIER = rf"(?:--|-?{_CSS_NAME_START}){_CSS_NAME_CHAR}*"
_CSS_IDENTIFIER_PATTERN = re.compile(_CSS_IDENTIFIER)
_CSS_ESCAPE_PATTERN = re.compile(_CSS_ESCAPE)

# Preserve the existing global utility-prefix handling as well as escaped names.
_CSS_CLASS_PATTERN = re.compile(
    rf"\.({_CSS_IDENTIFIER}(?::{_CSS_IDENTIFIER})*)\s*(?:\{{|,|\[)",
)

_CSS_NONCODE_PATTERN = re.compile(_CSS_ESCAPE + r"|/\*[\s\S]*?\*/|'(?:\\[\s\S]|[^'\\])*'|\"(?:\\[\s\S]|[^\"\\])*\"")
_CSS_SELECTOR_TOKEN_PATTERN = re.compile(
    rf"{_CSS_ESCAPE}|:(global|local)(?![\w-]|[^\x00-\x7f]|\\)|\.({_CSS_IDENTIFIER})|[(),\[\]]"
)
_CSS_BLOCK_TOKEN_PATTERN = re.compile(_CSS_ESCAPE + r"|[{};()\[\]]")


def _decode_css_identifier(identifier: str) -> str:
    """Decode CSS Syntax escapes, replacing invalid escaped Unicode scalars."""

    def unescape(match: re.Match) -> str:
        value = match.group()[1:]
        if value[0] in "0123456789abcdefABCDEF":
            codepoint = int(value.rstrip(" \t\r\n\f"), 16)
            return chr(codepoint) if 0 < codepoint <= 0x10FFFF and not 0xD800 <= codepoint <= 0xDFFF else "�"
        return value

    return _CSS_ESCAPE_PATTERN.sub(unescape, identifier)


def _module_selector_classes(selector: str, inherited_global: bool):
    """Yield each class's own scope, respecting functional and bare switches."""
    global_scope = inherited_global
    parentheses: list[tuple[bool, bool]] = []
    pending_scope: bool | None = None
    brackets = 0
    for match in _CSS_SELECTOR_TOKEN_PATTERN.finditer(selector):
        token = match.group()
        if token == "[":
            brackets += 1
        elif token == "]":
            brackets = max(0, brackets - 1)
        elif brackets:
            continue
        elif match.group(1):
            scope = match.group(1) == "global"
            if selector[match.end() :].lstrip().startswith("("):
                pending_scope = scope
            else:
                global_scope = scope
        elif token == "(":
            inner_scope = global_scope if pending_scope is None else pending_scope
            parentheses.append((global_scope, inner_scope))
            global_scope = inner_scope
            pending_scope = None
        elif token == ")":
            if parentheses:
                global_scope = parentheses.pop()[0]
        elif token == ",":
            global_scope = parentheses[-1][1] if parentheses else inherited_global
        elif match.group(2):
            yield _decode_css_identifier(match.group(2)), match.start(), global_scope


def _module_css_definitions(content: str, rel_path: str):
    """Read selector headers without mistaking declaration strings for classes."""
    masked = _CSS_NONCODE_PATTERN.sub(
        lambda match: match.group() if match.group().startswith("\\") else re.sub(r"[^\n]", " ", match.group()), content
    )
    lines = [0, *(match.end() for match in re.finditer("\n", content))]
    scopes = [False]
    start = 0
    parentheses = brackets = 0
    for match in _CSS_BLOCK_TOKEN_PATTERN.finditer(masked):
        token = match.group()
        if token.startswith("\\"):
            continue
        if token == "(":
            parentheses += 1
        elif token == ")":
            parentheses = max(0, parentheses - 1)
        elif token == "[":
            brackets += 1
        elif token == "]":
            brackets = max(0, brackets - 1)
        elif parentheses or brackets:
            continue
        elif token == "{":
            selector = masked[start : match.start()]
            selector_start = start + len(selector) - len(selector.lstrip())
            multiline_header = bisect_right(lines, selector_start) != bisect_right(lines, match.start())
            if not selector.lstrip().startswith("@"):
                for name, offset, global_scope in _module_selector_classes(selector, scopes[-1]):
                    yield (
                        name,
                        _CssDefinition(
                            rel_path, bisect_right(lines, start + offset), global_scope, match.start(), multiline_header
                        ),
                    )
            block_scope = {":global": True, ":local": False}.get(selector.strip(), scopes[-1])
            scopes.append(block_scope)
            start = match.end()
        elif token == "}":
            if len(scopes) > 1:
                scopes.pop()
            start = match.end()
        else:
            start = match.end()


# import statements
# Handles: import {Foo} from ..., import Foo from ..., import type {Foo} from ...,
#          import Default, {Named} from ..., import {type Foo} from ...
# Groups: 1 = first named block content (e.g. "Foo, Bar"), 2 = default import name,
#          3 = optional named block after comma default, 4 = module specifier
_IMPORT_PATTERN = re.compile(
    r"import\s+"
    r"(?:type\s+)?"
    r"(?:"
    r"\{([^}]+)\}"  # group 1: named imports {Foo, type Bar}
    r"|"
    r"(\w+(?:\s+as\s+\w+)?)"  # group 2: default import (Foo or Foo as Bar)
    r")"
    r"(?:\s*,\s*\{([^}]+)\})?"  # group 3: optional named after default
    r"\s+from\s+['\"]([^'\"]+)['\"]",
)

# Re-export forwarding: `export { A, B as C } from './mod'` and `export * from './mod'`.
# A barrel/index file that re-exports a symbol is *consuming* it from the source
# module, so the source's export must not be flagged as unused. `[^}]*` matches
# newlines (with re.DOTALL) for multi-line re-export blocks.
_REEXPORT_PATTERN = re.compile(
    r"export\s*(?:\{([^}]*)\}|\*(?:\s+as\s+\w+)?)\s*from\s*['\"]([^'\"]+)['\"]",
    re.DOTALL,
)

# Namespace import: `import * as Utils from './utils'`. A namespace binding
# reaches every export of the module through one object (`Utils.foo`), so
# individual names cannot be attributed to use sites. Like a barrel re-export,
# the whole export surface of the target module counts as consumed; otherwise
# exports used only via a namespace are falsely reported as unused with
# removable=True — live code queued for deletion.
_NAMESPACE_IMPORT_PATTERN = re.compile(r"import\s+\*\s+as\s+\w+\s+from\s*['\"]([^'\"]+)['\"]")

# Bare side-effect import: `import './polyfill';` — executes the module without
# binding any names, consuming its entire export surface.
_SIDE_EFFECT_IMPORT_PATTERN = re.compile(r"^\s*import\s*['\"]([^'\"]+)['\"]", re.MULTILINE)

# Dynamic import: `const m = await import('./heavy');` — lazily loads the whole
# module at runtime; individual consumed names are invisible statically, so the
# module's entire export surface counts as used.
_DYNAMIC_IMPORT_PATTERN = re.compile(r"import\(\s*['\"]([^'\"]+)['\"]\s*\)")

# CommonJS require: `const m = require('./legacy');` — same whole-module
# consumption semantics as a dynamic import.
_REQUIRE_PATTERN = re.compile(r"(?<![\w$.])require\(\s*['\"]([^'\"]+)['\"]\s*\)")

# JSX attribute quotes do not use JavaScript backslash escaping. Keep their
# delimiter parsing separate from strings inside JavaScript expressions.
_JS_LITERAL_PATTERN = re.compile(r"""'(?:\\[\s\S]|[^'\\\r\n])*'|"(?:\\[\s\S]|[^"\\\r\n])*"|`(?:\\[\s\S]|[^`\\])*`""")
_JS_COMMENT_PATTERN = re.compile(r"//[^\r\n]*|/\*[\s\S]*?\*/")
_JSX_TAG_PATTERN = re.compile(r"<(?:[^\W\d]|\$|[^\x00-\x7f\s])(?:[\w$:.-]|[^\x00-\x7f\s])*(?=[\s/>])")
_JSX_ATTRIBUTE_PATTERN = re.compile(r"(?:[^\W\d]|[$:]|[^\x00-\x7f\s])(?:[\w$:.-]|[^\x00-\x7f\s])*")
_CLASS_PROPERTY_PATTERN = re.compile(r"""(?<![\w$])(?:className|class|['"]className['"]|['"]class['"])\s*:\s*""")
_CLASSNAMES_CALL_PATTERN = re.compile(r"(?<![\w$])(?:classNames|clsx)\s*(?=\()")
_JSX_ENTITY_PATTERN = re.compile(r"&(?:#[xX][0-9a-fA-F]+|#[0-9]+|[a-zA-Z][a-zA-Z0-9]*);")
_HTML_CLASS_SPACE_PATTERN = re.compile(r"[ \t\r\n\f]+")


def _js_delimited_end(content: str, start: int, *, limit: int | None = None) -> int | None:
    """Find a closing JS delimiter without treating quoted braces as syntax."""
    closing = {"{": "}", "[": "]", "(": ")"}
    stack = [closing[content[start]]]
    index = start + 1
    limit = len(content) if limit is None else limit
    while index < limit:
        skipped = _JS_LITERAL_PATTERN.match(content, index, limit) or _JS_COMMENT_PATTERN.match(content, index, limit)
        if skipped:
            index = skipped.end()
            continue
        char = content[index]
        if char in closing:
            stack.append(closing[char])
        elif char in "}])":
            if char != stack.pop():
                return None
            if not stack:
                return index + 1
        index += 1
    return None


def _class_property_value(content: str, start: int) -> str | None:
    """Read a complete property expression, retaining uncertainty for operators."""
    index = start
    while index < len(content):
        skipped = _JS_LITERAL_PATTERN.match(content, index) or _JS_COMMENT_PATTERN.match(content, index)
        if skipped:
            index = skipped.end()
            continue
        if content[index] in "{[(":
            end = _js_delimited_end(content, index)
            if end is None:
                return None
            index = end
            continue
        if content[index] in ",};)]":
            break
        index += 1
    return content[start:index]


def _decode_jsx_attribute(value: str) -> str | None:
    """Decode semicolon-terminated JSX entities once, without HTML error recovery."""
    valid = True

    def entity(match: re.Match) -> str:
        nonlocal valid
        raw = match.group()
        if not raw.startswith("&#"):
            if raw == "&apos;":
                return "'"
            number = name2codepoint.get(raw[1:-1])
            return chr(number) if number is not None else raw
        code = raw[2:-1]
        hexadecimal = code[:1].lower() == "x"
        digits = (code[1:] if hexadecimal else code).lstrip("0") or "0"
        if len(digits) > (6 if hexadecimal else 7):
            valid = False
            return raw
        number = int(digits, 16 if hexadecimal else 10)
        if not 0 < number <= 0x10FFFF or 0xD800 <= number <= 0xDFFF:
            valid = False
            return raw
        # JSX numeric entities represent their code point directly; unlike
        # html.unescape, C1 controls must not be changed to Windows-1252 text.
        return chr(number)

    decoded = _JSX_ENTITY_PATTERN.sub(entity, value)
    return decoded if valid else None


def _jsx_class_attributes(content: str, attribute_positions: set[int] | None = None):
    """Yield raw JSX values or JS expressions from possible opening tags.

    Looking at every possible tag intentionally over-approximates tags inside
    source strings rather than missing nested JSX after quoted child text.
    """
    for tag in _JSX_TAG_PATTERN.finditer(content):
        index = tag.end()
        limit = min(len(content), tag.start() + 8192)
        while index < limit:
            if content[index].isspace() or content[index] == "/":
                index += 1
                continue
            if content[index] == ">":
                break
            if content[index] == "{":
                end = _js_delimited_end(content, index, limit=limit)
                if end is None:
                    yield False, None
                    break
                if content[index + 1 : end - 1].lstrip().startswith("..."):
                    yield False, None  # Spread props may supply any global class.
                index = end
                continue
            name = _JSX_ATTRIBUTE_PATTERN.match(content, index, limit)
            if name is None:
                break  # Not an attribute: do not walk the remaining file per candidate.
            wanted = name.group() in {"className", "class"}
            if wanted and attribute_positions is not None:
                attribute_positions.add(name.start())
            index = name.end()
            while index < limit and content[index].isspace():
                index += 1
            if index >= limit or content[index] != "=":
                continue
            index += 1
            while index < limit and content[index].isspace():
                index += 1
            if index == limit:
                if wanted:
                    yield False, None
                break
            if content[index] in "'\"":
                end = content.find(content[index], index + 1, limit)
                if end < 0:
                    if wanted or limit < len(content):
                        yield False, None
                    break
                if wanted:
                    yield True, content[index + 1 : end]
                index = end + 1
            elif content[index] == "{":
                end = _js_delimited_end(content, index, limit=limit)
                if wanted:
                    yield False, content[index + 1 : end - 1] if end is not None else None
                if end is None:
                    if not wanted:
                        yield False, None
                    break
                index = end
            else:
                if wanted:
                    yield False, None
                index += 1
        if index >= limit and limit < len(content):
            yield False, None  # An oversized header leaves possible global uses uncertain.


# tsconfig paths for path aliases
_TSCONFIG_PATHS_PATTERN = re.compile(
    r'"([^"]+)"\s*:\s*\["([^"]+)"\]',
)

# Computed keys are full quoted JavaScript literals, not identifier prefixes.
_CSS_MODULE_USAGE_PATTERN = re.compile(
    r"""(?<![\w$])([\w$]+)(?:\s*\??\.\s*([\w$]+)|\s*(?:\?\.)?\s*\[\s*"""
    r"""('(?:\\[\s\S]|[^'\\\r\n])*'|"(?:\\[\s\S]|[^"\\\r\n])*"|`(?:\\[\s\S]|[^`\\])*`)\s*\])""",
)


def _decode_js_string(literal: str) -> str | None:
    """Decode a computed literal; retain uncertainty for interpolation or invalid escapes."""
    body = literal[1:-1]
    decoded = []
    index = 0
    while index < len(body):
        char = body[index]
        index += 1
        if char != "\\":
            if literal[0] == "`" and char == "$" and body[index : index + 1] == "{":
                return None
            decoded.append(char)
            continue
        if index == len(body):
            return None
        char = body[index]
        index += 1
        if char in "\r\n\u2028\u2029":
            if char == "\r" and body[index : index + 1] == "\n":
                index += 1
            continue
        if char in "xu":
            width = 2 if char == "x" else 4
            if char == "u" and body[index : index + 1] == "{":
                end = body.find("}", index + 1)
                digits = body[index + 1 : end] if end >= 0 else ""
                index = end + 1
            else:
                digits = body[index : index + width]
                index += width
                if len(digits) != width:
                    return None
            if not re.fullmatch(r"[0-9a-fA-F]{1,6}", digits) or int(digits, 16) > 0x10FFFF:
                return None
            decoded.append(chr(int(digits, 16)))
        elif char.isdecimal() and (char != "0" or body[index : index + 1].isdigit()):
            return None  # Legacy octal escapes are invalid in ECMAScript modules.
        else:
            decoded.append(
                {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}.get(char, char)
            )
    try:
        # JavaScript Unicode escapes use UTF-16; pairs must match astral CSS names.
        return "".join(decoded).encode("utf-16-le", "surrogatepass").decode("utf-16-le")
    except UnicodeDecodeError:
        return None


def _class_expression_values(expression: str, module_bindings: set[str]) -> tuple[set[str], bool]:
    """Recognize literal values and owned module access; keep other expressions uncertain."""
    expression = expression.strip()
    while expression.startswith("(") and _js_delimited_end(expression, 0) == len(expression):
        expression = expression[1:-1].strip()
    if _JS_LITERAL_PATTERN.fullmatch(expression):
        decoded = _decode_js_string(expression)
        return ({decoded}, True) if decoded is not None else (set(), False)
    if expression in {"null", "undefined", "false", "true"}:
        return set(), True
    accessor = _CSS_MODULE_USAGE_PATTERN.fullmatch(expression)
    if accessor and accessor.group(1) in module_bindings:
        return set(), True  # The separate module pass retains stylesheet scope.
    computed = re.match(r"([\w$]+)\s*(?:\?\.)?\s*\[", expression)
    if (
        computed
        and computed.group(1) in module_bindings
        and _js_delimited_end(expression, computed.end() - 1) == len(expression)
    ):
        return set(), True
    call = _CLASSNAMES_CALL_PATTERN.match(expression)
    if call and _js_delimited_end(expression, call.end()) == len(expression):
        arguments = expression[call.end() + 1 : -1]
        values = set()
        complete = True
        for literal in _JS_LITERAL_PATTERN.finditer(arguments):
            decoded = _decode_js_string(literal.group())
            if decoded is None:
                complete = False
            else:
                values.add(decoded)
        remainder = _JS_COMMENT_PATTERN.sub("", _JS_LITERAL_PATTERN.sub("", arguments))
        return values, complete and not remainder.strip(" \t\r\n\f,")
    # Literal branches of conditions are possible uses, but cannot prove any
    # other global class unused. Do not execute or guess variable bindings.
    return {
        decoded
        for literal in _JS_LITERAL_PATTERN.finditer(expression)
        if (decoded := _decode_js_string(literal.group())) is not None
    }, False


# Detect a CSS-module import so we know which source-file class accessors
# correspond to module classes (``import styles from './x.module.css'``).
_CSS_MODULE_IMPORT_PATTERN = re.compile(
    r"""import\s+(?:\*\s+as\s+|\{\s*default\s+as\s+)?([\w$]+)(?:\s*\}|\s*,\s*\{[^}]*\})?\s+from\s+['"]([^'"]*\.module\.css)['"]""",
)


# ── Scanner ───────────────────────────────────────────────────────────


class DeadCodeScanner:
    """Scans TypeScript/React/Next.js projects for dead code."""

    def __init__(
        self,
        project_dir: str | Path,
        ignore_patterns: list[str] | None = None,
        include_patterns: list[str] | None = None,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.ignore_spec = pathspec.PathSpec.from_lines(
            "gitignore",
            ignore_patterns or self._default_ignore_patterns(),
        )
        self.include_spec = None
        if include_patterns:
            self.include_spec = pathspec.PathSpec.from_lines("gitignore", include_patterns)

    @staticmethod
    def _default_ignore_patterns() -> list[str]:
        return [
            "node_modules/",
            ".git/",
            ".next/",
            "dist/",
            "build/",
            "out/",
            "coverage/",
            "__pycache__/",
            "*.min.js",
            "*.min.css",
            ".cache/",
            "public/",
            "static/",
        ]

    def scan(self) -> ScanResult:
        """Run a full dead code scan."""
        result = ScanResult()

        # Collect all files
        all_files = self._collect_files()
        result.files_scanned = len(all_files)

        if not all_files:
            return result

        # Phase 1: Build export map and import map
        exports: dict[str, list[tuple[str, int]]] = {}  # name -> [(file, line)]
        imports: dict[str, set[str]] = {}  # name -> set of files that import it
        css_classes: dict[str, list[_CssDefinition]] = {}
        used_css_classes: set[str | None] = set()
        used_css_module_classes: dict[Path, set[str | None]] = {}
        unresolved_css_module_classes: set[str | None] = set()
        components: dict[str, str] = {}  # ComponentName -> file
        routes: list[tuple[str, str]] = []  # (route_path, file)
        star_reexports: list[tuple[str, str]] = []  # (barrel_file, module_spec)
        file_set = {str(f.relative_to(self.project_dir)).replace("\\", "/") for f in all_files}

        for filepath in all_files:
            try:
                content = filepath.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                result.errors.append(f"{filepath}: {e}")
                continue

            rel_path = str(filepath.relative_to(self.project_dir)).replace("\\", "/")

            # Parse exports
            self._parse_exports(content, rel_path, exports)

            # Parse imports
            self._parse_imports(content, rel_path, imports)

            # Parse re-exports (barrel/index forwarding) so re-exported symbols
            # are counted as used and not reported as removable dead code.
            self._parse_reexports(content, rel_path, imports, star_reexports)

            # Parse CSS classes (from .css/.scss/.module.css files)
            if self._is_css_file(rel_path):
                self._parse_css_classes(content, rel_path, css_classes)

            # Plain JS/TS can also export class props or classNames() values.
            if not self._is_css_file(rel_path):
                class_source = class_usage_source(content, rel_path)
                self._parse_classname_usage(class_source, used_css_classes, jsx=not rel_path.endswith(".ts"))

            # CSS modules can also be consumed by plain TypeScript/JavaScript
            # files, for example when exporting class-name maps to components.
            if not self._is_css_file(rel_path):
                self._parse_css_module_usage(
                    class_source, rel_path, file_set, used_css_module_classes, unresolved_css_module_classes
                )

            # Parse components
            if rel_path.endswith((".tsx", ".jsx")):
                self._parse_components(content, rel_path, components)

            # Parse routes
            route = self._parse_route(rel_path)
            if route:
                routes.append((route, rel_path))

        # Phase 2: Detect dead code

        # Resolve `export * from './mod'` specifiers to scanned files so that
        # every export forwarded by a barrel is treated as part of the public
        # API surface (never reported as removable).
        star_reexported_files: set[str] = set()
        for barrel_file, module_spec in star_reexports:
            resolved = self._resolve_relative_module(barrel_file, module_spec, file_set)
            if resolved:
                star_reexported_files.add(resolved)

        # 2a. Unused exports
        self._find_unused_exports(exports, imports, result, star_reexported_files)

        # 2b. Dead routes
        self._find_dead_routes(routes, all_files, result)

        # 2c. Orphaned CSS
        self._find_orphaned_css(
            css_classes, used_css_classes, used_css_module_classes, unresolved_css_module_classes, result
        )

        # 2d. Unreferenced components
        # Collect all names that are imported somewhere (i.e., actually used)
        all_imported_names: set[str] = set(imports.keys())
        self._find_unreferenced_components(components, all_imported_names, result)

        return result

    def _collect_files(self) -> list[Path]:
        """Collect all relevant source files."""
        files: list[Path] = []
        for root, dirs, filenames in os.walk(self.project_dir):
            rel_root = str(Path(root).relative_to(self.project_dir)).replace("\\", "/")

            # Filter out ignored directories
            dirs[:] = [
                d for d in dirs if not self.ignore_spec.match_file(f"{rel_root}/{d}/" if rel_root != "." else f"{d}/")
            ]

            # A file whitelist need not match its parent directories (for
            # example, "src/components/*.tsx"). Only ignored directories can
            # be pruned; apply include patterns to the individual files below.

            for fname in filenames:
                rel_path = f"{rel_root}/{fname}" if rel_root != "." else fname
                if self.ignore_spec.match_file(rel_path):
                    continue
                if self.include_spec and not self.include_spec.match_file(rel_path):
                    continue

                if not self._is_scannable_file(rel_path):
                    continue

                filepath = Path(root) / fname
                # A source-file symlink may resolve outside the project. Such
                # findings could otherwise make `remove` modify external files.
                try:
                    filepath.resolve().relative_to(self.project_dir)
                except (ValueError, OSError, RuntimeError):
                    continue
                files.append(filepath)

        return files

    @staticmethod
    def _is_scannable_file(rel_path: str) -> bool:
        """Check if a file should be scanned."""
        return rel_path.endswith(
            (
                ".ts",
                ".tsx",
                ".js",
                ".jsx",
                ".css",
                ".scss",
                ".module.css",
            )
        )

    @staticmethod
    def _is_css_file(rel_path: str) -> bool:
        return rel_path.endswith((".css", ".scss", ".module.css"))

    def _parse_exports(self, content: str, rel_path: str, exports: dict[str, list[tuple[str, int]]]) -> None:
        """Extract export names from a file.

        Handles both single-line forms::

            export function foo() {}
            export const BAR = 1;

        And multi-line export-list blocks::

            export {
              Foo,
              Bar as Baz,
            }
        """
        # Named/typed exports: scan line-by-line to preserve line numbers cheaply.
        for i, line in enumerate(content.splitlines(), 1):
            for m in _EXPORT_PATTERN.finditer(line):
                name = m.group(1)
                exports.setdefault(name, []).append((rel_path, i))

        # Export-list blocks: applied to the full content so that multi-line
        # blocks like ``export {\n  Foo,\n  Bar\n}`` are captured correctly.
        # [^}] matches newlines, so re.DOTALL is added for clarity but [^}]
        # already handles multi-line spans without it.
        for m in _EXPORT_LIST_PATTERN.finditer(content):
            # Determine the line number of the opening ``export {``.
            line_num = content.count("\n", 0, m.start()) + 1
            raw = m.group(1)
            # Strip // comments so inline-annotated export lists still parse.
            cleaned = "\n".join(line.split("//")[0] for line in raw.splitlines())
            names = [n.strip().split(" as ")[0].strip() for n in cleaned.split(",")]
            for name in names:
                if name and re.match(r"^[A-Za-z_$][\w$]*$", name):
                    exports.setdefault(name, []).append((rel_path, line_num))

    def _parse_imports(self, content: str, rel_path: str, imports: dict[str, set[str]]) -> None:
        """Extract import names from a file.

        Handles: named imports (group 1), default imports (group 2),
        and optional trailing named block (group 3, e.g. ``import React, { Foo }``).
        Named-block entries prefixed with ``type `` are stripped to the canonical name.
        """
        for m in _IMPORT_PATTERN.finditer(content):
            named_block = m.group(1)  # {Foo, Bar} content
            default_name = m.group(2)  # React or type
            named_block2 = m.group(3)  # optional second {Foo, Bar} after comma

            # Process first named block (from direct {Foo} or import type {Foo})
            if named_block:
                for entry in named_block.split(","):
                    name = entry.strip()
                    if not name:
                        continue
                    canonical = name[5:].strip() if name.startswith("type ") else name
                    if canonical:
                        imports.setdefault(canonical, set()).add(rel_path)

            # Process default import name (but skip bare "type" keyword)
            if default_name and default_name != "type":
                imports.setdefault(default_name, set()).add(rel_path)

            # Process optional named block after comma (Default, {Foo})
            if named_block2:
                for entry in named_block2.split(","):
                    name = entry.strip()
                    if not name:
                        continue
                    canonical = name[5:].strip() if name.startswith("type ") else name
                    if canonical:
                        imports.setdefault(canonical, set()).add(rel_path)

    def _parse_reexports(
        self,
        content: str,
        rel_path: str,
        imports: dict[str, set[str]],
        star_reexports: list[tuple[str, str]],
    ) -> None:
        """Record whole-module consumption so source modules don't false-positive.

        ``export { A, B as C } from './mod'`` consumes ``A`` and ``B`` from
        ``./mod``; the consumed (left-hand) names are registered as imports of
        this file so the source module's exports are not reported as unused.
        ``export * from './mod'``, ``import * as NS from './mod'``, and bare
        ``import './mod'`` all consume ``./mod``'s *entire* export surface —
        individual names cannot be attributed — so each (file, module) pair is
        recorded; those exports are treated as used once ``./mod`` resolves to
        a scanned file.
        """
        for m in _REEXPORT_PATTERN.finditer(content):
            named = m.group(1)
            module_path = m.group(2)
            if named is not None:
                for entry in named.split(","):
                    entry = entry.strip()
                    if not entry:
                        continue
                    # `A as B` re-exports A (the left-hand source name) as B.
                    source = entry.split(" as ")[0].strip()
                    if source.startswith("type "):
                        source = source[5:].strip()
                    if source and re.match(r"^[A-Za-z_$][\w$]*$", source):
                        imports.setdefault(source, set()).add(rel_path)
            else:
                # `export * from './mod'` — resolved to a file in phase 2.
                star_reexports.append((rel_path, module_path))
        for m in _NAMESPACE_IMPORT_PATTERN.finditer(content):
            # `import * as NS from './mod'` — whole-module consumption.
            star_reexports.append((rel_path, m.group(1)))
        for m in _SIDE_EFFECT_IMPORT_PATTERN.finditer(content):
            # `import './mod'` — side-effect-only consumption.
            star_reexports.append((rel_path, m.group(1)))
        for pattern in (_DYNAMIC_IMPORT_PATTERN, _REQUIRE_PATTERN):
            for m in pattern.finditer(content):
                # `import('./mod')` / `require('./mod')` — lazily loads the
                # whole module; consumed names are invisible statically.
                star_reexports.append((rel_path, m.group(1)))

    @staticmethod
    def _resolve_relative_module(importer_rel: str, spec: str, file_set: set[str]) -> str | None:
        """Resolve a relative module specifier to a scanned file's rel path.

        Returns ``None`` for bare/package specifiers (e.g. ``'react'``) or when
        no matching scanned file exists. Tries the literal path, then common
        TS/JS extensions, then an ``index.*`` barrel inside a directory.
        """
        if not spec.startswith("."):
            return None
        base = os.path.dirname(importer_rel)
        target = os.path.normpath(os.path.join(base, spec)).replace("\\", "/")
        if target in file_set:
            return target
        exts = (".ts", ".tsx", ".js", ".jsx")
        for e in exts:
            if target + e in file_set:
                return target + e
        for e in exts:
            candidate = f"{target}/index{e}"
            if candidate in file_set:
                return candidate
        return None

    def _parse_css_classes(self, content: str, rel_path: str, css_classes: dict[str, list[_CssDefinition]]) -> None:
        """Extract CSS class names defined in a stylesheet."""
        if rel_path.endswith(".module.css"):
            for cls, definition in _module_css_definitions(content, rel_path):
                css_classes.setdefault(cls, []).append(definition)
            return
        for i, line in enumerate(content.splitlines(), 1):
            for m in _CSS_CLASS_PATTERN.finditer(line):
                identifier = m.group(1)
                if "\\" in identifier:
                    # An unescaped colon following an escaped name begins a
                    # pseudo-selector, not part of that class's decoded key.
                    identifier = _CSS_IDENTIFIER_PATTERN.match(identifier).group()
                cls = _decode_css_identifier(identifier)
                css_classes.setdefault(cls, []).append(_CssDefinition(rel_path, i, True))

    def _parse_classname_usage(self, content: str, used_css_classes: set[str | None], *, jsx: bool = True) -> None:
        """Read raw JSX attributes and JavaScript literals using their own grammar."""
        properties, calls, code_starts = class_value_positions(content, jsx=jsx)
        module_bindings = {
            match.group(1) for match in _CSS_MODULE_IMPORT_PATTERN.finditer(content) if match.start() in code_starts
        }

        def consume(raw_jsx: bool, value: str | None) -> None:
            if value is None:
                used_css_classes.add(None)
                return
            if raw_jsx:
                decoded = _decode_jsx_attribute(value)
                values, complete = ({decoded}, True) if decoded is not None else (set(), False)
            else:
                values, complete = _class_expression_values(value, module_bindings)
            for text in values:
                # HTML class tokens split on ASCII whitespace, not NBSP or
                # other Unicode spaces produced by JSX entity references.
                used_css_classes.update(filter(None, _HTML_CLASS_SPACE_PATTERN.split(text)))
            if not complete:
                used_css_classes.add(None)

        jsx_properties: set[int] = set()
        for raw_jsx, value in _jsx_class_attributes(content, jsx_properties):
            consume(raw_jsx, value)
        for property_match in _CLASS_PROPERTY_PATTERN.finditer(content):
            if property_match.start() in properties:
                consume(False, _class_property_value(content, property_match.end()))
        for key, key_start, start, compound in class_property_positions(content, jsx=jsx):
            if key_start in jsx_properties:
                continue  # The JSX reader has already consumed its own grammar.
            name = _decode_js_string(key) if key[:1] in {"'", '"', "`"} else key
            if name in {"className", "class"}:
                consume(False, None if compound else _class_property_value(content, start))
        for call in _CLASSNAMES_CALL_PATTERN.finditer(content):
            if call.start() not in calls:
                continue
            end = _js_delimited_end(content, call.end())
            consume(False, content[call.start() : end] if end is not None else None)

    def _parse_css_module_usage(
        self,
        content: str,
        rel_path: str,
        file_set: set[str],
        used_css_module_classes: dict[Path, set[str | None]],
        unresolved_css_module_classes: set[str | None],
    ) -> None:
        """Extract CSS-module class names consumed via object accessors.

        The canonical Next.js/React pattern is::

            import styles from './Card.module.css';
            <div className={styles.card}>...</div>

        Resolve each relative ``*.module.css`` import from its importing file
        so that ``styles.card`` protects ``card`` only in that stylesheet.
        Bracket access ``styles['card-hover']`` is also captured. Canonical
        paths keep internal stylesheet symlinks and their targets consistent.
        Classes used through unresolved imports remain uncertain so alias or
        bundler-specific resolution cannot make live module classes removable.
        Without this, every CSS-module class is falsely reported as orphaned
        and marked removable=True, risking deletion of live styles.
        """
        # Map the local binding (e.g. ``styles``) to a CSS-module import so
        # only module accessors are treated as class names.
        module_bindings: dict[str, Path | None] = {}
        _, _, code_starts = class_value_positions(content, jsx=not rel_path.endswith(".ts"))
        for match in _CSS_MODULE_IMPORT_PATTERN.finditer(content):
            if match.start() not in code_starts:
                continue
            stylesheet = self._resolve_relative_module(rel_path, match.group(2), file_set)
            if stylesheet is not None and stylesheet.endswith(".module.css"):
                module_bindings[match.group(1)] = (self.project_dir / stylesheet).resolve()
            else:
                module_bindings[match.group(1)] = None
        if not module_bindings:
            return
        recognized = set()
        for m in _CSS_MODULE_USAGE_PATTERN.finditer(content):
            if m.start() not in code_starts:
                continue
            binding, dot_name, bracket_literal = m.groups()
            if binding in module_bindings:
                recognized.add(m.start())
                name = dot_name if dot_name is not None else _decode_js_string(bracket_literal)
                stylesheet_path = module_bindings[binding]
                if stylesheet_path is None:
                    unresolved_css_module_classes.add(name)
                else:
                    used_css_module_classes.setdefault(stylesheet_path, set()).add(name)
        for binding, stylesheet_path in module_bindings.items():
            for match in re.finditer(rf"(?<![\w$]){re.escape(binding)}\s*(?:\?\.)?\s*\[", content):
                if match.start() in code_starts and match.start() not in recognized:
                    if stylesheet_path is None:
                        unresolved_css_module_classes.add(None)
                    else:
                        used_css_module_classes.setdefault(stylesheet_path, set()).add(None)

    def _parse_components(self, content: str, rel_path: str, components: dict[str, str]) -> None:
        """Extract React component definitions."""
        for m in _COMPONENT_PATTERN.finditer(content):
            name = m.group(1)
            # Only track if PascalCase (React convention)
            if name[0].isupper():
                components.setdefault(name, rel_path)

    @staticmethod
    def _parse_route(rel_path: str) -> str | None:
        """Extract route path from file path (Next.js app router)."""
        m = _ROUTE_PATTERN.search(rel_path)
        if m:
            route_path = "/" + m.group(1) if m.group(1) else "/"
            # Convert [param] to :param for display
            route_path = re.sub(r"\[([^\]]+)\]", r":\1", route_path)
            return route_path
        return None

    def _find_unused_exports(
        self,
        exports: dict[str, list[tuple[str, int]]],
        imports: dict[str, set[str]],
        result: ScanResult,
        star_reexported_files: set[str] | None = None,
    ) -> None:
        """Find exports that are never imported elsewhere."""
        # Special names that are entry points or conventions
        skip_names = {
            "default",
            "GET",
            "POST",
            "PUT",
            "DELETE",
            "PATCH",
            "HEAD",
            "OPTIONS",
            "middleware",
            "config",
            "metadata",
            "generateMetadata",
            "loader",
            "action",
            "generateStaticParams",
        }

        star_reexported_files = star_reexported_files or set()

        for name, locations in exports.items():
            if name in skip_names:
                continue
            # A symbol defined in a file that is `export *`-forwarded by a barrel
            # is part of the public API surface and must not be reported as
            # removable dead code.
            if any(loc_file in star_reexported_files for loc_file, _ in locations):
                continue
            # If imported by at least one other file, it's used
            importers = imports.get(name, set())
            exporter_files = {loc[0] for loc in locations}
            external_importers = importers - exporter_files
            if not external_importers:
                for file, line in locations:
                    result.findings.append(
                        Finding(
                            file=file,
                            line=line,
                            name=name,
                            category="unused_export",
                            detail=f"Export '{name}' is never imported outside its defining file",
                            removable=True,
                        )
                    )

    def _find_dead_routes(
        self,
        routes: list[tuple[str, str]],
        all_files: list[Path],
        result: ScanResult,
    ) -> None:
        """Find Next.js routes that have no internal links pointing to them."""
        if not routes:
            return

        # Build set of all route paths referenced in links
        link_pattern = re.compile(r'(?:href|to|push|replace)\s*[=:]\s*["\'](/[^"\']*)["\']')
        referenced_routes: set[str] = set()

        for filepath in all_files:
            try:
                content = filepath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for m in link_pattern.finditer(content):
                path = m.group(1)
                # Normalize: strip trailing slash, query params
                path = path.split("?")[0].split("#")[0].rstrip("/") or "/"
                referenced_routes.add(path)

        # Root route "/" is always live
        referenced_routes.add("/")

        for route_path, rel_path in routes:
            norm_route = route_path.rstrip("/") or "/"
            if norm_route not in referenced_routes:
                # Check if it's a dynamic route that matches a referenced path
                is_dynamic = ":" in norm_route
                if is_dynamic:
                    # Dynamic routes are harder to prove dead — skip them
                    continue

                result.findings.append(
                    Finding(
                        file=rel_path,
                        line=1,
                        name=route_path,
                        category="dead_route",
                        detail=f"Route '{route_path}' has no internal links pointing to it",
                        removable=False,  # Routes may be linked externally
                    )
                )

    def _find_orphaned_css(
        self,
        css_classes: dict[str, list[_CssDefinition]],
        used_css_classes: set[str | None],
        used_css_module_classes: dict[Path, set[str | None]],
        unresolved_css_module_classes: set[str | None],
        result: ScanResult,
    ) -> None:
        """Find CSS classes defined but never used in JSX."""
        module_usage_by_file: dict[str, set[str | None]] = {}
        protected_lines: set[tuple[str, int]] = set()
        protected_rules: set[tuple[str, int]] = set()
        unused: list[tuple[str, _CssDefinition, bool]] = []
        for cls, locations in css_classes.items():
            # Skip common utility classes and pseudo-selectors
            if cls.startswith(
                (
                    "hover:",
                    "focus:",
                    "active:",
                    "disabled:",
                    "group-",
                    "sm:",
                    "md:",
                    "lg:",
                    "xl:",
                )
            ):
                # Skipped utility classes still protect a shared rule/line from
                # whole-line removal through a separate unused selector.
                protected_lines.update((definition.file, definition.line) for definition in locations)
                protected_rules.update(
                    (definition.file, definition.rule) for definition in locations if definition.rule is not None
                )
                continue
            for definition in locations:
                file, line = definition.file, definition.line
                if definition.global_scope:
                    used = cls in used_css_classes
                else:
                    if file not in module_usage_by_file:
                        module_usage_by_file[file] = used_css_module_classes.get(
                            (self.project_dir / file).resolve(), set()
                        )
                    used = cls in module_usage_by_file[file]
                uncertain = (
                    None in used_css_classes
                    if definition.global_scope
                    else cls in unresolved_css_module_classes
                    or None in unresolved_css_module_classes
                    or None in module_usage_by_file[file]
                )
                if used or uncertain:
                    protected_lines.add((file, line))
                    if definition.rule is not None:
                        protected_rules.add((file, definition.rule))
                if not used:
                    unused.append((cls, definition, uncertain))
        for cls, definition, uncertain in unused:
            shared = (definition.file, definition.line) in protected_lines or (
                definition.rule is not None and (definition.file, definition.rule) in protected_rules
            )
            result.findings.append(
                Finding(
                    file=definition.file,
                    line=definition.line,
                    name=cls,
                    category="orphaned_css",
                    detail=(
                        f"CSS class '.{cls}' may be used through a computed class expression"
                        if uncertain and definition.global_scope
                        else f"CSS module class '.{cls}' may be used through an unresolved stylesheet import or computed key"
                        if uncertain
                        else f"CSS class '.{cls}' shares a rule or line with a used selector; remove manually"
                        if shared
                        else f"CSS class '.{cls}' has a selector across multiple lines; remove manually"
                        if definition.multiline_header
                        else f"CSS class '.{cls}' is not used in any JSX className"
                    ),
                    removable=not (uncertain or shared or definition.multiline_header),
                )
            )

    def _find_unreferenced_components(
        self,
        components: dict[str, str],
        all_imported_names: set[str],
        result: ScanResult,
    ) -> None:
        """Find React components that are defined but never imported."""
        # Skip page/layout components (Next.js convention)
        skip_suffixes = (
            "Page",
            "Layout",
            "Template",
            "Loading",
            "Error",
            "NotFound",
            "GlobalError",
        )

        for comp_name, file in components.items():
            # Skip Next.js special files
            if any(comp_name.endswith(s) for s in skip_suffixes):
                continue
            # Check if the component is exported and imported
            if comp_name in all_imported_names:
                continue
            # If the file is a page/route, it's an entry point
            if "/page." in file or "/route." in file or "/layout." in file:
                continue

            result.findings.append(
                Finding(
                    file=file,
                    line=1,
                    name=comp_name,
                    category="unreferenced_component",
                    detail=f"Component '{comp_name}' is never imported by other files",
                    removable=True,
                )
            )
