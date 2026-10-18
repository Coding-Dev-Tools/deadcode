"""Raw Unicode import bindings keep their complete JavaScript identity."""

import time

import pytest
from click.testing import CliRunner

from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner


@pytest.mark.parametrize(
    ("statement", "binding"),
    [
        ("import { token, default as café, } from './x.module.css';", "café"),
        ("import café from './x.module.css';", "café"),
        ("import * as café from './x.module.css';", "café"),
        ("import { default as na‍me‌x, token } from './x.module.css';", "na‍me‌x"),
        ("import sty‌les from './x.module.css';", "sty‌les"),
        ("import { default as قَلَم, token } from './x.module.css';", "قَلَم"),
    ],
)
def test_import_alias_continuations_keep_runtime_css_identity(tmp_path, monkeypatch, statement, binding):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    css = tmp_path / "x.module.css"
    css.write_text(".live {}\n.dead {}\n", encoding="utf-8")
    (tmp_path / "consumer.tsx").write_text(statement + f"\nvoid {binding}.live;", encoding="utf-8")

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    preview = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css", "--dry-run"])
    assert preview.exit_code == 0, preview.output
    assert css.read_text(encoding="utf-8") == ".live {}\n.dead {}\n"
    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])

    assert result.exit_code == 0, result.output
    assert [(f.name, f.removable) for f in findings] == [("dead", True)]
    assert css.read_text(encoding="utf-8") == ".live {}\n"


@pytest.mark.parametrize(
    "source",
    [
        "import type { default as café, } from './x.module.css'; type Name = typeof café.live;",
        "import styles from './x.module.css'; const caféstyles = {live: 'other'}; void caféstyles.live;",
    ],
)
def test_unicode_alias_lookalikes_and_type_only_imports_do_not_create_runtime_use(tmp_path, monkeypatch, source):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    css = tmp_path / "x.module.css"
    css.write_text(".live {}\n.dead {}\n", encoding="utf-8")
    (tmp_path / "consumer.tsx").write_text(source, encoding="utf-8")

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])

    assert result.exit_code == 0, result.output
    assert {f.name for f in findings if f.removable} == {"live", "dead"}
    assert css.read_text(encoding="utf-8") == ""
