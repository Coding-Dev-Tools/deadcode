"""Escaped CSS names and computed JavaScript keys must agree before removal."""

import time

import pytest
from click.testing import CliRunner

from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner


@pytest.fixture(autouse=True)
def no_interactive_countdown(monkeypatch):
    """Exercise real scan/removal IO without waiting at the interactive warning."""
    monkeypatch.setattr(time, "sleep", lambda _: None)


@pytest.mark.parametrize(
    ("selector", "name", "accessor"),
    [
        (r".foo\:bar", "foo:bar", "['foo:bar']"),
        (r".foo\.bar", "foo.bar", '["foo.bar"]'),
        (r".foo\3a bar", "foo:bar", r"['foo\u003abar']"),
        (r".foo\00003Abar", "foo:bar", "['foo:bar']"),
        (r".foo\00002Ebar", "foo.bar", "['foo.bar']"),
        (r".\31 23", "123", "['123']"),
        (r".\00003123", "123", "['123']"),
        (".-foo", "-foo", "['-foo']"),
        (".--foo", "--foo", "['--foo']"),
        (".café", "café", "['café']"),
        (r".caf\e9", "café", r"['caf\u00e9']"),
        (r".\1f680", "🚀", r"['\u{1f680}']"),
        (".🚀", "🚀", r"['\ud83d\ude80']"),
        (r".foo\\bar", "foo\\bar", r"['foo\\bar']"),
        (r".foo\'bar", "foo'bar", '["foo\'bar"]'),
        (r".foo\"bar", 'foo"bar', "['foo\"bar']"),
        (r".foo\{bar", "foo{bar", "['foo{bar']"),
        (r".foo\}bar", "foo}bar", "['foo}bar']"),
        (r".foo\(bar", "foo(bar", "['foo(bar']"),
        (r".foo\)bar", "foo)bar", "['foo)bar']"),
        (r".foo\[bar", "foo[bar", "['foo[bar']"),
        (r".foo\]bar", "foo]bar", "['foo]bar']"),
        (r".foo\;bar", "foo;bar", "['foo;bar']"),
        (r".foo\,bar", "foo,bar", "['foo,bar']"),
        (r".foo\/bar", "foo/bar", "['foo/bar']"),
        (r".foo\ bar", "foo bar", "['foo bar']"),
        (r".foo\:bar", "foo:bar", r"['foo\x3abar']"),
        (r".foo\:bar", "foo:bar", r"['foo\:bar']"),
        (r".foo\:bar", "foo:bar", "?.['foo:bar']"),
        (r".foo\:bar", "foo:bar", "[`foo:bar`]"),
        (r".foo\`bar", "foo`bar", "['foo`bar']"),
        (r".foo\$bar", "foo$bar", "['foo$bar']"),
        (r".foo\\\:bar", "foo\\:bar", r"['foo\\:bar']"),
        (r".foo\000000bar", "foo�bar", r"['foo\ufffdbar']"),
        (r".foo\d800 bar", "foo�bar", r"['foo\ufffdbar']"),
        (r".foo\110000 bar", "foo�bar", r"['foo\ufffdbar']"),
        (r".foo\:bar", "foo:bar", "['foo\\\n:bar']"),
        (r".foo\:bar", "foo:bar", "['foo\\\r\n:bar']"),
        (r".foo\'bar", "foo'bar", r"['foo\'bar']"),
        (r".foo\"bar", 'foo"bar', r'["foo\"bar"]'),
        (r".foo\`bar", "foo`bar", r"[`foo\`bar`]"),
        (r".foo\$\{bar\}", "foo${bar}", r"[`foo\${bar}`]"),
        (r".foo\9 bar", "foo\tbar", r"['foo\tbar']"),
        (".foo\\3a\tbar", "foo:bar", "['foo:bar']"),
    ],
)
def test_remove_preserves_complete_escaped_names_and_keeps_stylesheet_scope(tmp_path, selector, name, accessor):
    live = selector + " { color: red; }\n"
    (tmp_path / "Card.module.css").write_text(live + ".unused { color: blue; }\n", encoding="utf-8")
    (tmp_path / "Other.module.css").write_text(selector + " {}\n", encoding="utf-8")
    # Preserve the intended JavaScript line-continuation bytes on Windows too.
    (tmp_path / "consumer.ts").write_bytes(
        ("import styles from './Card.module.css';\nconst selected = styles" + accessor + ";\n").encode("utf-8")
    )

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert {(finding.file, finding.name) for finding in findings} == {
        ("Card.module.css", "unused"),
        ("Other.module.css", name),
    }
    assert all(finding.removable for finding in findings)
    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "Card.module.css").read_text(encoding="utf-8") == live
    assert (tmp_path / "Other.module.css").read_text(encoding="utf-8") == ""


@pytest.mark.parametrize("scope", [":global ", ":global({})"])
@pytest.mark.parametrize(("selector", "name"), [(r".foo\:bar", "foo:bar"), (r".foo\.bar", "foo.bar")])
def test_escaped_global_classes_consume_literal_jsx_without_hiding_unused_local_classes(
    tmp_path, scope, selector, name
):
    selected = scope.format(selector) if "{}" in scope else scope + selector
    live = selected + " { color: red; }\n"
    (tmp_path / "Card.module.css").write_text(live + ".unused {}\n")
    (tmp_path / "consumer.tsx").write_text(f'const view = <div className="{name} unused" />;\n')

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert [(finding.name, finding.removable) for finding in findings] == [("unused", True)]
    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "Card.module.css").read_text() == live


@pytest.mark.parametrize("selector", [r".foo\:bar, .unused", r":global(.foo\:bar), .unused"])
def test_unused_member_of_rule_with_live_escaped_class_is_visible_but_not_removable(tmp_path, selector):
    stylesheet = selector + " { color: red; }\n"
    (tmp_path / "Card.module.css").write_text(stylesheet)
    (tmp_path / "consumer.tsx").write_text(
        "import styles from './Card.module.css';\n"
        "const selected = styles['foo:bar'];\n"
        'const view = <div className="foo:bar" />;\n'
    )

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert [(finding.name, finding.removable) for finding in findings] == [("unused", False)]
    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "Card.module.css").read_text() == stylesheet


@pytest.mark.parametrize("selector", [r".foo\:global", r".foo\3a global"])
def test_escaped_pseudo_name_does_not_switch_to_global_scope(tmp_path, selector):
    (tmp_path / "Card.module.css").write_text(selector + " .live {}\n")
    (tmp_path / "consumer.tsx").write_text('const view = <div className="foo:global live" />;\n')

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert {finding.name for finding in findings} == {"foo:global", "live"}


def test_escaped_backslash_does_not_hide_following_class_or_scope_delimiter(tmp_path):
    (tmp_path / "Card.module.css").write_text(r":global(.foo\\).bar {}" + "\n")
    (tmp_path / "consumer.ts").write_text("import styles from './Card.module.css';\nconst selected = styles.bar;\n")

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert [(finding.name, finding.removable) for finding in findings] == [("foo\\", False)]


def test_escaped_hex_terminator_newline_keeps_the_full_live_identifier(tmp_path):
    stylesheet = ".foo\\2e\r\nbar { color: red; }\n"
    (tmp_path / "Card.module.css").write_bytes(stylesheet.encode())
    (tmp_path / "consumer.ts").write_text(
        "import styles from './Card.module.css';\nconst selected = styles['foo.bar'];\n"
    )

    assert DeadCodeScanner(tmp_path).scan().orphaned_css == []
    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "Card.module.css").read_bytes() == stylesheet.encode()


def test_interpolated_template_keeps_uncertain_module_findings_visible_but_nonremovable(tmp_path):
    for name in ["Card.module.css", "Other.module.css", "global.css"]:
        (tmp_path / name).write_text(r".foo\:bar {}" + "\n")
    (tmp_path / "consumer.ts").write_text(
        "import styles from './Card.module.css';\nconst selected = styles[`foo:${suffix}`];\n"
    )

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert {(finding.file, finding.name) for finding in findings} == {
        ("Card.module.css", "foo:bar"),
        ("Other.module.css", "foo:bar"),
        ("global.css", "foo:bar"),
    }
    assert {finding.file for finding in findings if finding.removable} == {"Other.module.css", "global.css"}


def test_module_key_does_not_protect_global_selector_with_the_same_decoded_name(tmp_path):
    (tmp_path / "Card.module.css").write_text(":global(.foo\\:bar) {}\n.foo\\:bar {}\n")
    (tmp_path / "consumer.ts").write_text(
        "import styles from './Card.module.css';\nconst selected = styles['foo:bar'];\n"
    )

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert [(finding.line, finding.name, finding.removable) for finding in findings] == [(1, "foo:bar", True)]


@pytest.mark.parametrize("suffix", ["", ":hover"])
def test_global_escaped_class_uses_decoded_name_before_pseudo_selector(tmp_path, suffix):
    stylesheet = r".foo\:bar" + suffix + " { color: red; }\n"
    (tmp_path / "global.css").write_text(stylesheet)
    (tmp_path / "consumer.tsx").write_text('const view = <div className="foo:bar" />;\n')

    assert DeadCodeScanner(tmp_path).scan().orphaned_css == []
    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "global.css").read_text() == stylesheet


@pytest.mark.parametrize("filename", ["Card.module.css", "global.css"])
def test_skipped_escaped_utility_still_protects_its_shared_rule_from_removal(tmp_path, filename):
    stylesheet = r".hover\:active, .unused { color: red; }" + "\n"
    (tmp_path / filename).write_text(stylesheet)

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert [(finding.name, finding.removable) for finding in findings] == [("unused", False)]
    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / filename).read_text() == stylesheet
