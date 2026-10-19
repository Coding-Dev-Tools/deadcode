"""Whole-line removal cannot erase an unrelated non-class CSS construct."""

import time

import pytest
from click.testing import CliRunner

from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner


@pytest.mark.parametrize("filename", ["global.css", "global.scss", "Card.module.css"])
@pytest.mark.parametrize(
    "rule",
    [
        r".unused\:name {} body { color: red; }",
        r"body { color: red; } .unused\.name {}",
        r".unused\3a name {} #app { color: red; }",
        r".unused\:name {} :root { --color: red; }",
        r"@media screen { .unused\:name {} body { color: red; } }",
        r".unused\:name {} @font-face { font-family: x; src: url(x.woff); }",
        ":root { --color: red; } .unused {}",
        ".unused {} body { color: red; }",
        "/* leading\n*/ .unused\\:name {}",
        ".unused\\:name {} /* trailing\n*/",
        "/* leading\n/* nested-looking */ .unused\\:name {}",
        r".unused\:name, body { color: red; }",
        r"body, .unused\:name { color: red; }",
        r".unused\:name, :root { --color: red; }",
        r".unused\:name, #app { color: red; }",
        ".unused, body { color: red; }",
        ".unused:hover { color: red; }",
    ],
)
def test_shared_lines_are_visible_but_never_removed(tmp_path, monkeypatch, filename, rule):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    css = tmp_path / filename
    original = rule + "\n.removeOnly {}\n"
    css.write_text(original, encoding="utf-8")

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    assert findings
    assert {f.name for f in findings if f.removable} == {"removeOnly"}
    assert any(not f.removable for f in findings)
    dry_run = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css", "--dry-run"])
    assert dry_run.exit_code == 0, dry_run.output
    assert css.read_text(encoding="utf-8") == original
    removed = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])
    assert removed.exit_code == 0, removed.output
    assert css.read_text(encoding="utf-8") == rule + "\n"


@pytest.mark.parametrize("filename", ["global.css", "global.scss", "Card.module.css"])
@pytest.mark.parametrize(
    "rule",
    [
        r".unused\:name {}",
        r"  .unused\.name { content: '}'; }  ",
        r"/* header */ .unused\:name { /* body */ } /* footer */",
        r".unused\3a name { content: 'body {}'; }",
        r".unused\{name { color: red; }",
        ".first, .second { color: red; }",
    ],
)
def test_standalone_complete_rules_still_remove(tmp_path, monkeypatch, filename, rule):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    css = tmp_path / filename
    css.write_text(rule + "\n", encoding="utf-8")
    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    assert findings and all(f.removable for f in findings)
    removed = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])
    assert removed.exit_code == 0, removed.output
    assert css.read_text(encoding="utf-8") == ""
