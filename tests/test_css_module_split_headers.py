"""A line-only remover must preserve complete multi-line selector headers."""

import time

import pytest
from click.testing import CliRunner

from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner


@pytest.mark.parametrize(
    "rule,names",
    [
        (".unused\n{ color: red; }\n", {"unused"}),
        (".unused\n{\n  color: red;\n}\n", {"unused"}),
        (".first,\n.second { color: red; }\n", {"first", "second"}),
        (".first\n, .second { color: red; }\n", {"first", "second"}),
        (".first /* note\ncontinued */ .second { color: red; }\n", {"first", "second"}),
        ("@media (min-width: 10px) {\n.unused\n{ color: red; }\n}\n", {"unused"}),
    ],
)
def test_split_module_headers_are_visible_but_never_partially_removed(tmp_path, monkeypatch, rule, names):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    stylesheet = tmp_path / "Card.module.css"
    stylesheet.write_bytes((rule + ".single { color: blue; }\n").encode("utf-8"))
    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    protected = [finding for finding in findings if finding.name in names]
    assert {finding.name for finding in protected} == names
    assert all(not finding.removable and "multiple lines" in finding.detail for finding in protected)
    assert next(finding for finding in findings if finding.name == "single").removable

    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])
    assert result.exit_code == 0, result.output
    assert stylesheet.read_text(encoding="utf-8") == rule


def test_leading_blank_lines_do_not_make_a_complete_header_multiline(tmp_path):
    (tmp_path / "Card.module.css").write_bytes(b"\n/* introductory comment */\n\n.single {}\n")
    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    assert len(findings) == 1 and findings[0].name == "single" and findings[0].removable
