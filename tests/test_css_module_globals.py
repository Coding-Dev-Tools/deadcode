"""Global escapes in CSS modules consume literal JSX classes without leaking scope."""

import pytest
from click.testing import CliRunner

from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner


@pytest.mark.parametrize(
    "stylesheet",
    [
        ":global .live {}\n.local {}\n",
        ":global(.live) {}\n.local {}\n",
        ":global .live:hover {}\n.local {}\n",
        ":global\n.live {}\n.local {}\n",
        "@media (min-width: 20px) {\n:global(.live) {}\n.local {}\n}\n",
        ":global {\n.live {}\n}\n.local {}\n",
        ":global {\n:local(.local) {}\n.live {}\n}\n",
        ":local {\n:global(.live) {}\n.local {}\n}\n",
    ],
)
def test_global_module_selectors_consume_literal_classes_but_local_selectors_do_not(tmp_path, stylesheet):
    (tmp_path / "Card.module.css").write_text(stylesheet)
    (tmp_path / "consumer.tsx").write_text('export const View = () => <div className="live local" />;\n')

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert [(finding.name, finding.removable) for finding in findings] == [("local", True)]


@pytest.mark.parametrize(
    "selector",
    [
        ":global(.live) .local",
        ".local :global(.live)",
        ":global .live, .local",
        ":global .live, :local .local",
        ":global(.live):local(.local)",
        ":is(:global(.live), .local)",
        ":global(.live, .other) .local",
        ":global .live :local(.local)",
    ],
)
def test_scope_switches_and_selector_lists_do_not_mark_the_whole_rule_global(tmp_path, selector):
    (tmp_path / "Card.module.css").write_text(selector + " { color: red; }\n")
    (tmp_path / "consumer.tsx").write_text('export const View = () => <div className="live other local" />;\n')

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert [finding.name for finding in findings] == ["local"]
    assert not findings[0].removable
    assert "shares a rule or line" in findings[0].detail


def test_global_and_local_definitions_of_the_same_name_stay_distinct(tmp_path):
    (tmp_path / "Card.module.css").write_text(":global .shared {}\n.shared {}\n")
    (tmp_path / "Other.module.css").write_text(".shared {}\n")
    (tmp_path / "consumer.tsx").write_text('export const View = () => <div className="shared" />;\n')

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert {(finding.file, finding.line, finding.name) for finding in findings} == {
        ("Card.module.css", 2, "shared"),
        ("Other.module.css", 1, "shared"),
    }
    assert all(finding.removable for finding in findings)


def test_module_access_does_not_protect_a_global_escape_of_the_same_name(tmp_path):
    (tmp_path / "Card.module.css").write_text(":global(.shared) {}\n.shared {}\n")
    (tmp_path / "consumer.tsx").write_text(
        "import styles from './Card.module.css';\nexport const View = () => <div className={styles.shared} />;\n"
    )

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert [(finding.line, finding.name, finding.removable) for finding in findings] == [(1, "shared", True)]


@pytest.mark.parametrize(
    "stylesheet",
    [
        '/* :global .fake {} */\n.local { content: ":global .fake {}"; }\n',
        '[data-mode=":global .fake"] .local { background: url(".fake.svg"); }\n',
        '/* :global */ .local { content: "escaped \\" :global .fake"; }\n',
    ],
)
def test_comments_strings_and_attribute_values_cannot_change_selector_scope(tmp_path, stylesheet):
    (tmp_path / "Card.module.css").write_text(stylesheet)
    (tmp_path / "consumer.tsx").write_text('export const View = () => <div className="local fake" />;\n')

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert [finding.name for finding in findings] == ["local"]


def test_multiline_selector_groups_keep_unused_classes_visible_but_nonremovable(tmp_path):
    (tmp_path / "Card.module.css").write_text(":global(.live),\n.local { color: red; }\n")
    (tmp_path / "consumer.tsx").write_text('export const View = () => <div className="live" />;\n')

    findings = DeadCodeScanner(tmp_path).scan().orphaned_css

    assert [(finding.line, finding.name, finding.removable) for finding in findings] == [(2, "local", False)]


@pytest.mark.parametrize("selector", [":global .live", ":global(.live)"])
def test_remove_keeps_live_global_module_rules_and_removes_separate_unused_local_rules(tmp_path, selector):
    live = selector + " { color: red; }\n"
    (tmp_path / "Card.module.css").write_text(live + ".unused { color: blue; }\n")
    (tmp_path / "consumer.tsx").write_text('export const View = () => <div className="live" />;\n')

    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "Card.module.css").read_text() == live


def test_remove_retains_a_mixed_rule_with_a_live_global_selector(tmp_path):
    stylesheet = ":global(.live), .unused { color: red; }\n"
    (tmp_path / "Card.module.css").write_text(stylesheet)
    (tmp_path / "consumer.tsx").write_text('export const View = () => <div className="live" />;\n')

    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "Card.module.css").read_text() == stylesheet
