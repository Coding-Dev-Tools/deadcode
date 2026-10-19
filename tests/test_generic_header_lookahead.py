"""Complete generic-arrow headers avoid lexing the following file repeatedly."""

import time

import pytest
from click.testing import CliRunner

from deadcode import _typescript
from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner


@pytest.mark.parametrize("count", [40, 100, 400])
@pytest.mark.parametrize("constraint", ["unknown", "{}"])
def test_repeated_short_generic_arrows_have_bounded_parser_input(monkeypatch, count, constraint):
    source = 'import styles from "./Card.module.css";\n'
    source += "".join(f"const f{i} = <T extends {constraint}>(value:T) => value;\n" for i in range(count))
    source += "const view = <div className={styles.local} />;\n"
    lengths = []
    original = _typescript._RuntimeView.__init__

    def measured(self, text, *, jsx=True):
        lengths.append(len(text))
        original(self, text, jsx=jsx)

    monkeypatch.setattr(_typescript._RuntimeView, "__init__", measured)
    rendered = _typescript.class_usage_source(source, "consumer.tsx")

    assert len(rendered) == len(source)
    assert "styles.local" in rendered
    assert "extends" not in rendered
    assert sum(lengths) <= 32 * len(source)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("<T extends object>(é:T) => é", True),
        ("<T extends object>(...values:T[]) => values", True),
        ("<T extends [unknown, string]>(value:T) => value", True),
        ("<T extends /* => */ {}>(value:T) => value", True),
        ('<T extends {tag: "=> ) > <"}>(value:T) => value', True),
        ("<T extends {}>(value:T): () => {} => () => ({})", True),
        ("<T extends {}>(value:T): <U>(item:U) => {} => <U,>(item:U) => ({})", True),
        (
            "<T extends {}>(value:T): T extends string ? (() => {className:string,local:string}) "
            ": (() => {className:string,local:string}) => () => ({className:'live',local:styles.local});",
            False,
        ),
        ("<T extends {}>(value:T) { return value; }", True),
        ('<Component extends title="value" />', False),
        ("<T extends unknown>(value:T[) => value", False),
    ],
)
def test_generic_header_decisions_preserve_complete_and_fallback_boundaries(source, expected):
    assert _typescript._jsx_type_parameter_head(source, 0) is expected


@pytest.mark.parametrize("arrow_end", [8191, 8192, 8193])
def test_direct_arrow_respects_the_existing_lookahead_limit(arrow_end):
    prefix = "<T extends {}>("
    ending = ") =>"
    source = prefix + " " * (arrow_end - len(prefix) - len(ending)) + ending + " value;"
    assert _typescript._jsx_type_parameter_head(source, 0) is (arrow_end <= 8192)


@pytest.mark.parametrize("constraint", ["unknown", "{}", '{className:"legacy"}'])
def test_generic_header_optimization_preserves_live_css_and_removal(tmp_path, monkeypatch, constraint):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    consumer = tmp_path / "consumer.tsx"
    consumer.write_text(
        'import styles from "./Card.module.css";\n'
        f"const probe = <T extends {constraint}>(value:T) => "
        '({className:"live", local:styles.local});\n',
        encoding="utf-8",
    )
    global_css = tmp_path / "global.css"
    module_css = tmp_path / "Card.module.css"
    global_css.write_text(".live {}\n.dead {}\n.legacy {}\n", encoding="utf-8")
    module_css.write_text(".local {}\n.deadLocal {}\n", encoding="utf-8")
    original_source = consumer.read_bytes()

    scan = DeadCodeScanner(tmp_path).scan()
    assert not scan.errors
    assert sorted((finding.name, finding.removable) for finding in scan.orphaned_css) == [
        ("dead", True),
        ("deadLocal", True),
        ("legacy", True),
    ]
    runner = CliRunner()
    dry_run = runner.invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css", "--dry-run"])
    assert dry_run.exit_code == 0, dry_run.output
    assert global_css.read_text(encoding="utf-8") == ".live {}\n.dead {}\n.legacy {}\n"
    removed = runner.invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])
    assert removed.exit_code == 0, removed.output
    assert global_css.read_text(encoding="utf-8") == ".live {}\n"
    assert module_css.read_text(encoding="utf-8") == ".local {}\n"
    assert consumer.read_bytes() == original_source
