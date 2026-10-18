"""A bounded runtime view for CSS usage, without changing symbol analysis.

This is deliberately not a TypeScript transpiler. Only syntactically established
type contexts are erased; an unrecognized boundary retains the original source.
Offsets and newlines survive so the existing JSX/string readers keep their own
grammar. Runtime class-field initializers are normalized to property syntax.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class _Token:
    value: str
    start: int
    end: int
    word: bool = False
    expressions: tuple[tuple[int, int], ...] = ()
    complete: bool = True
    uncertain: bool = False


_WORD = re.compile(r"[\w$]+", re.UNICODE)
_JSX_OPENING = re.compile(r"<[a-zA-Z][\w:.-]*(?=[\s/>])(?!\s*(?:=|extends\b))")
_JSX_CLOSING = re.compile(r"</(?:[\w$][\w$:.-]*\s*)?>")
_CLASS_VALUE_OPERATORS = {":", "=", "+=", "-=", "*=", "/=", "%=", "**=", "&=", "|=", "^=", "&&=", "||=", "??="}
_PREFIX = {"keyof", "readonly", "unique", "typeof", "asserts", "abstract", "new"}
_MODIFIERS = {"public", "private", "protected", "static", "readonly", "abstract", "declare", "override", "accessor"}
_EXPRESSION_PREFIX = {
    "return",
    "throw",
    "yield",
    "await",
    "new",
    "case",
    "delete",
    "void",
    "typeof",
    "in",
    "instanceof",
    "of",
    "else",
    "do",
    "extends",
    "export",
    "default",
    "const",
    "let",
    "var",
    "function",
    "class",
    "interface",
    "type",
    "declare",
    "import",
    "namespace",
    "module",
    "abstract",
    "as",
    "satisfies",
    "keyof",
    "infer",
    "is",
    "asserts",
}
_REGEX_PREFIX = {
    "return",
    "throw",
    "yield",
    "await",
    "new",
    "case",
    "delete",
    "void",
    "typeof",
    "in",
    "instanceof",
    "of",
    "else",
    "do",
    "extends",
    "default",
    "=",
    "(",
    "[",
    "{",
    ",",
    ":",
    ";",
    "!",
    "?",
    "=>",
    "~",
    "+",
    "-",
    "*",
    "/",
    "%",
    "**",
    "<",
    ">",
    "&",
    "|",
    "^",
    "&&",
    "||",
    "??",
    "==",
    "!=",
    "===",
    "!==",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "&&=",
    "||=",
    "??=",
    "**=",
}


def _regex_context(tokens: list[_Token]) -> bool:
    if not tokens:
        return True
    previous = tokens[-1].value
    if len(tokens) > 1 and tokens[-2].value in {".", "?."}:
        return False
    if (
        previous == "!"
        and len(tokens) > 1
        and (tokens[-2].word and tokens[-2].value not in _EXPRESSION_PREFIX or tokens[-2].value in {")", "]"})
    ):
        return False  # TypeScript's postfix non-null assertion ends an expression.
    if previous == ")":
        depth = 1
        for index in range(len(tokens) - 2, -1, -1):
            if tokens[index].value == ")":
                depth += 1
            elif tokens[index].value == "(":
                depth -= 1
                if not depth:
                    return index > 0 and tokens[index - 1].value in {"if", "while", "for", "with", "switch", "catch"}
        return False
    return previous in _REGEX_PREFIX


def _jsx_element(source: str, index: int, depth: int) -> _Token | None:
    """Read one complete element, exposing only its JavaScript expressions."""
    if depth > 80:
        return None
    start = index
    expressions = []
    uncertain = False
    if source.startswith("<>", index):
        name = ""
        index += 2
    else:
        opening = _JSX_OPENING.match(source, index)
        if not opening:
            return None
        name = source[index + 1 : opening.end()]
        index = opening.end()
        while index < len(source):
            if source.startswith("/>", index):
                return _Token(
                    source[start : index + 2], start, index + 2, expressions=tuple(expressions), uncertain=uncertain
                )
            if source[index] == ">":
                index += 1
                break
            if source[index] in "'\"":
                end = source.find(source[index], index + 1)
                if end < 0:
                    return None
                index = end + 1
            elif source[index] == "{":
                _, end, nested_uncertain = _lex(source, index + 1, interpolation=True, depth=depth + 1, jsx=True)
                if end >= len(source):
                    return None
                expressions.append((index + 1, end))
                uncertain |= nested_uncertain
                index = end + 1
            elif source[index] == "<":
                return None  # Generic JSX arguments retain the existing token path.
            else:
                index += 1
        else:
            return None
    while index < len(source):
        if source.startswith("</", index):
            closing = _JSX_CLOSING.match(source, index)
            if not closing or source[index + 2 : closing.end() - 1].strip() != name:
                return None
            return _Token(
                source[start : closing.end()], start, closing.end(), expressions=tuple(expressions), uncertain=uncertain
            )
        if source[index] == "<":
            child = _jsx_element(source, index, depth + 1)
            if child is None:
                return None
            expressions.extend(child.expressions)
            uncertain |= child.uncertain
            index = child.end
        elif source[index] == "{":
            _, end, nested_uncertain = _lex(source, index + 1, interpolation=True, depth=depth + 1, jsx=True)
            if end >= len(source):
                return None
            expressions.append((index + 1, end))
            uncertain |= nested_uncertain
            index = end + 1
        else:
            index += 1  # Child text has no JavaScript quotes, comments or templates.
    return None


def _lex(
    source: str, index: int = 0, *, interpolation: bool = False, depth: int = 0, jsx: bool = True
) -> tuple[list[_Token], int, bool]:
    tokens = []
    braces = 0
    uncertain = False
    jsx_tags: list[tuple[int, int]] = []
    while index < len(source):
        start = index
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if (
            jsx
            and char == "<"
            and _regex_context(tokens)
            and (_JSX_OPENING.match(source, index) or source.startswith("<>", index))
        ):
            element = _jsx_element(source, index, depth + 1)
            if element:
                tokens.append(element)
                index = element.end
                uncertain |= element.uncertain
                continue
            # Incomplete JSX cannot establish that a later runtime use is absent.
            tokens.append(_Token(source[start:], start, len(source), complete=False, uncertain=True))
            return tokens, len(source), True
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            index = len(source) if end < 0 else end
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            index = len(source) if end < 0 else end + 2
            continue
        if interpolation and char == "}" and not braces:
            return tokens, index, uncertain
        if jsx and char == "<" and (opening := _JSX_OPENING.match(source, index)):
            jsx_tags.append((braces, opening.end()))
        elif char == ">" and jsx_tags and jsx_tags[-1][0] == braces:
            jsx_tags.pop()
        if char == "{":
            braces += 1
        elif char == "}":
            braces -= 1
        if char == "`":
            index += 1
            expressions = []
            complete = False
            template_uncertain = False
            while index < len(source):
                if source[index] == "\\":
                    index += 2
                elif source[index] == "`":
                    index += 1
                    complete = True
                    break
                elif source.startswith("${", index):
                    if depth > 80:
                        index = len(source)
                        break
                    expression = index + 2
                    _, end, nested_uncertain = _lex(source, expression, interpolation=True, depth=depth + 1, jsx=jsx)
                    template_uncertain |= nested_uncertain
                    if end == len(source):
                        index = end
                        break
                    expressions.append((expression, end))
                    index = end + 1
                else:
                    index += 1
            tokens.append(
                _Token(
                    source[start:index],
                    start,
                    index,
                    expressions=tuple(expressions),
                    complete=complete,
                    uncertain=template_uncertain,
                )
            )
            continue
        if char in "'\"":
            # JSX attribute delimiters follow HTML rules: a backslash before
            # the closing quote is literal. JavaScript expressions inside
            # braces still use the ordinary escaped-string grammar.
            raw_attribute = bool(
                jsx_tags
                and jsx_tags[-1][0] == braces
                and len(tokens) >= 2
                and tokens[-1].value == "="
                and tokens[-2].word
                and tokens[-2].start >= jsx_tags[-1][1]
            )
            index += 1
            complete = False
            while index < len(source):
                if source[index] == "\\" and not raw_attribute:
                    index += 2
                elif source[index] == char:
                    index += 1
                    complete = True
                    break
                elif source[index] in "\r\n" and not raw_attribute:
                    break
                else:
                    index += 1
            tokens.append(_Token(source[start:index], start, index, complete=complete))
            continue
        # Closing tags/fragments and self-closing delimiters contain no runtime
        # expressions. A slash after '<' or a generic '>' must not consume the
        # following sibling's class expressions as an opaque regular expression.
        closing_jsx = _JSX_CLOSING.match(source, index)
        if closing_jsx or source.startswith("/>", index) and tokens and tokens[-1].value == ">":
            index = closing_jsx.end() if closing_jsx else index + 2
            tokens.append(_Token(source[start:index], start, index))
            continue
        # A regex is opaque. Failed recognition leaves the slash as punctuation,
        # including JSX closing tags and divisions; it never swallows a file tail.
        if char == "/" and tokens and tokens[-1].value in {")", "}"} and not _regex_context(tokens):
            uncertain = True
        if char == "/" and _regex_context(tokens):
            regex_uncertain = bool(tokens and tokens[-1].value in {">", "!", "await", "yield", "of"})
            uncertain |= regex_uncertain
            end = index + 1
            bracket = False
            while end < len(source) and source[end] not in "\r\n":
                if source[end] == "\\":
                    end += 2
                    continue
                if source[end] == "[":
                    bracket = True
                elif source[end] == "]":
                    bracket = False
                elif source[end] == "/" and not bracket:
                    end += 1
                    while end < len(source) and source[end].isalpha():
                        end += 1
                    tokens.append(_Token(source[start:end], start, end, uncertain=regex_uncertain))
                    index = end
                    break
                end += 1
            if index != start:
                continue
        word = _WORD.match(source, index)
        if word:
            index = word.end()
            tokens.append(_Token(word.group(), start, index, True))
            continue
        operator = next(
            (
                value
                for value in (
                    "...",
                    "===",
                    "!==",
                    "&&=",
                    "||=",
                    "??=",
                    "**=",
                    "=>",
                    "?.",
                    "++",
                    "--",
                    "&&",
                    "||",
                    "??",
                    "==",
                    "!=",
                    "**",
                    "+=",
                    "-=",
                    "*=",
                    "/=",
                    "%=",
                    "&=",
                    "|=",
                    "^=",
                )
                if source.startswith(value, index)
            ),
            char,
        )
        index += len(operator)
        tokens.append(_Token(operator, start, index))
    return tokens, index, uncertain


def _tokens(source: str, *, jsx: bool = True) -> list[_Token]:
    return _lex(source, jsx=jsx)[0]


class _RuntimeView:
    def __init__(self, source: str, *, jsx: bool = True):
        self.source = source
        self.tokens = _tokens(source, jsx=jsx)
        self.pairs: dict[int, int] = {}
        self.parents: dict[int, int | None] = {}
        stack = []
        for index, token in enumerate(self.tokens):
            self.parents[index] = stack[-1] if stack else None
            if token.value in {"{", "[", "("}:
                stack.append(index)
            elif token.value in {"}", "]", ")"} and stack:
                opening = stack[-1]
                if {"{": "}", "[": "]", "(": ")"}[self.value(opening)] == token.value:
                    stack.pop()
                    self.pairs[opening] = index
        self.erased: list[tuple[int, int]] = []
        self.replacements: dict[int, str] = {}

    def value(self, index: int) -> str:
        return self.tokens[index].value if 0 <= index < len(self.tokens) else ""

    def erase(self, start: int, end: int) -> None:
        if 0 <= start < end <= len(self.tokens) and not any(token.uncertain for token in self.tokens[start:end]):
            self.erased.append((self.tokens[start].start, self.tokens[end - 1].end))

    def same_line(self, left: int, right: int) -> bool:
        return 0 <= left < right < len(self.tokens) and not any(
            char in self.source[self.tokens[left].end : self.tokens[right].start] for char in "\r\n\u2028\u2029"
        )

    def angle_end(self, start: int) -> int | None:
        depth = 0
        index = start
        while index < len(self.tokens):
            value = self.value(index)
            if value == "<":
                depth += 1
            elif value == ">":
                depth -= 1
                if depth == 0:
                    return index + 1
            elif value in {"{", "[", "("}:
                if index not in self.pairs:
                    return None
                index = self.pairs[index]
            elif value in {";", "}", ")", "]"}:
                return None
            index += 1
        return None

    def type_end(self, start: int, *, strict: bool = False, depth: int = 0) -> int | None:
        if depth > 80 or start >= len(self.tokens):
            return None
        value = self.value(start)
        function_type = value in {"(", "<"}
        if value in {"|", "&"}:
            return self.type_end(start + 1, strict=strict, depth=depth + 1)
        if value in _PREFIX:
            index = self.type_end(start + 1, strict=strict, depth=depth + 1)
        elif value == "infer":
            index = start + 2 if self.tokens[start + 1 : start + 2] and self.tokens[start + 1].word else None
        elif value == "-":
            index = start + 2 if self.value(start + 1)[:1].isdigit() else None
        elif value in {"{", "[", "("}:
            closing = self.pairs.get(start)
            if closing is None:
                return None
            index = closing + 1
            if strict and value == "{" and not self.type_members(start, closing, depth + 1):
                return None
            if strict and value == "(":
                if self.value(index) == "=>":
                    if not self.parameters_are_types(start, closing):
                        return None
                elif self.type_end(start + 1, strict=True, depth=depth + 1) != closing:
                    return None
        elif value == "<":
            index = self.angle_end(start)
            if index is None or self.value(index) != "(" or index not in self.pairs:
                return None
            closing = self.pairs[index]
            if strict and not self.parameters_are_types(index, closing):
                return None
            index = closing + 1
            if self.value(index) != "=>":
                return None
        elif self.tokens[start].word or (value[:1] in {"'", '"', "`"} and self.tokens[start].complete):
            index = start + 1
            if value == "import" and self.value(index) == "(" and index in self.pairs:
                index = self.pairs[index] + 1
        else:
            return None
        if index is None:
            return None
        while True:
            value = self.value(index)
            if value == "." and index + 1 < len(self.tokens) and self.tokens[index + 1].word:
                index += 2
            elif value == "<":
                end = self.angle_end(index)
                if end is None or (strict and not self.type_arguments(index, end - 1, depth + 1)):
                    return None
                index = end
            elif value == "[" and index in self.pairs:
                index = self.pairs[index] + 1
            else:
                break
        if self.value(index) in {"|", "&", "is"} or (function_type and self.value(index) == "=>"):
            return self.type_end(index + 1, strict=strict, depth=depth + 1)
        if self.value(index) == "extends":
            condition = self.type_end(index + 1, strict=strict, depth=depth + 1)
            if condition is None or self.value(condition) != "?":
                return None
            accepted = self.type_end(condition + 1, strict=strict, depth=depth + 1)
            if accepted is None or self.value(accepted) != ":":
                return None
            return self.type_end(accepted + 1, strict=strict, depth=depth + 1)
        return index

    def type_arguments(self, opening: int, closing: int, depth: int = 0) -> bool:
        index = opening + 1
        while index < closing:
            end = self.type_end(index, strict=True, depth=depth + 1)
            if end is None or end > closing:
                return False
            if end == closing:
                return True
            if self.value(end) != ",":
                return False
            index = end + 1
        return index == closing

    def parameters_are_types(self, opening: int, closing: int) -> bool:
        index = opening + 1
        while index < closing:
            if self.value(index) == "=":
                return False  # An initializer is a runtime expression, not a function type.
            if index in self.pairs:
                index = self.pairs[index]
            index += 1
        return True

    def type_members(self, opening: int, closing: int, depth: int) -> bool:
        index = opening + 1
        while index < closing:
            if self.value(index) in {";", ",", "readonly", "+", "-", "new"}:
                index += 1
                continue
            if self.value(index) in {"[", "("} and index in self.pairs:
                index = self.pairs[index] + 1
            elif self.tokens[index].word or self.value(index)[:1] in {"'", '"'}:
                index += 1
            else:
                return False
            if self.value(index) == "?":
                index += 1
            if self.value(index) == "<":
                index = self.angle_end(index)
                if index is None:
                    return False
            if self.value(index) == "(" and index in self.pairs:
                index = self.pairs[index] + 1
            if self.value(index) != ":":
                return False
            end = self.type_end(index + 1, strict=True, depth=depth + 1)
            if end is None or end > closing:
                return False
            if (
                end < closing
                and self.value(end) not in {";", ","}
                and "\n" not in self.source[self.tokens[end - 1].end : self.tokens[end].start]
            ):
                return False
            index = end
        return index == closing

    def declaration_start(self, index: int) -> bool:
        previous = self.value(index - 1)
        if not previous or previous in {";", "{", "}", "export", "default", "declare"}:
            return True
        return (
            previous not in {".", "?.", ":", "=", ",", "(", "["}
            and "\n" in self.source[self.tokens[index - 1].end : self.tokens[index].start]
        )

    def declarations(self) -> None:
        for index, token in enumerate(self.tokens):
            value = token.value
            if value in {"interface", "type"} and self.declaration_start(index) and self.same_line(index, index + 1):
                cursor = index + 1
                if cursor >= len(self.tokens) or not self.tokens[cursor].word:
                    continue
                cursor += 1
                if self.value(cursor) == "<":
                    cursor = self.angle_end(cursor)
                    if cursor is None:
                        continue
                if value == "type" and self.value(cursor) == "=":
                    end = self.type_end(cursor + 1)
                    if end is not None:
                        self.erase(index, end)
                elif value == "interface":
                    while cursor < len(self.tokens) and self.value(cursor) not in {"{", ";", "}"}:
                        if self.value(cursor) == "<":
                            end = self.angle_end(cursor)
                            if end is None:
                                break
                            cursor = end
                        else:
                            cursor += 1
                    if self.value(cursor) == "{" and cursor in self.pairs:
                        self.erase(index, self.pairs[cursor] + 1)
            elif value == "declare" and self.declaration_start(index) and self.same_line(index, index + 1):
                kind = self.value(index + 1)
                if kind in {"class", "namespace", "module", "global", "enum"}:
                    cursor = index + 2
                    while cursor < len(self.tokens) and self.value(cursor) not in {"{", ";"}:
                        if self.value(cursor) == "<":
                            end = self.angle_end(cursor)
                            if end is None:
                                break
                            cursor = end
                        else:
                            cursor += 1
                    if cursor in self.pairs:
                        self.erase(index, self.pairs[cursor] + 1)
                elif kind in {"const", "let", "var", "function"}:
                    if kind == "function":
                        cursor = index + 3
                        if self.value(cursor) == "<":
                            cursor = self.angle_end(cursor)
                        if cursor is None or self.value(cursor) != "(" or cursor not in self.pairs:
                            continue
                        cursor = self.pairs[cursor] + 1
                        if self.value(cursor) == ":":
                            cursor = self.type_end(cursor + 1)
                    else:
                        cursor = self.binding(index + 2)
                    if (
                        cursor is not None
                        and cursor > index + 2
                        and (
                            self.value(cursor) in {";", "", "}"}
                            or "\n" in self.source[self.tokens[cursor - 1].end : self.tokens[cursor].start]
                        )
                    ):
                        self.erase(index, cursor + (self.value(cursor) == ";"))
            elif (
                value in {"import", "export"}
                and self.value(index + 1) == "type"
                and self.value(index + 2) not in {"from", ",", "="}
                and (value == "import" or self.same_line(index + 1, index + 2))
            ):
                cursor = index + 2
                while cursor < len(self.tokens):
                    if self.value(cursor) == ";":
                        cursor += 1
                        break
                    if (
                        cursor > index + 2
                        and "\n" in self.source[self.tokens[cursor - 1].end : self.tokens[cursor].start]
                    ):
                        break
                    if cursor in self.pairs:
                        cursor = self.pairs[cursor]
                    cursor += 1
                self.erase(index, cursor)

    def binding(self, index: int) -> int:
        while self.value(index) in _MODIFIERS or self.value(index) == "...":
            index += 1
        if self.value(index) in {"{", "["} and index in self.pairs:
            index = self.pairs[index] + 1
        elif index < len(self.tokens) and self.tokens[index].word:
            index += 1
        else:
            return index
        if self.value(index) in {"?", "!"}:
            index += 1
        if self.value(index) == ":":
            end = self.type_end(index + 1)
            if end is not None:
                self.erase(index, end)
                return end
        return index

    def parameters(self, opening: int) -> None:
        closing = self.pairs.get(opening)
        if closing is None:
            return
        cursor = opening + 1
        while cursor < closing:
            cursor = self.binding(cursor)
            while cursor < closing and self.value(cursor) != ",":
                if cursor in self.pairs:
                    cursor = self.pairs[cursor]
                cursor += 1
            cursor += 1

    def annotations(self) -> None:
        for index, token in enumerate(self.tokens):
            if token.value in {"const", "let", "var"} and self.value(index - 1) not in {".", "?."}:
                cursor = index + 1
                while cursor < len(self.tokens):
                    end = self.binding(cursor)
                    if end == cursor:
                        break
                    cursor = end
                    while cursor < len(self.tokens) and self.value(cursor) not in {",", ";", "}"}:
                        if cursor in self.pairs:
                            cursor = self.pairs[cursor]
                        cursor += 1
                    if self.value(cursor) != ",":
                        break
                    cursor += 1
            elif token.value == "(" and index in self.pairs:
                closing = self.pairs[index]
                end = closing + 1
                result = self.type_end(end + 1) if self.value(end) == ":" else end
                arrow = result is not None and self.value(result) == "=>"
                # Function declarations, function expressions and methods have
                # a distinct header. Calls/control-flow parentheses are excluded.
                before = self.value(index - 1)
                head = index - 2
                while self.value(head) in {"*", "async", "get", "set"} | _MODIFIERS:
                    head -= 1
                named_function = before == "function" or self.value(head) == "function"
                method = (
                    before not in {"if", "for", "while", "switch", "catch", "with"}
                    and index > 0
                    and self.tokens[index - 1].word
                    and self.value(head) in {"{", ",", ";", "}"}
                    and result is not None
                    and self.value(result) == "{"
                )
                if arrow or named_function or method:
                    self.parameters(index)
                    if self.value(end) == ":" and result is not None:
                        self.erase(end, result)
            elif token.value in {"as", "satisfies"} and index > 0:
                previous = self.tokens[index - 1]
                if (
                    self.same_line(index - 1, index)
                    and previous.value not in _EXPRESSION_PREFIX | {".", "?."}
                    and (previous.word or previous.value in {")", "]", "}"} or previous.value[:1] in {"'", '"', "`"})
                ):
                    end = self.type_end(index + 1)
                    if end is not None:
                        self.erase(index, end)

    def generic_arguments(self, *, tsx: bool) -> None:
        for index, token in enumerate(self.tokens):
            if token.value != "<":
                continue
            end = self.angle_end(index)
            if end is None:
                continue
            before = self.value(index - 1)
            after = self.value(end)
            value_call = (
                index > 0
                and (self.tokens[index - 1].word or before in {")", "]"})
                and (after in {"(", ";", ",", ")", "]", "}", ".", "?.", ""} or after.startswith("`"))
            )
            jsx_start = index - 1
            while jsx_start > 0 and (self.tokens[jsx_start].word or self.value(jsx_start) in {".", ":"}):
                jsx_start -= 1
            jsx_argument = tsx and self.value(jsx_start) == "<" and jsx_start < index - 1
            assertion = not tsx and before in {"", "=", "(", "[", ",", ":", "return", "=>", "?"}
            if (value_call or jsx_argument or assertion) and self.type_arguments(index, end - 1):
                self.erase(index, end)
                continue
            # Generic function headers have declaration parameters rather than
            # type arguments (constraints/defaults are legal). Require a body.
            if after == "(" and end in self.pairs:
                closing = self.pairs[end]
                body = closing + 1
                if self.value(body) == ":":
                    body = self.type_end(body + 1)
                if (
                    body is not None
                    and self.value(body) in {"=>", "{"}
                    and (
                        self.value(index - 2) in {"function", "{", ",", ";", "}"}
                        or before in {"=", "("}
                        or before == "async"
                        and self.value(index - 2) in {"=", "(", ":", ",", "return"}
                    )
                ):
                    self.erase(index, end)
                    self.parameters(end)
                    if self.value(closing + 1) == ":":
                        self.erase(closing + 1, body)

    def class_fields(self, *, typescript: bool) -> None:
        for index, token in enumerate(self.tokens):
            if (
                token.value != "class"
                or self.value(index - 1) in {".", "?."}
                or self.value(index + 1) in {":", "=", "("}
            ):
                continue
            opening = index + 1
            while opening < len(self.tokens) and self.value(opening) not in {"{", ";"}:
                if self.value(opening) == "<":
                    end = self.angle_end(opening)
                    if end is None:
                        break
                    if typescript:
                        self.erase(opening, end)
                    opening = end
                    continue
                if opening in self.pairs:
                    opening = self.pairs[opening]
                opening += 1
            closing = self.pairs.get(opening)
            if closing is None:
                continue
            cursor = opening + 1
            while cursor < closing:
                start = cursor
                while self.value(cursor) in _MODIFIERS:
                    cursor += 1
                name = self.value(cursor)
                if cursor >= len(self.tokens) or not self.tokens[cursor].word:
                    cursor = self.pairs.get(cursor, cursor) + 1
                    continue
                cursor += 1
                if self.value(cursor) in {"?", "!"}:
                    cursor += 1
                if typescript and self.value(cursor) == ":":
                    end = self.type_end(cursor + 1)
                    if end is not None:
                        self.erase(cursor, end)
                        cursor = end
                if self.value(cursor) == "=":
                    if name in {"className", "class"}:
                        self.replacements[self.tokens[cursor].start] = ":"
                elif name in {"className", "class"} and self.value(cursor) != "(":
                    self.erase(start, cursor)
                # Stop at a peer member, respecting initializer/method bodies.
                while cursor < closing:
                    if self.value(cursor) == ";":
                        cursor += 1
                        break
                    if cursor in self.pairs:
                        cursor = self.pairs[cursor] + 1
                        if self.value(cursor - 1) == "}" and self.value(cursor) != ";":
                            break
                        continue
                    if cursor > start and "\n" in self.source[self.tokens[cursor - 1].end : self.tokens[cursor].start]:
                        break
                    cursor += 1

    def render(self, path: str, depth: int) -> str:
        output = list(self.source)
        for token in self.tokens:
            for start, end in token.expressions:
                output[start:end] = class_usage_source(self.source[start:end], path, depth=depth + 1)
        merged = []
        for start, end in sorted(self.erased):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        for start, end in merged:
            for index in range(start, end):
                if output[index] not in "\r\n":
                    output[index] = " "
        for index, value in self.replacements.items():
            if output[index] != " ":
                output[index] = value
        return "".join(output)


def class_usage_source(source: str, path: str, *, depth: int = 0) -> str:
    """Return only established runtime class-use syntax; keep uncertain input."""
    if path.endswith(".d.ts"):
        return re.sub(r"[^\r\n]", " ", source)
    if depth > 80:
        return source
    view = _RuntimeView(source, jsx=not path.endswith(".ts"))
    typescript = path.endswith((".ts", ".tsx"))
    if typescript:
        view.declarations()
        view.annotations()
        view.generic_arguments(tsx=path.endswith(".tsx"))
    view.class_fields(typescript=typescript)
    return view.render(path, depth)


def class_value_positions(source: str, *, depth: int = 0, jsx: bool = True) -> tuple[set[int], set[int], set[int]]:
    """Recognize code-token starts, excluding comments, strings and regex bodies."""
    tokens = _tokens(source, jsx=jsx)
    property_keys = {
        token.start
        for token in tokens
        if token.value in {"className", "class", "'className'", '"className"', "'class'", '"class"'}
    }
    calls = {token.start for token in tokens if token.value in {"classNames", "clsx"}}
    words = {token.start for token in tokens if token.word}
    for token in tokens:
        if token.uncertain or token.value.startswith("`") and (not token.complete or depth > 80):
            # Broken or excessively nested templates cannot establish absence of
            # runtime expressions. Retain all possible class-related code starts.
            words.update(
                token.start + match.start() for match in _WORD.finditer(token.value) if match.group() != "import"
            )
            property_keys.update(words)
            property_keys.update(
                token.start + match.start()
                for match in re.finditer(r"""['"](?:className|class)['"]\s*:""", token.value)
            )
            calls.update(words)
        elif token.expressions:
            for start, end in token.expressions:
                nested_properties, nested_calls, nested_words = class_value_positions(
                    source[start:end], depth=depth + 1, jsx=jsx
                )
                property_keys.update(start + value for value in nested_properties)
                calls.update(start + value for value in nested_calls)
                words.update(start + value for value in nested_words)
    return property_keys, calls, words


def class_property_positions(source: str, *, depth: int = 0, jsx: bool = True) -> list[tuple[str, int, int, bool]]:
    """Return class property/write keys, offsets and compound uncertainty.

    Comments are already skipped by the lexer. Exact assignment operators avoid
    treating equality tests or arrows as writes; quoted member keys are decoded
    by the caller's existing JavaScript string reader.
    """
    tokens = _tokens(source, jsx=jsx)
    assignments = []
    for index, token in enumerate(tokens):
        operator = index + 1
        if token.value[:1] in {"'", '"', "`"}:
            if (
                index >= 2
                and tokens[index - 1].value == "["
                and tokens[operator : operator + 1]
                and tokens[operator].value == "]"
                and (tokens[index - 2].word or tokens[index - 2].value in {")", "]", "!"})
            ):
                operator += 1
            elif operator >= len(tokens) or tokens[operator].value not in {":", "="}:
                operator = len(tokens)
        elif token.value not in {"className", "class"}:
            operator = len(tokens)
        if operator < len(tokens) and tokens[operator].value in _CLASS_VALUE_OPERATORS:
            start = tokens[operator + 1].start if operator + 1 < len(tokens) else tokens[operator].end
            assignments.append((token.value, token.start, start, tokens[operator].value not in {":", "="}))
        if token.expressions and depth < 80:
            for start, end in token.expressions:
                assignments.extend(
                    (key, start + key_offset, start + offset, compound)
                    for key, key_offset, offset, compound in class_property_positions(
                        source[start:end], depth=depth + 1, jsx=jsx
                    )
                )
        elif token.uncertain and re.search(r"\b(?:className|class)\b[\s\S]*=", token.value):
            # An ambiguous lexical range cannot establish absence of a runtime
            # write. Keep possible global uses uncertain rather than delete CSS.
            assignments.append(("className", token.start, token.end, True))
    return assignments
