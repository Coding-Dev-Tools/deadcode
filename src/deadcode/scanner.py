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
from dataclasses import dataclass, field
from pathlib import Path

import pathspec

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

# CSS class selectors (supports Tailwind utility classes with colon-separated segments like hover:bg-red)
_CSS_CLASS_PATTERN = re.compile(
    r"\.([a-zA-Z_][\w-]*(?::[\w-]+)*)\s*(?:\{|,|\[)",
)

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

# className="..." or className={...} in JSX
_CLASSNAME_PATTERN = re.compile(
    r"class(?:Name)?\s*[=:]\s*['\"]([^'\"]+)['\"]|"
    r"class(?:Name)?\s*[=:]\s*\{`([^`]+)`\}|"
    r"classNames\([^)]*['\"]([\w\s-]+)['\"]",
)

# tsconfig paths for path aliases
_TSCONFIG_PATHS_PATTERN = re.compile(
    r'"([^"]+)"\s*:\s*\["([^"]+)"\]',
)

# CSS-module accessor usage, two forms::
#   - dot:    `styles.card`        -> capture group 1 empty, full = "styles.card"
#   - bracket: `styles['card-hover']` / `styles["card"]` -> capture group 1 = name
# We deliberately match either form after a binding identifier so both
# `styles.card` and `styles['card-hover']` register the class as used.
_CSS_MODULE_USAGE_PATTERN = re.compile(
    r"""\b\w+\.(?:_?[\w$]+)|(\w+)\[['"]([\w$-]+)['"]\]""",
)

# DOM classList API: `el.classList.add('foo')` / `toggle('bar')` / `remove(...)`
# / `contains('baz')`. Dynamic class names referenced here are real uses.
_CLASSLIST_PATTERN = re.compile(
    r"""classList\.(?:add|remove|toggle|contains)\(\s*['"]([\w$-]+)['"]""",
)

# Detect a CSS-module import so we know which source-file class accessors
# correspond to module classes (``import styles from './x.module.css'``).
_CSS_MODULE_IMPORT_PATTERN = re.compile(
    r"""import\s+(?:type\s+)?(\w+)\s+from\s+['"]([^'"]*\.module\.css)['"]""",
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
        css_classes: dict[str, list[tuple[str, int]]] = {}  # class -> [(file, line)]
        used_css_classes: set[str] = set()
        components: dict[str, str] = {}  # ComponentName -> file
        routes: list[tuple[str, str]] = []  # (route_path, file)
        star_reexports: list[tuple[str, str]] = []  # (barrel_file, module_spec)

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

            # Parse className usage in TSX/JSX files
            if rel_path.endswith((".tsx", ".jsx")):
                self._parse_classname_usage(content, used_css_classes)
                # CSS-module accessor usage (styles.card / styles['card']).
                # Only register accessors imported as a CSS module so we don't
                # treat every object property access (e.g. `user.name`) as a
                # CSS class.
                self._parse_css_module_usage(content, used_css_classes)

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
        file_set = {str(f.relative_to(self.project_dir)).replace("\\", "/") for f in all_files}
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
        self._find_orphaned_css(css_classes, used_css_classes, result)

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

            # Filter out non-included directories when include_spec is set
            if self.include_spec:
                dirs[:] = [
                    d for d in dirs if self.include_spec.match_file(f"{rel_root}/{d}/" if rel_root != "." else f"{d}/")
                ]

            for fname in filenames:
                rel_path = f"{rel_root}/{fname}" if rel_root != "." else fname
                if self.ignore_spec.match_file(rel_path):
                    continue
                if self.include_spec and not self.include_spec.match_file(rel_path):
                    continue

                filepath = Path(root) / fname
                if self._is_scannable_file(rel_path):
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
        """Record re-export forwarding so barrel/index files don't false-positive.

        ``export { A, B as C } from './mod'`` consumes ``A`` and ``B`` from
        ``./mod``; the consumed (left-hand) names are registered as imports of
        this file so the source module's exports are not reported as unused.
        ``export * from './mod'`` forwards every export of ``./mod``; the
        (file, module) pair is recorded so those exports can be treated as used
        once ``./mod`` is resolved to a scanned file.
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

    def _parse_css_classes(self, content: str, rel_path: str, css_classes: dict[str, list[tuple[str, int]]]) -> None:
        """Extract CSS class names defined in a stylesheet."""
        for i, line in enumerate(content.splitlines(), 1):
            for m in _CSS_CLASS_PATTERN.finditer(line):
                cls = m.group(1)
                css_classes.setdefault(cls, []).append((rel_path, i))

    def _parse_classname_usage(self, content: str, used_css_classes: set[str]) -> None:
        """Extract CSS class names used in JSX className attributes."""
        for m in _CLASSNAME_PATTERN.finditer(content):
            for group in m.groups():
                if group:
                    for cls in group.split():
                        used_css_classes.add(cls)

    def _parse_css_module_usage(self, content: str, used_css_classes: set[str]) -> None:
        """Extract CSS-module class names consumed via object accessors.

        The canonical Next.js/React pattern is::

            import styles from './Card.module.css';
            <div className={styles.card}>...</div>

        We first find any ``*.module.css`` imports (binding name ``styles``)
        so that accessor use ``styles.card`` registers ``card`` as a used
        class. Bracket access ``styles['card-hover']`` is also captured.
        Without this, every CSS-module class is falsely reported as orphaned
        and marked removable=True, risking deletion of live styles.
        """
        # Map the local binding (e.g. ``styles``) to a CSS-module import so
        # only module accessors are treated as class names.
        module_bindings = {m.group(1) for m in _CSS_MODULE_IMPORT_PATTERN.finditer(content)}
        if not module_bindings:
            return
        for m in _CSS_MODULE_USAGE_PATTERN.finditer(content):
            groups = m.groups()
            # Bracket form `styles['card-hover']` -> groups = (binding, name).
            # Dot form `styles.card` -> groups = (None, None); the whole match
            # is "binding.attr". Distinguish by whether a bracket name exists.
            bracket_binding, bracket_name = groups
            if bracket_name is not None:
                if bracket_binding in module_bindings:
                    used_css_classes.add(bracket_name)
                continue
            # Dot form `styles.card` -> the whole match is "binding.attr".
            full = m.group(0)
            binding, _, attr = full.partition(".")
            if binding in module_bindings and attr and attr[0] != "_":
                # Skip internal/private-ish accessors (e.g. styles.toString).
                used_css_classes.add(attr)

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
        css_classes: dict[str, list[tuple[str, int]]],
        used_css_classes: set[str],
        result: ScanResult,
    ) -> None:
        """Find CSS classes defined but never used in JSX."""
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
                continue
            if cls in used_css_classes:
                continue
            for file, line in locations:
                result.findings.append(
                    Finding(
                        file=file,
                        line=line,
                        name=cls,
                        category="orphaned_css",
                        detail=f"CSS class '.{cls}' is not used in any JSX className",
                        removable=True,
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
