"""Runtime class writes and JSX delimiters must never hide live CSS evidence."""

import time

import pytest
from click.testing import CliRunner

from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner


@pytest.fixture(autouse=True)
def no_countdown(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)


ASSIGNMENT_RUNTIME_CASES = [
    (f'{target} = "live";', extension)
    for target in ("element.className", "element.class", "className", "element['className']", 'element["class"]')
    for extension in ("ts", "js", "tsx", "jsx")
] + [
    ('element.className = "live" as string;', "ts"),
    ('element.className = ("live" satisfies string);', "ts"),
    ('const apply = () => (element.className = "live");', "js"),
    ('function apply() { return element.className = "live"; }', "ts"),
    ('element.className /* separator */ = "live";', "js"),
    ('element.className /* separator */ = /* value */ "live";', "ts"),
    ('element[/* key */ "className"] /* separator */ = "live";', "ts"),
    ('element["class\\u004eame"] = "live";', "js"),
    ('element[`className`] = "live";', "js"),
    ('const text = `${element.className = "live"}`;', "ts"),
    ('class Props {className /* separator */ = "live";}', "js"),
    ('const attrs = {className /* separator */ : "live"};', "ts"),
    ('const attrs = {"className" /* separator */ : "live"};', "js"),
]
ASSIGNMENT_UNKNOWN_CASES = [
    (f"{target} {operator} {value};", extension)
    for target in ("element.className", "element['className']")
    for operator, value in (
        ("=", "selected"),
        ("=", '"prefix" + selected'),
        ("+=", '"live"'),
        ("||=", '"live"'),
        ("&&=", '"live"'),
        ("??=", '"live"'),
    )
    for extension in ("ts", "js")
] + [
    ("element.className /* separator */ = selected;", "js"),
    ('element["className"] /* separator */ = selected;', "ts"),
    ("const text = `${element.className = selected}`;", "ts"),
]
JSX_MODULE_CASES = [
    ("import styles from './Card.module.css';\n" + expression, extension)
    for expression in (
        "const view = <><div></div><div className={styles.live} /></>;",
        'const view = <><section></section><UI.Card className={styles["live"]}></UI.Card></>;',
        "const view = <><svg:path></svg:path><div className={styles.live} /></>;",
        "const view = <><Élément></Élément><div className={styles.live} /></>;",
        "const view = <><><div /></><div className={styles.live} /></>;",
        "const view = <><div />{null}<div className={styles.live} /></>;",
        "const view = <><Button<string> /><div className={styles.live} /></>;",
    )
    for extension in ("tsx", "jsx")
    if not (extension == "jsx" and "<string>" in expression)
]
JSX_MODULE_UNKNOWN_CASES = [
    (
        f"import styles from './Card.module.css';\nconst view = <><div></div><div className={{styles[{accessor}]}} /></>;",
        extension,
    )
    for accessor in ("selected", '"prefix" + selected')
    for extension in ("tsx", "jsx")
]
JSX_TAIL_RUNTIME_CASES = [
    ('const view = <><div></div><div />{use({className: "live"})}</>;', extension) for extension in ("tsx", "jsx")
] + [('const view = <><div></div><div /></>; element.className = "live";', extension) for extension in ("tsx", "jsx")]
ASSIGNMENT_MODULE_CASES = [
    (f"import styles from './Card.module.css';\nelement.className = {accessor};", extension)
    for accessor in ("styles.live", 'styles["live"]')
    for extension in ("ts", "js")
]


def _write(project, content, extension):
    (project / ("consumer." + extension)).write_text(content + "\n")
    (project / "global.css").write_text(".live {}\n.unusedGlobal {}\n")
    (project / "Card.module.css").write_text(":global(.live) {}\n.live {}\n.unusedLocal {}\n")
    (project / "Other.module.css").write_text(".live {}\n.unusedLocal {}\n")


def _remove(project):
    result = CliRunner().invoke(cli, ["-p", str(project), "remove", "-c", "orphaned_css"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(("content", "extension"), ASSIGNMENT_RUNTIME_CASES + JSX_TAIL_RUNTIME_CASES)
def test_runtime_class_assignments_and_jsx_tails_keep_live_global_rules(tmp_path, content, extension):
    _write(tmp_path, content, extension)

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert all(finding.removable for finding in findings)
    assert not any(finding.file == "global.css" and finding.name == "live" for finding in findings)
    _remove(tmp_path)
    assert (tmp_path / "global.css").read_text() == ".live {}\n"
    assert (tmp_path / "Card.module.css").read_text() == ":global(.live) {}\n"
    assert (tmp_path / "Other.module.css").read_text() == ""


@pytest.mark.parametrize(("content", "extension"), ASSIGNMENT_UNKNOWN_CASES)
def test_unknown_runtime_class_assignments_keep_only_global_css_uncertain(tmp_path, content, extension):
    _write(tmp_path, content, extension)

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert all(not finding.removable for finding in findings if finding.file == "global.css")
    assert all(finding.removable for finding in findings if finding.name == "unusedLocal")
    _remove(tmp_path)
    assert (tmp_path / "global.css").read_text() == ".live {}\n.unusedGlobal {}\n"
    assert (tmp_path / "Card.module.css").read_text() == ":global(.live) {}\n"
    assert (tmp_path / "Other.module.css").read_text() == ""


@pytest.mark.parametrize(("content", "extension"), JSX_MODULE_CASES + ASSIGNMENT_MODULE_CASES)
def test_jsx_closing_slashes_and_class_writes_keep_css_module_scope(tmp_path, content, extension):
    _write(tmp_path, content, extension)

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert all(finding.removable for finding in findings)
    assert not any(
        finding.file == "Card.module.css" and not finding.name.startswith("unused")
        for finding in findings
        if finding.line == 2
    )
    _remove(tmp_path)
    assert (tmp_path / "global.css").read_text() == ""
    assert (tmp_path / "Card.module.css").read_text() == ".live {}\n"
    assert (tmp_path / "Other.module.css").read_text() == ""


@pytest.mark.parametrize(("content", "extension"), JSX_MODULE_UNKNOWN_CASES)
def test_jsx_closing_slash_keeps_dynamic_css_module_access_uncertain_only_in_own_stylesheet(
    tmp_path, content, extension
):
    _write(tmp_path, content, extension)

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert all(finding.removable for finding in findings if finding.file != "Card.module.css")
    assert all(not finding.removable for finding in findings if finding.file == "Card.module.css" and finding.line > 1)
    _remove(tmp_path)
    assert (tmp_path / "global.css").read_text() == ""
    assert (tmp_path / "Card.module.css").read_text() == ".live {}\n.unusedLocal {}\n"
    assert (tmp_path / "Other.module.css").read_text() == ""


NONRUNTIME_CASES = [
    '// element.className = "live";\nconst unused = 1;',
    "const text = 'element.className = \"live\"';",
    'const text = `element.className = "live"`;',
    'const pattern = /element.className = "live"/;',
    'const pattern = />{className:"live"}/;',
    'const equal = element.className == "live";',
    'const equal = element.className === "live";',
    'const identity = className => "live";',
    'type Props = {className: "live"}; interface View {className: string}',
]


@pytest.mark.parametrize("content", NONRUNTIME_CASES)
def test_nonruntime_text_comparisons_and_type_properties_do_not_invent_class_assignments(tmp_path, content):
    _write(tmp_path, content, "ts")
    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    assert all(finding.removable for finding in findings)
    _remove(tmp_path)
    assert all((tmp_path / name).read_text() == "" for name in ("global.css", "Card.module.css", "Other.module.css"))
