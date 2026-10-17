"""Protect live styles and the project boundary during a dead-code scan."""

import pytest

from deadcode.scanner import DeadCodeScanner


@pytest.mark.parametrize("extension", ["ts", "js", "tsx", "jsx"])
@pytest.mark.parametrize(
    ("binding", "accessor", "class_name"),
    [
        ("styles", "._active", "_active"),
        ("styles", "[ 'card-hover' ]", "card-hover"),
        ("$styles", ".card", "card"),
    ],
)
def test_css_module_accessors_preserve_live_classes(tmp_path, extension, binding, accessor, class_name):
    (tmp_path / "Card.module.css").write_text(f".{class_name} {{ color: red; }}\n.unused {{}}\n")
    (tmp_path / f"consumer.{extension}").write_text(
        f"import {binding} from './Card.module.css';\nconst selected = {binding}{accessor};\n"
    )

    result = DeadCodeScanner(tmp_path).scan()

    assert class_name not in {finding.name for finding in result.orphaned_css}
    assert "unused" in {finding.name for finding in result.orphaned_css}


def test_scanner_does_not_read_source_symlink_outside_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "external.ts"
    external.write_text("export const externalLiveValue = 1;\n")
    (project / "linked.ts").symlink_to(external)

    result = DeadCodeScanner(project).scan()

    assert result.files_scanned == 0
    assert result.findings == []
    assert external.read_text() == "export const externalLiveValue = 1;\n"


def test_scanner_still_reads_internal_source_symlink(tmp_path):
    target = tmp_path / "target.ts"
    target.write_text("export const internalValue = 1;\n")
    (tmp_path / "linked.ts").symlink_to(target)

    result = DeadCodeScanner(tmp_path).scan()

    assert result.files_scanned == 2
