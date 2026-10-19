"""Real CSS-module bindings and complete global rules survive removal."""

import time

import pytest
from click.testing import CliRunner

from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner


def remove_css(project, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    before = {p.name: p.read_bytes() for p in project.glob("*.css")}
    findings = DeadCodeScanner(project).scan().orphaned_css
    preview = CliRunner().invoke(cli, ["-p", str(project), "remove", "-c", "orphaned_css", "--dry-run"])
    assert preview.exit_code == 0, preview.output
    assert {p.name: p.read_bytes() for p in project.glob("*.css")} == before
    removed = CliRunner().invoke(cli, ["-p", str(project), "remove", "-c", "orphaned_css"])
    assert removed.exit_code == 0, removed.output
    return findings


@pytest.mark.parametrize(
    ("statement", "binding"),
    [
        ("import { default as styles, } from './x.module.css';", "styles"),
        ("import { token, default as styles } from './x.module.css';", "styles"),
        ("import { default as styles, token } from './x.module.css';", "styles"),
        (
            "import { first, default as styles, last as other, } from './x.module.css';",
            "styles",
        ),
        ("import {\n token,\n default as styles,\n} from './x.module.css';", "styles"),
        (
            "import { /* }, */ token, default /* bind */ as styles, } from './x.module.css';",
            "styles",
        ),
        (
            "import { token, // other binding\n default as styles, } from './x.module.css';",
            "styles",
        ),
        ("import { type Token, default as styles, } from './x.module.css';", "styles"),
        ("import { default as $css, token } from './x.module.css';", "$css"),
        ("import { token, default as café, } from './x.module.css';", "café"),
        ("import { default as 样式, token } from './x.module.css';", "样式"),
        ('import { "default" as styles, token } from "./x.module.css";', "styles"),
        ("import { 'default' as styles, } from './x.module.css';", "styles"),
        (
            'import { "x//y" as unused, default as styles, } from "./x.module.css";',
            "styles",
        ),
        ("import styles from './x.module.css';", "styles"),
        ("import * as styles from './x.module.css';", "styles"),
        ("import styles, { token } from './x.module.css';", "styles"),
    ],
)
def test_complete_default_import_lists_keep_runtime_styles(tmp_path, monkeypatch, statement, binding):
    css = tmp_path / "x.module.css"
    css.write_text(".live {}\n.dead {}\n", encoding="utf-8")
    (tmp_path / "consumer.tsx").write_text(statement + f"\nexport const node = <p className={{{binding}.live}} />;\n")

    findings = remove_css(tmp_path, monkeypatch)

    assert [(f.name, f.removable) for f in findings] == [("dead", True)]
    assert css.read_text(encoding="utf-8") == ".live {}\n"


@pytest.mark.parametrize(
    "source",
    [
        "import type { default as styles, } from './x.module.css';\ntype Name = typeof styles.live;",
        "import { type default as styles, } from './x.module.css';\ntype Name = typeof styles.live;",
        "import { default as styles, } from './x.module.css';\ntype Name = typeof styles.live;",
        "const text = \"import { default as styles, } from './x.module.css';\";\nconst styles = {}; void styles.live;",
        "/* import { default as styles, } from './x.module.css'; */\nconst styles = {}; void styles.live;",
        "const text = `import { default as styles, } from './x.module.css';`;\nconst styles = {}; void styles.live;",
        "import { other as styles, } from './x.module.css';\nconst text = 'styles.live';",
        "import { token /* default as styles */ } from './x.module.css';\nconst styles = {}; void styles.live;",
    ],
)
def test_only_runtime_default_bindings_protect_module_styles(tmp_path, monkeypatch, source):
    css = tmp_path / "x.module.css"
    css.write_text(".live {}\n.dead {}\n", encoding="utf-8")
    (tmp_path / "consumer.tsx").write_text(source, encoding="utf-8")

    findings = remove_css(tmp_path, monkeypatch)

    assert {f.name for f in findings if f.removable} == {"live", "dead"}
    assert css.read_text(encoding="utf-8") == ""


def test_multiple_default_aliases_and_neighboring_modules_keep_their_ownership(tmp_path, monkeypatch):
    first = tmp_path / "x.module.css"
    second = tmp_path / "y.module.css"
    first.write_text(".live {}\n.extra {}\n.dead {}\n", encoding="utf-8")
    second.write_text(".live {}\n.dead {}\n", encoding="utf-8")
    (tmp_path / "consumer.tsx").write_text(
        "import { default as first, token, default as second, } from './x.module.css';\n"
        "void first.live; void second.extra;\n",
        encoding="utf-8",
    )

    findings = remove_css(tmp_path, monkeypatch)

    assert {(f.file, f.name) for f in findings} == {
        ("x.module.css", "dead"),
        ("y.module.css", "live"),
        ("y.module.css", "dead"),
    }
    assert first.read_text(encoding="utf-8") == ".live {}\n.extra {}\n"
    assert second.read_text(encoding="utf-8") == ""


@pytest.mark.parametrize(
    ("rule", "used", "expected_names"),
    [
        (".live,\n.unused\\:name {}\n", "live", {"unused:name"}),
        (".first,\n.last {}\n", "", {"first", "last"}),
        (".first, /* } */\n.last {}\n", "", {"first", "last"}),
        (".first,\n.last\\:name { color: red; }\n", "first", {"last:name"}),
        (".unused {\n color: red;\n}\n", "", {"unused"}),
        ("@media (min-width: 1px) {\n.first,\n.last {}\n}\n", "first", {"last"}),
        ('.first, [data-note="}"]\n.last {}\n', "first", {"last"}),
        (".first\\:name,\n.last\\:name {}\n", "first:name", {"last:name"}),
        (".first /* note */ ,\n.last {}\n", "first", {"last"}),
        (".live,\n.unused\\:name { content: '}'; /* } */ }\n", "live", {"unused:name"}),
        (".unused\n{ color: red; }\n", "", set()),
        (".unused\n{\n color: red;\n}\n", "", set()),
    ],
)
def test_global_split_headers_and_rule_bodies_are_diagnostic_only(tmp_path, monkeypatch, rule, used, expected_names):
    css = tmp_path / "global.css"
    css.write_text(rule + ".standalone {}\n", encoding="utf-8")
    (tmp_path / "consumer.jsx").write_text(f'export const view = <p className="{used}" />;\n', encoding="utf-8")

    findings = remove_css(tmp_path, monkeypatch)

    assert {f.name for f in findings} == expected_names | {"standalone"}
    assert {f.name for f in findings if f.removable} == {"standalone"}
    assert css.read_text(encoding="utf-8") == rule


@pytest.mark.parametrize(
    "rule",
    [
        ".unused {}\n",
        ".unused { content: '}'; }\n",
        ".unused { /* { } */ color: red; }\n",
    ],
)
def test_complete_global_one_line_rules_still_remove(tmp_path, monkeypatch, rule):
    css = tmp_path / "global.css"
    css.write_text(rule, encoding="utf-8")

    findings = remove_css(tmp_path, monkeypatch)

    assert [(f.name, f.removable) for f in findings] == [("unused", True)]
    assert css.read_text(encoding="utf-8") == ""
