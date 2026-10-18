"""Erased TypeScript declarations cannot invent or obscure runtime CSS uses."""

import time

import pytest
from click.testing import CliRunner

from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner


@pytest.fixture(autouse=True)
def no_countdown(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)


ERASED_CASES = [
    ('interface Props { className: "legacy" }', "ts"),
    ("type Props = { className: string }", "ts"),
    ('export interface Props<T extends { className: "legacy" }> { className: string }', "tsx"),
    ('export type Props = { nested: { className: "legacy" }; class: string };', "ts"),
    ('type Props = { readonly className?: "legacy"; class: string }', "ts"),
    ('type Props =\n | { className: "legacy" }\n | { class: string }\nconst next = 1;', "ts"),
    ('type Props = ({ className: "legacy" } & { class: string })[];', "ts"),
    ('type Props<T> = T extends string ? {className: "legacy"} : {class: string};', "ts"),
    ('type Props = () => { className: "legacy" };', "ts"),
    ("type Props = <T>(value: T) => { className: string };", "ts"),
    ('type Props = `className: "legacy"`;', "ts"),
    ("declare const props: { className: string };", "ts"),
    ('declare function props(): { className: "legacy" };', "ts"),
    ('declare class Props { className: "legacy"; }', "ts"),
    ("declare namespace Props { const attrs: {className: string}; }", "ts"),
    ('declare module "props" { export interface Props { className: string } }', "ts"),
    ('export {}; declare global { interface Props { className: "legacy" } }', "ts"),
    ("export declare const props: { className: string };", "ts"),
    ("export const props: { className: string };", "d.ts"),
    ("const props: { className: string } = {} as never;", "ts"),
    ("function view(props: { className: string }): void {}", "ts"),
    ("const view = (props: { className: string }): void => {};", "tsx"),
    ('class Props { className: "legacy"; }', "ts"),
    ('class Props { declare className: "legacy"; }', "ts"),
    ("class Props { attrs: { className: string }; }", "ts"),
    ("import type styles from './Card.module.css'; type Props = typeof styles['legacy'];", "ts"),
    ("import styles from './Card.module.css'; type Props = typeof styles['legacy'];", "ts"),
    ('interface Props extends Base<{className: "legacy"}> { className: string }', "ts"),
    ("type Props = Readonly<{className: string}>;", "ts"),
    ('type Props = new (value: {className: string}) => {className: "legacy"};', "ts"),
    ('type Props = { [Key in "className"]: string };', "ts"),
    ('type Props = {className: import("./props").Name};', "ts"),
    ('type Props = {className: "legacy"} | null;', "ts"),
    ("declare const props: {className: string}\nconst next = 1;", "ts"),
    ("declare function props(): {className: string}\nconst next = 1;", "ts"),
    ('declare class Props<T extends {className: string}> { className: "legacy" }', "ts"),
    ("const props = source<{className: string}>;", "ts"),
]


RUNTIME_CASES = [
    ('interface Props { className: "legacy" }\nconst attrs = {className: "live"};', "ts"),
    ('type Props = {className: string}\nconst attrs = {className: "live"};', "ts"),
    ('type Props = {className: string}\nconst view = <div className="live" />;', "tsx"),
    ('const attrs: {className: string} = {className: "live"};', "ts"),
    ('let a: {className: string}, attrs: {className: string} = {className: "live"};', "ts"),
    ('function view(props: {className: string} = {className: "live"}) {}', "ts"),
    ('function view(): {className: string} { return {className: "live"}; }', "ts"),
    ('const view = (): {className: string} => ({className: "live"});', "tsx"),
    ('const attrs = {className: "live"} satisfies {className: string};', "ts"),
    ('const attrs = ({className: "live"} as {className: string});', "ts"),
    ('const attrs = <{className: string}>{className: "live"};', "ts"),
    ('declare function make<T>(value: T): T; make<{className: string}>({className: "live"});', "ts"),
    ('const view = <Button<{className: string}> className="live" />;', "tsx"),
    ('function view<T extends {className: string}>() { return {className: "live"}; }', "ts"),
    ('const view = <T extends {className: string},>() => <div className="live" />;', "tsx"),
    ('class Props { className: string = "live"; }', "ts"),
    ('class Props { className = "live"; }', "js"),
    ('class Props { getAttrs(): {className: string} { return {className: "live"}; } }', "ts"),
    ('const attrs = {view(): {className: string} { return {className: "live"}; }};', "ts"),
    ('const type = {className: "live"}; const attrs = {interface: type, declare: type};', "ts"),
    ('const attrs = {interface: {className: "live"}, type: 1, declare: 1};', "ts"),
    ('const pattern = /interface\\s+Props\\{className: string\\}/; const attrs = {className: "live"};', "ts"),
    ('// interface Props {className: string}\nconst attrs = {className: "live"};', "ts"),
    ('const text = "type Props = {className: string}"; const attrs = {className: "live"};', "ts"),
    ('const text = `interface Props {className: string}`; const attrs = {className: "live"};', "ts"),
    ('const text = `${use({className: "live"})}`;', "ts"),
    ('const text = `${`${use({className: "live"})}`}`;', "ts"),
    ('const text = `${(() => {type Props = {className: string}; return use({className: "live"});})()}`;', "ts"),
    ('const text = `${/}/.test(value) ? use({className: "live"}) : null}`;', "ts"),
    ('class Props<T extends {className: string}> {className: string = "live";}', "ts"),
    ('class Props extends make({className: "live"}) {}', "ts"),
    ('class Props {other = 1\nclassName: string = "live"\n}', "ts"),
    ('namespace Props { export const attrs: {className: string} = {className: "live"}; }', "ts"),
    ('const attrs = {"className": "live"};', "ts"),
    ('const attrs = {className: clsx("live")};', "ts"),
    ('const view = <UI.Button<{className: string}> className="live" />;', "tsx"),
    ('class Props {view<T extends {className: string}>(): {className: string} {return {className: "live"};}}', "ts"),
    ('const view = async <T extends {className: string},>() => <div className="live" />;', "tsx"),
]


UNKNOWN_CASES = [
    ("type Props = {className: string}; const attrs = {className: selected};", "ts"),
    ("interface Props {className: string} const view = <div className={selected} />;", "tsx"),
    ("type Props = {className: string}; const view = <div {...attrs} />;", "tsx"),
    ('const attrs: {className: string} = {className: "prefix" + selected};', "ts"),
    ("class Props { className: string = selected; }", "ts"),
    ("class Props { className = selected; }", "js"),
    ("const attrs = {className: selected} satisfies {className: string};", "ts"),
    ("function view(): {className: string} { return {className: selected}; }", "ts"),
    ("const compared = (left < {className: selected()}) > right;", "ts"),
    ("const compared = (left < ((value = selected()) => ({className: value}))) > right;", "ts"),
    ("const text = `${use({className: selected})}`;", "ts"),
    ("const text = `${`${use({className: selected})}`}`;", "ts"),
    ("import type styles from './Card.module.css'; const attrs = {className: styles.live};", "ts"),
    ("// import styles from './Card.module.css';\nconst attrs = {className: styles.live};", "ts"),
]


CONTEXTUAL_RUNTIME_CASES = [
    ('function render() { return as({className: "live"}); }', "ts"),
    ('function render() { return satisfies({className: "live"}); }', "ts"),
    ('function* render() { yield as({className: "live"}); }', "ts"),
    ('function* render() { yield satisfies({className: "live"}); }', "ts"),
    ('async function render() { await as({className: "live"}); }', "ts"),
    ('async function render() { await satisfies({className: "live"}); }', "ts"),
    ('function render() { throw as({className: "live"}); }', "ts"),
    ('const view = new as({className: "live"});', "ts"),
    ('const view = typeof as({className: "live"});', "ts"),
    ('const view = void satisfies({className: "live"});', "ts"),
    ('for (const value of as({className: "live"})) {}', "ts"),
    ('switch (value) {case as({className: "live"}): break;}', "ts"),
    ('class View extends as({className: "live"}) {}', "ts"),
    ('export default satisfies({className: "live"});', "ts"),
    ('const previous = 0; previous\nas({className: "live"});', "ts"),
    ('const previous = 0; previous/*\n*/satisfies({className: "live"});', "ts"),
]

LINE_TERMINATORS = ["\n", "\r\n", "\u2028", "\u2029", "/*\n*/"]
DECLARATION_RUNTIME_CASES = [
    (f'{keyword}{gap}Props = {{className: "live"}};', "ts")
    for keyword in ("type", "interface")
    for gap in LINE_TERMINATORS
] + [(f'declare{gap}class Props {{className = "live";}}', "ts") for gap in LINE_TERMINATORS]
REGEX_RUNTIME_CASES = [
    (f'const text = `${{flag {operator} /}}/.test(value) ? use({{className: "live"}}) : ""}}`;', extension)
    for operator in ("&&", "||", "??")
    for extension in ("ts", "js")
]
REGEX_UNKNOWN_CASES = [
    (f'const text = `${{flag {operator} /}}/.test(value) ? use({{className: selected}}) : ""}}`;', extension)
    for operator in ("&&", "||", "??")
    for extension in ("ts", "js")
]
MODULE_RUNTIME_CASES = [
    (f"{statement}\nconst attrs: {{className: string}} = {{className: type.live}};", "ts")
    for statement in [
        "import type from './Card.module.css';",
        "import type, {value} from './Card.module.css';",
        "import type, {type Value} from './Card.module.css';",
        "import * as type from './Card.module.css';",
        "import {default as type} from './Card.module.css';",
        "import type\nfrom './Card.module.css';",
    ]
]


def _write(project, content, extension, global_css, module_css):
    (project / "global.css").write_text(global_css)
    (project / "Card.module.css").write_text(module_css)
    (project / "Other.module.css").write_text(".local {}\n")
    (project / f"consumer.{extension}").write_text(content + "\n")


def _remove(project):
    result = CliRunner().invoke(cli, ["-p", str(project), "remove", "-c", "orphaned_css"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(("content", "extension"), ERASED_CASES)
def test_erased_types_leave_unused_global_and_local_rules_removable(tmp_path, content, extension):
    _write(tmp_path, content, extension, ".legacy {}\n.unusedGlobal {}\n", ":global(.legacy) {}\n.local {}\n")

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert len(findings) == 5
    assert all(finding.removable for finding in findings)
    assert {finding.name for finding in findings} == {"legacy", "unusedGlobal", "local"}
    _remove(tmp_path)
    assert all((tmp_path / name).read_text() == "" for name in ("global.css", "Card.module.css", "Other.module.css"))


@pytest.mark.parametrize(("content", "extension"), RUNTIME_CASES)
def test_runtime_literals_survive_type_erasure_and_actual_remove(tmp_path, content, extension):
    _write(tmp_path, content, extension, ".legacy {}\n.live {}\n.unusedGlobal {}\n", ":global(.live) {}\n.local {}\n")

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert {finding.name for finding in findings} == {"legacy", "unusedGlobal", "local"}
    assert all(finding.removable for finding in findings)
    _remove(tmp_path)
    assert (tmp_path / "global.css").read_text() == ".live {}\n"
    assert (tmp_path / "Card.module.css").read_text() == ":global(.live) {}\n"
    assert (tmp_path / "Other.module.css").read_text() == ""


@pytest.mark.parametrize(("content", "extension"), CONTEXTUAL_RUNTIME_CASES)
def test_contextual_assertion_identifiers_keep_live_runtime_calls(tmp_path, content, extension):
    test_runtime_literals_survive_type_erasure_and_actual_remove(tmp_path, content, extension)


@pytest.mark.parametrize(("content", "extension"), DECLARATION_RUNTIME_CASES + REGEX_RUNTIME_CASES)
def test_lexical_boundaries_keep_explicit_live_runtime_classes(tmp_path, content, extension):
    test_runtime_literals_survive_type_erasure_and_actual_remove(tmp_path, content, extension)


@pytest.mark.parametrize(("content", "extension"), UNKNOWN_CASES)
def test_unknown_runtime_values_keep_global_css_conservative(tmp_path, content, extension):
    global_css = ".live {}\n.unusedGlobal {}\n"
    _write(tmp_path, content, extension, global_css, ":global(.live) {}\n.local {}\n")

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert all(not finding.removable for finding in findings if finding.file == "global.css")
    assert all(
        not finding.removable for finding in findings if finding.file == "Card.module.css" and finding.name == "live"
    )
    assert all(finding.removable for finding in findings if finding.name == "local")
    _remove(tmp_path)
    assert (tmp_path / "global.css").read_text() == global_css
    assert (tmp_path / "Card.module.css").read_text() == ":global(.live) {}\n"
    assert (tmp_path / "Other.module.css").read_text() == ""


@pytest.mark.parametrize(("content", "extension"), REGEX_UNKNOWN_CASES)
def test_template_regex_boundaries_keep_unknown_runtime_classes_conservative(tmp_path, content, extension):
    test_unknown_runtime_values_keep_global_css_conservative(tmp_path, content, extension)


@pytest.mark.parametrize(("content", "extension"), MODULE_RUNTIME_CASES)
def test_value_import_binding_named_type_preserves_css_module_scope(tmp_path, content, extension):
    for name in ("Card.module.css", "Other.module.css"):
        (tmp_path / name).write_text(".live {}\n.unusedLocal {}\n")
    (tmp_path / "global.css").write_text(".unusedGlobal {}\n")
    (tmp_path / ("consumer." + extension)).write_text(content)

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert all(finding.removable for finding in findings)
    assert [(finding.name, finding.removable) for finding in findings if finding.file == "Card.module.css"] == [
        ("unusedLocal", True)
    ]
    _remove(tmp_path)
    assert (tmp_path / "Card.module.css").read_text() == ".live {}\n"
    assert (tmp_path / "Other.module.css").read_text() == ""
    assert (tmp_path / "global.css").read_text() == ""


@pytest.mark.parametrize("accessor", ["styles.live", "styles[variant]"])
def test_type_annotations_preserve_value_import_module_scope(tmp_path, accessor):
    for name in ("Card.module.css", "Other.module.css"):
        (tmp_path / name).write_text(".live {}\n.unusedLocal {}\n")
    (tmp_path / "global.css").write_text(".unusedGlobal {}\n")
    (tmp_path / "consumer.ts").write_text(
        f"import styles from './Card.module.css';\nconst attrs: {{className: string}} = {{className: {accessor}}};\n"
    )

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert all(finding.removable for finding in findings if finding.file != "Card.module.css")
    own = [finding for finding in findings if finding.file == "Card.module.css"]
    assert [(finding.name, finding.removable) for finding in own] == (
        [("unusedLocal", True)] if accessor == "styles.live" else [("live", False), ("unusedLocal", False)]
    )
    _remove(tmp_path)
    assert (tmp_path / "Card.module.css").read_text() == (
        ".live {}\n" if accessor == "styles.live" else ".live {}\n.unusedLocal {}\n"
    )
    assert (tmp_path / "Other.module.css").read_text() == ""
    assert (tmp_path / "global.css").read_text() == ""


@pytest.mark.parametrize(
    "source",
    [
        'interface Props {className: string;\nconst attrs = {className: "live"};',
        'declare const props: {className: string;\nconst attrs = {className: "live"};',
        'type Props = Array<{className: string};\nconst attrs = {className: "live"};',
    ],
)
def test_unproved_type_boundaries_do_not_erase_runtime_uses(tmp_path, source):
    global_css = ".live {}\n.unusedGlobal {}\n"
    _write(tmp_path, source, "ts", global_css, ":global(.live) {}\n.local {}\n")

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert all(not finding.removable for finding in findings if finding.file == "global.css")
    _remove(tmp_path)
    assert (tmp_path / "global.css").read_text() == global_css
    assert (tmp_path / "Other.module.css").read_text() == ""


def test_css_runtime_view_preserves_type_export_and_import_analysis(tmp_path):
    (tmp_path / "types.ts").write_text("export interface Props {className: string}\nexport type Unused = string;\n")
    (tmp_path / "consumer.ts").write_text('import type {Props} from "./types";\nconst next = 1;\n')
    (tmp_path / "global.css").write_text(".unusedGlobal {}\n")

    result = DeadCodeScanner(tmp_path).scan()

    assert [(finding.name, finding.removable) for finding in result.orphaned_css] == [("unusedGlobal", True)]
    assert [(finding.name, finding.removable) for finding in result.unused_exports] == [("Unused", True)]
