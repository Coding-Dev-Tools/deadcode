"""Raw JSX quotes must not hide live CSS-module accesses from removal."""

import time

import pytest
from click.testing import CliRunner

from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner


@pytest.mark.parametrize("extension", ["tsx", "jsx"])
@pytest.mark.parametrize(
    "view",
    [
        r'<div data-path="C:\" className={styles.card} />',
        r"<div data-path='C:\' className={styles.card} />",
        r'<><span data-path="C:\" /><div className={styles.card} /></>',
        r'<div data-path="C:\" title="Card" className={styles.card} />',
        '<div data-path="C:\\\nfolder" className={styles.card} />',
        r"""<div data-path="C:\" title={'escaped \' quote'} className={styles.card} />""",
        r"""<div title={'C:\\'} data-path="C:\" className={styles.card} />""",
    ],
)
def test_raw_jsx_attribute_quotes_preserve_live_module_rules(tmp_path, monkeypatch, extension, view):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    stylesheet = tmp_path / "Card.module.css"
    stylesheet.write_text(".card {}\n.unused {}\n", encoding="utf-8")
    (tmp_path / f"consumer.{extension}").write_text(
        f"import styles from './Card.module.css';\nexport const View = () => {view};\n", encoding="utf-8"
    )

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    assert {finding.name for finding in findings} == {"unused"}
    assert all(finding.removable for finding in findings)

    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])
    assert result.exit_code == 0, result.output
    assert stylesheet.read_text(encoding="utf-8") == ".card {}\n"


@pytest.mark.parametrize("extension", ["tsx", "jsx"])
def test_quoted_jsx_and_javascript_do_not_invent_module_uses(tmp_path, extension):
    (tmp_path / "Card.module.css").write_text(".card {}\n", encoding="utf-8")
    (tmp_path / f"consumer.{extension}").write_text(
        "import styles from './Card.module.css';\n"
        r"""const text = 'escaped \' quote styles.card <div data-path="C:\\">';"""
        "\n// styles.card\n"
        r"""export const View = () => <div data-path="C:\" title="styles.card" />;""",
        encoding="utf-8",
    )
    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    assert {finding.name for finding in findings} == {"card"}
    assert all(finding.removable for finding in findings)


@pytest.mark.parametrize("extension", ["ts", "tsx"])
@pytest.mark.parametrize(
    "declaration",
    [
        r"""function view<T = "escaped \" quote">() { return styles.card; }""",
        r"""const view = <T = "escaped \" quote",>() => styles.card;""",
        r"""const view = <T extends "escaped \" quote",>() => styles.card;""",
        r"""const view = <T extends U = "escaped \" quote",>() => styles.card;""",
    ],
)
def test_type_parameter_heads_keep_javascript_string_escaping(tmp_path, extension, declaration):
    (tmp_path / "Card.module.css").write_text(".card {}\n.unused {}\n", encoding="utf-8")
    (tmp_path / f"consumer.{extension}").write_text(
        f"import styles from './Card.module.css';\n{declaration}\n", encoding="utf-8"
    )
    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    assert {finding.name for finding in findings} == {"unused"}
    assert all(finding.removable for finding in findings)


@pytest.mark.parametrize("extension", ["tsx", "jsx"])
@pytest.mark.parametrize(
    "view",
    [
        "<p>It's <span className={styles.card} /></p>",
        '<p>He said "hello <span className={styles.card} /></p>',
        "<p>https://example.test <span className={styles.card} /></p>",
        "<p>/* raw child prose <span className={styles.card} /></p>",
        "<p>`raw child prose <span className={styles.card} /></p>",
        "<>It's {flag ? <span className={styles.card} /> : null}</>",
        '<p>It\'s {"quoted \\" value"}<span className={styles.card} /></p>',
        "<p>It's a child</p>; element.className = styles.card",
    ],
)
def test_jsx_child_text_preserves_live_rules_and_following_code(tmp_path, monkeypatch, extension, view):
    test_raw_jsx_attribute_quotes_preserve_live_module_rules(tmp_path, monkeypatch, extension, view)


@pytest.mark.parametrize("extension", ["tsx", "jsx"])
def test_jsx_child_prose_does_not_invent_module_access(tmp_path, extension):
    (tmp_path / "Card.module.css").write_text(".card {}\n", encoding="utf-8")
    (tmp_path / f"consumer.{extension}").write_text(
        "import styles from './Card.module.css';\nconst View=()=> <p>It's styles.card // prose /* text */ `text`</p>;\n",
        encoding="utf-8",
    )
    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    assert len(findings) == 1 and findings[0].name == "card" and findings[0].removable


def test_typescript_assertion_with_apparent_closing_tag_keeps_live_access(tmp_path):
    (tmp_path / "Card.module.css").write_text(".card {}\n.unused {}\n", encoding="utf-8")
    (tmp_path / "consumer.ts").write_text(
        "import styles from './Card.module.css';\nconst selected=<T>render(\"</T>\"); const live=styles.card;\n",
        encoding="utf-8",
    )
    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    assert {finding.name for finding in findings} == {"unused"}


@pytest.mark.parametrize("tag", ["Élément", "Button<string>"])
def test_generic_and_unicode_jsx_keep_module_and_literal_classes(tmp_path, tag):
    (tmp_path / "Card.module.css").write_text(".card {}\n.unused {}\n", encoding="utf-8")
    (tmp_path / "global.css").write_text(".literal {}\n.unusedGlobal {}\n", encoding="utf-8")
    closing = tag.split("<")[0]
    (tmp_path / "consumer.tsx").write_text(
        "import styles from './Card.module.css';\n"
        f'<{tag} className="literal">It\'s <span className={{styles.card}} /></{closing}>;\n',
        encoding="utf-8",
    )
    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    assert {finding.name for finding in findings} == {"unused", "unusedGlobal"}
    assert all(finding.removable for finding in findings)


@pytest.mark.parametrize("extension", ["tsx", "jsx"])
@pytest.mark.parametrize("tag", ["_Button", "$Button", "Button$", "Élément"])
def test_all_jsx_identifier_forms_keep_raw_attribute_grammar(tmp_path, monkeypatch, extension, tag):
    view = rf'<{tag} data-path="C:\" className={{styles.card}} />'
    test_raw_jsx_attribute_quotes_preserve_live_module_rules(tmp_path, monkeypatch, extension, view)


@pytest.mark.parametrize("extension", ["ts", "tsx"])
@pytest.mark.parametrize(
    "expression,live",
    [("a < styles.card > (b)", False), ("(a < styles.card) > b", True), ("a < styles.card > b", True)],
)
def test_angle_expression_usage_agrees_with_typescript_emission(tmp_path, extension, expression, live):
    # TypeScript 5.9.3 emits a(b) for the first expression, and preserves the
    # two explicitly relational forms. Whitespace does not change that grammar.
    (tmp_path / "Card.module.css").write_text(".card {}\n", encoding="utf-8")
    (tmp_path / f"consumer.{extension}").write_text(
        f"import styles from './Card.module.css';\nconst value = {expression};\n", encoding="utf-8"
    )
    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    assert bool(findings) is not live
    assert all(finding.name == "card" and finding.removable for finding in findings)
