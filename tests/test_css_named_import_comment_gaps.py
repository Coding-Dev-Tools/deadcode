"""Comments are legal lexical gaps around a named-default CSS import."""

import time

import pytest
from click.testing import CliRunner

from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner


@pytest.mark.parametrize(
    "statement",
    [
        "import/*a*/{ default as styles, }/*b*/from/*c*/'./x.module.css';",
        "import/* { ignored } */{ default as styles, token }/* from ignored */from/* gap */'./x.module.css';",
        "import// before list\n{ default as styles, }// before from\nfrom// before path\n'./x.module.css';",
        "import/* first\nline */{ token, default as styles, }/* second\nline */from/* third */'./x.module.css';",
        'import/*a*/{ "default" as styles, token }/*b*/from/*c*/"./x.module.css";',
    ],
)
def test_comment_separated_named_default_import_keeps_live_css(tmp_path, monkeypatch, statement):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    css = tmp_path / "x.module.css"
    css.write_text(".live {}\n.dead {}\n", encoding="utf-8")
    (tmp_path / "consumer.tsx").write_text(statement + "\nvoid styles.live;", encoding="utf-8")

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
        "const text = \"import/*a*/{default as styles,}/*b*/from/*c*/'./x.module.css'\";",
        "// import/*a*/{default as styles,}/*b*/from/*c*/'./x.module.css'",
        "import/*a*/type {default as styles,}/*b*/from/*c*/'./x.module.css'; type Name = typeof styles.live;",
    ],
)
def test_import_comment_gaps_do_not_turn_noncode_or_type_only_names_into_uses(tmp_path, monkeypatch, source):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    css = tmp_path / "x.module.css"
    css.write_text(".live {}\n.dead {}\n", encoding="utf-8")
    (tmp_path / "consumer.tsx").write_text(source, encoding="utf-8")

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])

    assert result.exit_code == 0, result.output
    assert {f.name for f in findings if f.removable} == {"live", "dead"}
    assert css.read_text(encoding="utf-8") == ""
