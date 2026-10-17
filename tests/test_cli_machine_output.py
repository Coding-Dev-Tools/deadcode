"""Machine output preserves source paths without terminal presentation rules."""

import json

import pytest
from click.testing import CliRunner

from deadcode.cli import cli


@pytest.mark.parametrize("option", ["--format=json", "--json-output"])
def test_json_preserves_long_paths_and_markup(tmp_path, option):
    name = "[green]" + "x" * 100 + "[red].ts"
    (tmp_path / name).write_text("export const unused = 1;\n")

    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "scan", option])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["files_scanned"] == 1
    assert data["findings"][0]["file"] == name
    assert "never imported outside its defining file" in data["findings"][0]["detail"]


def test_github_annotations_preserve_long_paths_and_escape_properties(tmp_path):
    name = "[green]" + "x" * 100 + "%value,other.ts"
    (tmp_path / name).write_text("export const unused = 1;\n")

    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "scan", "--format=github"])

    assert result.exit_code == 0
    annotations = [line for line in result.output.splitlines() if line.startswith("::error")]
    assert len(annotations) == 1
    expected_path = name.replace("%", "%25").replace(",", "%2C")
    assert annotations[0].startswith(f"::error file={expected_path},line=1::unused_export: unused")


def test_github_annotation_path_cannot_inject_workflow_commands(tmp_path):
    import os

    if os.name == "nt":
        pytest.skip("Windows does not permit newline characters in file names")
    name = "first.ts\n::error file=other.ts::injected.ts"
    (tmp_path / name).write_text("export const unused = 1;\n")

    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "scan", "--format=github"])

    assert result.exit_code == 0
    annotations = [line for line in result.output.splitlines() if line.startswith("::error")]
    assert len(annotations) == 1
    assert "first.ts%0A%3A%3Aerror file=other.ts%3A%3Ainjected.ts" in annotations[0]
