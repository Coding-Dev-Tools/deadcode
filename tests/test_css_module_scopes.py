"""CSS-module uses belong to one stylesheet, while literal classes stay global."""

import pytest
from click.testing import CliRunner

from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner


def orphaned(project):
    return {(finding.file, finding.name) for finding in DeadCodeScanner(project).scan().orphaned_css}


@pytest.mark.parametrize("extension", ["ts", "js", "tsx", "jsx"])
@pytest.mark.parametrize(
    ("binding", "accessor", "class_name"),
    [
        ("styles", ".shared", "shared"),
        ("styles", "[ 'card-hover' ]", "card-hover"),
        ("$styles", "._active", "_active"),
    ],
)
def test_module_accessor_only_protects_its_imported_stylesheet(tmp_path, extension, binding, accessor, class_name):
    for name in ["A.module.css", "B.module.css", "global.css"]:
        (tmp_path / name).write_text(f".{class_name} {{ color: red; }}\n")
    (tmp_path / f"consumer.{extension}").write_text(
        f"import {binding} from './B.module.css';\nconst selected = {binding}{accessor};\n"
    )

    assert orphaned(tmp_path) == {("A.module.css", class_name), ("global.css", class_name)}


def test_nested_imports_distinguish_stylesheets_with_the_same_filename(tmp_path):
    for directory in ["components", "first", "second"]:
        (tmp_path / directory).mkdir()
    for directory in ["first", "second"]:
        (tmp_path / directory / "Card.module.css").write_text(".shared {}\n")
    (tmp_path / "components" / "consumer.ts").write_text(
        "import styles from '../second/./Card.module.css';\nconst selected = styles.shared;\n"
    )

    assert orphaned(tmp_path) == {("first/Card.module.css", "shared")}


def test_bindings_are_local_to_each_importing_file(tmp_path):
    for name in ["A.module.css", "B.module.css"]:
        (tmp_path / name).write_text(".shared {}\n.other {}\n")
    (tmp_path / "first.ts").write_text("import styles from './A.module.css';\nconst selected = styles.shared;\n")
    (tmp_path / "second.ts").write_text("import styles from './B.module.css';\nconst selected = styles.other;\n")

    assert orphaned(tmp_path) == {("A.module.css", "other"), ("B.module.css", "shared")}


def test_literal_classes_protect_global_stylesheets_without_protecting_module_classes(tmp_path):
    for name in ["first.css", "second.scss", "Card.module.css"]:
        (tmp_path / name).write_text(".shared {}\n")
    (tmp_path / "consumer.tsx").write_text('export const View = () => <div className="shared" />;\n')

    assert orphaned(tmp_path) == {("Card.module.css", "shared")}


def test_global_literal_and_module_accessor_uses_coexist(tmp_path):
    for name in ["A.module.css", "B.module.css", "global.css"]:
        (tmp_path / name).write_text(".shared {}\n.literal {}\n")
    (tmp_path / "consumer.tsx").write_text(
        "import styles from './B.module.css';\n"
        'export const View = () => <div className="literal"><span className={styles.shared} /></div>;\n'
    )

    assert orphaned(tmp_path) == {
        ("A.module.css", "shared"),
        ("A.module.css", "literal"),
        ("B.module.css", "literal"),
        ("global.css", "shared"),
    }


@pytest.mark.parametrize("specifier", ["./missing.module.css", "package/Other.module.css"])
def test_unresolved_imports_do_not_hide_unrelated_classes(tmp_path, specifier):
    (tmp_path / "A.module.css").write_text(".shared {}\n")
    (tmp_path / "global.css").write_text(".shared {}\n")
    (tmp_path / "consumer.ts").write_text(f"import styles from '{specifier}';\nconst selected = styles.shared;\n")

    assert orphaned(tmp_path) == {("A.module.css", "shared"), ("global.css", "shared")}


def test_internal_stylesheet_symlink_keeps_live_target_and_alias_classes(tmp_path):
    (tmp_path / "Actual.module.css").write_text(".shared {}\n.unused {}\n")
    (tmp_path / "Linked.module.css").symlink_to(tmp_path / "Actual.module.css")
    (tmp_path / "consumer.ts").write_text(
        "import styles from './Linked.module.css';\nconst selected = styles.shared;\n"
    )

    assert orphaned(tmp_path) == {("Actual.module.css", "unused"), ("Linked.module.css", "unused")}


def test_remove_preserves_live_module_and_only_removes_unused_definitions(tmp_path):
    for name in ["A.module.css", "B.module.css", "global.css"]:
        (tmp_path / name).write_text(".shared { color: red; }\n")
    (tmp_path / "consumer.ts").write_text("import styles from './B.module.css';\nconst selected = styles.shared;\n")

    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"], input="y\n")

    assert result.exit_code == 0, result.output
    assert (tmp_path / "B.module.css").read_text() == ".shared { color: red; }\n"
    assert ".shared" not in (tmp_path / "A.module.css").read_text()
    assert ".shared" not in (tmp_path / "global.css").read_text()


def test_unresolved_alias_keeps_module_findings_visible_and_nonremovable(tmp_path):
    for name in ["A.module.css", "B.module.css", "global.css"]:
        (tmp_path / name).write_text(".shared {}\n")
    (tmp_path / "consumer.ts").write_text("import styles from '@/Card.module.css';\nconst selected = styles.shared;\n")

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert {(finding.file, finding.name) for finding in findings} == {
        ("A.module.css", "shared"),
        ("B.module.css", "shared"),
        ("global.css", "shared"),
    }
    assert {finding.file for finding in findings if finding.removable} == {"global.css"}
    assert all("unresolved stylesheet import" in finding.detail for finding in findings if not finding.removable)


def test_remove_retains_uncertain_module_classes_and_removes_unreferenced_global_class(tmp_path):
    for name in ["A.module.css", "B.module.css", "global.css"]:
        (tmp_path / name).write_text(".shared { color: red; }\n")
    (tmp_path / "consumer.ts").write_text("import styles from '@/Card.module.css';\nconst selected = styles.shared;\n")

    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"], input="y\n")

    assert result.exit_code == 0, result.output
    for name in ["A.module.css", "B.module.css"]:
        assert (tmp_path / name).read_text() == ".shared { color: red; }\n"
    assert ".shared" not in (tmp_path / "global.css").read_text()
