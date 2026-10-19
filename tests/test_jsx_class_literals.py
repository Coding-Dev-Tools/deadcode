"""JSX attributes, JavaScript expressions and uncertain values keep live CSS."""

import time

import pytest
from click.testing import CliRunner

from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner


@pytest.fixture(autouse=True)
def no_countdown(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)


LITERAL_CASES = [
    (r".foo\'bar", "foo'bar", '"foo\'bar"'),
    (r".foo\"bar", 'foo"bar', "'foo\"bar'"),
    (r".foo\'bar", "foo'bar", '"foo&apos;bar"'),
    (r".foo\'bar", "foo'bar", '"foo&#39;bar"'),
    (r".foo\'bar", "foo'bar", '"foo&#x27;bar"'),
    (r".foo\"bar", 'foo"bar', '"foo&quot;bar"'),
    (r".foo\&bar", "foo&bar", '"foo&amp;bar"'),
    (r".foo\&copybar", "foo&copybar", '"foo&copybar"'),
    (".foo©bar", "foo©bar", '"foo&copy;bar"'),
    (r".foo\&unknown\;bar", "foo&unknown;bar", '"foo&unknown;bar"'),
    (r".foo\&NotEqualTilde\;bar", "foo&NotEqualTilde;bar", '"foo&NotEqualTilde;bar"'),
    (r".foo\&NoBreak\;bar", "foo&NoBreak;bar", '"foo&NoBreak;bar"'),
    (r".foo\&NewLine\;bar", "foo&NewLine;bar", '"foo&NewLine;bar"'),
    (r".foo\&apos\;bar", "foo&apos;bar", '"foo&amp;apos;bar"'),
    (r".foo\a0 bar", "foo\u00a0bar", '"foo&nbsp;bar"'),
    (r".foo\202f bar", "foo\u202fbar", '"foo&#8239;bar"'),
    (r".foo\80 bar", "foo\u0080bar", '"foo&#128;bar"'),
    (r".foo\1f680 bar", "foo🚀bar", '"foo&#x1f680;bar"'),
    (r".foo\\x27bar", r"foo\x27bar", r'"foo\x27bar"'),
    (r".foo\'bar", "foo'bar", r"""{'foo\'bar'}"""),
    (r".foo\"bar", 'foo"bar', r"""{"foo\"bar"}"""),
    (r".foo\'bar", "foo'bar", r"""{"foo\x27bar"}"""),
    (r".foo\'bar", "foo'bar", r"""{'foo\u0027bar'}"""),
    (r".foo\'bar", "foo'bar", r"""{`foo'bar`}"""),
    (r".foo\'bar", "foo'bar", r"""{("foo'bar")}"""),
    (r".foo\&apos\;bar", "foo&apos;bar", r"""{"foo&apos;bar"}"""),
    (r".foo\b bar", "foo\vbar", r"""{"foo\vbar"}"""),
    (r".foo\'bar", "foo'bar", r"""{classNames("foo'bar")}"""),
    (r".foo\'bar", "foo'bar", r"""{clsx('foo\x27bar')}"""),
]


@pytest.mark.parametrize(("selector", "name", "attribute"), LITERAL_CASES)
@pytest.mark.parametrize("stylesheet", ["global.css", "Card.module.css"])
def test_quoted_and_entity_classes_survive_real_remove_with_unused_control(
    tmp_path, selector, name, attribute, stylesheet
):
    selected = f":global({selector})" if stylesheet.endswith(".module.css") else selector
    live = selected + " { color: red; }\n"
    (tmp_path / stylesheet).write_text(live + ".unused {}\n", encoding="utf-8")
    (tmp_path / "consumer.tsx").write_text(f'const view = <div title=">" className={attribute} />;\n', encoding="utf-8")

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert [(finding.name, finding.removable) for finding in findings] == [("unused", True)]
    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / stylesheet).read_text(encoding="utf-8") == live


def test_single_quoted_class_attribute_and_nested_jsx_text_use_the_right_delimiter(tmp_path):
    live = '.foo\\"bar {}\n'
    (tmp_path / "global.css").write_text(live + ".unused {}\n")
    (tmp_path / "consumer.jsx").write_text("const view = <p>It's <i class='foo\"bar' /></p>;\n")

    assert [finding.name for finding in DeadCodeScanner(tmp_path).scan().orphaned_css] == ["unused"]
    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "global.css").read_text() == live


@pytest.mark.parametrize("extension", ["ts", "js", "tsx", "jsx"])
def test_javascript_class_property_and_classnames_calls_decode_string_escapes(tmp_path, extension):
    (tmp_path / "global.css").write_text(".foo\\'bar {}\n.unused {}\n")
    (tmp_path / f"consumer.{extension}").write_text(
        r"""const attrs = {className: "foo\x27bar"}; const selected = classNames('foo\u0027bar');""" + "\n"
    )

    assert [(finding.name, finding.removable) for finding in DeadCodeScanner(tmp_path).scan().orphaned_css] == [
        ("unused", True)
    ]


@pytest.mark.parametrize(
    "expression",
    ["selected", "getClassName()", "'foo' + suffix", "`foo${suffix}`", "active ? 'live' : alternative"],
)
def test_uncertain_global_expressions_keep_findings_visible_and_disable_automatic_removal(tmp_path, expression):
    global_css = ".live {}\n.unusedGlobal {}\n"
    (tmp_path / "global.css").write_text(global_css)
    (tmp_path / "Card.module.css").write_text(".unusedLocal {}\n")
    (tmp_path / "consumer.tsx").write_text(f"const view = <div className={{{expression}}} />;\n")

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert any(finding.name == "unusedGlobal" and not finding.removable for finding in findings)
    assert all(not finding.removable for finding in findings if finding.name == "live")
    assert any(finding.name == "unusedLocal" and finding.removable for finding in findings)
    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "global.css").read_text() == global_css
    assert (tmp_path / "Card.module.css").read_text() == ""


def test_escaped_string_constant_is_retained_when_expression_binding_is_uncertain(tmp_path):
    stylesheet = ".foo\\'bar {}\n.unused {}\n"
    (tmp_path / "global.css").write_text(stylesheet)
    (tmp_path / "consumer.tsx").write_text(
        r"""const selected = 'foo\x27bar'; const view = <div className={selected} />;""" + "\n"
    )

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert all(not finding.removable for finding in findings)
    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "global.css").read_text() == stylesheet


def test_spread_props_keep_uncertain_global_classes_nonremovable(tmp_path):
    (tmp_path / "global.css").write_text(".live {}\n")
    (tmp_path / "consumer.tsx").write_text("const view = <div {...attrs} />;\n")

    assert [(finding.name, finding.removable) for finding in DeadCodeScanner(tmp_path).scan().orphaned_css] == [
        ("live", False)
    ]


def test_dynamic_css_module_key_keeps_only_its_module_uncertain(tmp_path):
    for name in ["Card.module.css", "Other.module.css", "global.css"]:
        (tmp_path / name).write_text(".live {}\n")
    (tmp_path / "consumer.tsx").write_text(
        "import styles from './Card.module.css';\nconst view = <div className={styles[variant]} />;\n"
    )

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert {finding.file for finding in findings} == {"Card.module.css", "Other.module.css", "global.css"}
    assert {finding.file for finding in findings if finding.removable} == {"Other.module.css", "global.css"}


def test_oversized_numeric_entity_cannot_crash_or_make_uncertain_css_removable(tmp_path):
    (tmp_path / "global.css").write_text(".live {}\n")
    (tmp_path / "consumer.tsx").write_text('const view = <div className="&#' + "9" * 5000 + ';" />;\n')

    assert [(finding.name, finding.removable) for finding in DeadCodeScanner(tmp_path).scan().orphaned_css] == [
        ("live", False)
    ]


@pytest.mark.parametrize("value", ["'foo' + suffix", "'foo'.concat(suffix)"])
def test_javascript_property_literal_prefix_does_not_hide_uncertain_suffix(tmp_path, value):
    (tmp_path / "global.css").write_text(".foobar {}\n.unused {}\n")
    (tmp_path / "consumer.ts").write_text(f"const attrs = {{className: {value}}};\n")

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert {finding.name for finding in findings} == {"foobar", "unused"}
    assert all(not finding.removable for finding in findings)
