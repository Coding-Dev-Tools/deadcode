"""A start-line finding must never delete just part of a CSS module rule."""

import time

import pytest
from click.testing import CliRunner

from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner

MULTILINE_RULES = [
    (".unused\n{ color: red; }\n", {"unused"}),
    (".unused\n{\n color: red;\n}\n", {"unused"}),
    (".unused {\n color: red;\n}\n", {"unused"}),
    (".first,\n.second { color: red; }\n", {"first", "second"}),
    (".first, /* selector comment */\n.second\n{ color: red; }\n", {"first", "second"}),
    ("@media (min-width: 1px) {\n.unused\n{ color: red; }\n}\n", {"unused"}),
    (":local(.unused)\n{ color: red; }\n", {"unused"}),
    (".unused\n{ content: '{not a rule}'; }\n", {"unused"}),
    (":global(.unused)\n{ color: red; }\n", {"unused"}),
]


@pytest.mark.parametrize(("rule", "names"), MULTILINE_RULES)
def test_multiline_module_rules_remain_visible_and_byte_preserved(tmp_path, monkeypatch, rule, names):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    css = tmp_path / "Card.module.css"
    original = rule + ".standalone {}\n"
    css.write_text(original, encoding="utf-8")
    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    preview = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css", "--dry-run"])
    after_preview = css.read_text(encoding="utf-8")
    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])
    remaining = css.read_text(encoding="utf-8")

    assert preview.exit_code == 0, preview.output
    assert after_preview == original
    assert result.exit_code == 0, result.output
    assert {f.name for f in findings} == names | {"standalone"}
    assert {f.name for f in findings if f.removable} == {"standalone"}, (findings, remaining)
    assert remaining == rule


@pytest.mark.parametrize(
    "rule",
    [".live,\n.unused { color: red; }\n", ".live,\n.unused\n{ color: red; }\n"],
)
def test_used_shared_multiline_rule_and_unrelated_one_liner_keep_their_bounds(tmp_path, monkeypatch, rule):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    css = tmp_path / "Card.module.css"
    css.write_text(rule + ".standalone {}\n", encoding="utf-8")
    (tmp_path / "consumer.ts").write_text(
        "import styles from './Card.module.css'; const selected = styles.live;", encoding="utf-8"
    )
    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])

    assert result.exit_code == 0, result.output
    assert {f.name for f in findings} == {"unused", "standalone"}
    assert {f.name for f in findings if f.removable} == {"standalone"}
    assert css.read_text(encoding="utf-8") == rule


@pytest.mark.parametrize(
    "rule", [".unused { color: red; }\n", ".unused { content: '}'; }\n", ".unused { /* { } */ color: red; }\n"]
)
def test_complete_one_line_module_rules_still_remove(tmp_path, monkeypatch, rule):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    css = tmp_path / "Card.module.css"
    css.write_text(rule, encoding="utf-8")
    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])

    assert result.exit_code == 0, result.output
    assert {f.name for f in findings if f.removable} == {"unused"}
    assert css.read_text(encoding="utf-8") == ""
