"""File include patterns must not prune unmatched ancestor directories."""

import json

import pytest
from click.testing import CliRunner

from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner


@pytest.fixture
def nested_project(tmp_path):
    nested = tmp_path / "src" / "components"
    nested.mkdir(parents=True)
    (nested / "Unused.tsx").write_text("export const unused = 1;\n")
    (nested / "ignored.tsx").write_text("export const ignored = 2;\n")
    (tmp_path / "outside.ts").write_text("export const outside = 3;\n")
    return tmp_path


@pytest.mark.parametrize("pattern", ["src/components/*.tsx", "**/*.tsx", "src/components/Unused.tsx"])
def test_nested_file_whitelist_reaches_matching_files(nested_project, pattern):
    result = DeadCodeScanner(
        nested_project, include_patterns=[pattern], ignore_patterns=["**/ignored.tsx"]
    ).scan()

    assert result.files_scanned == 1
    assert [(finding.file, finding.name) for finding in result.findings] == [
        ("src/components/Unused.tsx", "unused")
    ]


@pytest.mark.parametrize("command", [["scan", "--format=json"], ["stats"], ["remove", "--dry-run"]])
def test_nested_whitelist_applies_to_all_cli_commands(nested_project, command):
    source = nested_project / "src" / "components" / "Unused.tsx"
    original = source.read_bytes()

    result = CliRunner().invoke(
        cli,
        ["-p", str(nested_project), "--include", "src/components/Unused.tsx", *command],
    )

    assert result.exit_code == 0
    if command[0] == "scan":
        assert json.loads(result.output)["files_scanned"] == 1
    elif command[0] == "stats":
        assert "Files scanned: 1" in result.output
    else:
        assert "WOULD REMOVE" in result.output
        assert "outside.ts" not in result.output
    assert source.read_bytes() == original
