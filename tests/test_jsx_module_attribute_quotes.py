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
