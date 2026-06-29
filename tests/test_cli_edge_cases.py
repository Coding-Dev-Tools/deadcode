"""Tests for __main__.py entry point and CLI edge cases."""

from __future__ import annotations

import json

import pytest

from deadcode.cli import cli


class TestMainModule:
    """Tests for __main__.py entry point (0% coverage)."""

    @pytest.fixture
    def runner(self):
        from click.testing import CliRunner

        return CliRunner()

    def test_main_module_runs_help(self, runner):
        """python -m deadcode --help works (covers __main__.py:2-5)."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output


class TestCliEdgeCases:
    """Edge cases for CLI uncovered paths."""

    @pytest.fixture
    def runner(self):
        from click.testing import CliRunner

        return CliRunner()

    def test_non_existent_project_exits_1(self, runner):
        """Scan with non-existent project exits 1 (cli.py:88-90)."""
        result = runner.invoke(cli, ["--project", "/nonexistent/path", "scan"])
        assert result.exit_code == 1

    def test_fail_threshold_exits_high(self, runner, tmp_path):
        """--fail=0 exits 1 when findings exist (covers fail threshold path)."""
        (tmp_path / "src" / "unused.ts").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "unused.ts").write_text(
            "export function unused() { return 1; }\n"
        )
        result = runner.invoke(cli, ["-p", str(tmp_path), "scan", "--fail", "0"])
        assert result.exit_code == 1
        assert "FAIL" in result.output

    def test_ignore_flag_before_subcommand(self, runner, tmp_path):
        """--ignore group option rejects submodule patterns (covers _merge_config_ignore)."""
        (tmp_path / "src" / "used.ts").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "used.ts").write_text(
            "export function used() { return 1; }\n"
        )
        (tmp_path / "src" / "unused.ts").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "unused.ts").write_text(
            "export function unused() { return 2; }\n"
        )
        result = runner.invoke(
            cli, ["-p", str(tmp_path), "--ignore", "**/unused.ts", "scan"]
        )
        assert result.exit_code == 0
        assert "unused" not in result.output


class TestCliFormatOutput:
    """Tests for scan --format output modes (added in PR #34)."""

    @pytest.fixture
    def runner(self):
        from click.testing import CliRunner

        return CliRunner()

    @pytest.fixture
    def sample(self, tmp_path):
        """A tiny TS project with at least one dead export."""
        mod = tmp_path / "src" / "mod.ts"
        mod.parent.mkdir(parents=True, exist_ok=True)
        mod.write_text(
            "export function usedHelper() { return 1; }\nexport function unusedHelper() { return 2; }\n"
        )
        return tmp_path

    def test_format_compact_output(self, runner, sample):
        """--format=compact produces one-line-per-finding output."""
        result = runner.invoke(cli, ["-p", str(sample), "scan", "--format", "compact"])
        assert result.exit_code == 0
        assert "0 findings" not in result.output
        assert "unusedHelper" in result.output
        assert "unused_export" in result.output

    def test_format_github_annotations(self, runner, sample):
        """--format=github produces ::warning/::error annotations."""
        result = runner.invoke(cli, ["-p", str(sample), "scan", "--format", "github"])
        assert result.exit_code == 0
        assert "::warning" in result.output or "::error" in result.output
        assert "unusedHelper" in result.output

    def test_format_pretty_default(self, runner, sample):
        """Default pretty format shows table output."""
        result = runner.invoke(cli, ["-p", str(sample), "scan", "--format", "pretty"])
        assert result.exit_code == 0
        assert "DeadCode Scan" in result.output

    def test_legacy_json_output_still_works(self, runner, sample):
        """Legacy --json-output flag maps to --format=json."""
        result = runner.invoke(cli, ["-p", str(sample), "scan", "--json-output"])
        assert result.exit_code == 0
        # Scanner details may contain newlines; use strict=False
        payload = json.loads(result.output, strict=False)
        assert "findings" in payload
        assert "files_scanned" in payload
        assert len(payload["findings"]) >= 1


class TestRemoveCommand:
    """Tests for the `remove` CLI command."""

    @pytest.fixture
    def runner(self):
        from click.testing import CliRunner

        return CliRunner()

    def test_remove_dry_run_nothing_removable(self, runner, tmp_path):
        """remove --dry-run on clean project prints nothing removable."""
        (tmp_path / "src" / "clean.ts").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "clean.ts").write_text("const x = 1;\n")
        result = runner.invoke(cli, ["-p", str(tmp_path), "remove", "--dry-run"])
        assert result.exit_code == 0
        assert "Nothing removable" in result.output


class TestStatsCommand:
    """Tests for the `stats` CLI command."""

    @pytest.fixture
    def runner(self):
        from click.testing import CliRunner

        return CliRunner()

    def test_stats_basic(self, runner, tmp_path):
        """stats command shows scan summary."""
        (tmp_path / "src" / "unused.ts").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "unused.ts").write_text(
            "export function unusedHelper() { return 1; }\n"
        )
        result = runner.invoke(cli, ["-p", str(tmp_path), "stats"])
        assert result.exit_code == 0
        assert "Files scanned" in result.output
