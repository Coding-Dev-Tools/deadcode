"""Statically named object props preserve live styles through real removal."""

import time

import pytest
from click.testing import CliRunner

from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner


@pytest.mark.parametrize("extension", ["js", "ts", "jsx", "tsx"])
@pytest.mark.parametrize(
    "property_source",
    [
        "['className']: 'live'",
        '["class"]: "live"',
        r"['class\u004eame']: 'live'",
        "[`className`]: `live`",
        "[/* name */ 'className' /* key */] /* value */ : 'live'",
        "id: 'node', ['className']: 'live'",
    ],
)
def test_computed_object_keys_keep_live_global_rules(tmp_path, monkeypatch, extension, property_source):
    (tmp_path / ("view." + extension)).write_text(
        "const props = {" + property_source + "}; React.createElement('div', props);\n",
        encoding="utf-8",
    )
    _assert_removal(tmp_path, monkeypatch, live=True)


@pytest.mark.parametrize(
    "source",
    [
        "const props = {['title']: 'live'};",
        "const names = ['className', 'live'];",
        "const map = {['className']: 'other'};",
        "// const props = {['className']: 'live'};",
        "const text = \"({['className']: 'live'})\";",
        "const text = `({['className']: 'live'})`;",
        "const pattern = /['className']: 'live'/;",
        "type Props = {['className']: 'live'};",
        "interface Props {['className']: 'live'}",
    ],
)
def test_nonruntime_or_other_computed_keys_do_not_invent_class_uses(tmp_path, monkeypatch, source):
    (tmp_path / "view.ts").write_text(source + "\n", encoding="utf-8")
    _assert_removal(tmp_path, monkeypatch, live=False)


def _assert_removal(project, monkeypatch, *, live):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    global_css = project / "global.css"
    module_css = project / "other.module.css"
    global_css.write_text(".live {}\n.unused {}\n", encoding="utf-8")
    module_css.write_text(":global(.live) {}\n.localUnused {}\n", encoding="utf-8")
    findings = DeadCodeScanner(project).scan().orphaned_css
    assert any(f.name == "unused" and f.removable for f in findings)
    assert not live or not any(f.name == "live" for f in findings)
    result = CliRunner().invoke(cli, ["-p", str(project), "remove", "-c", "orphaned_css"])
    assert result.exit_code == 0, result.output
    assert global_css.read_text(encoding="utf-8") == (".live {}\n" if live else "")
    assert module_css.read_text(encoding="utf-8") == (":global(.live) {}\n" if live else "")
