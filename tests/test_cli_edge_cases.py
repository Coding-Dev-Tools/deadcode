"""Tests for __main__.py entry point and CLI edge cases."""

from __future__ import annotations

import subprocess
import sys

import pytest


class TestMainModule:
    """Tests for __main__.py entry point (0% coverage)."""

    def test_main_module_runs_help(self):
        """python -m deadcode --help works (covers __main__.py:2-5)."""
        result = subprocess.run(
            [sys.executable, "-m", "deadcode", "--help"],
            capture_output=True, text=False,
        )
        assert result.returncode == 0
        assert b"Usage" in result.stdout


class TestCliEdgeCases:
    """Edge cases for CLI uncovered paths."""

    def test_non_existent_project_exits_1(self):
        """Scan with non-existent project exits 1 (cli.py:88-90)."""
        result = subprocess.run(
            [sys.executable, "-m", "deadcode", "--project", "/nonexistent/path", "scan"],
            capture_output=True, text=False,
        )
        assert result.returncode == 1


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
            'export function usedHelper() { return 1; }\n'
            'export function unusedHelper() { return 2; }\n'
        )
        return tmp_path

    def test_format_compact_output(self, runner, sample):
        """--format=compact produces one-line-per-finding output."""
        from deadcode.cli import cli
        result = runner.invoke(cli, ["-p", str(sample), "scan", "--format", "compact"])
        assert result.exit_code == 0
        assert "0 findings" not in result.output
        assert "unusedHelper" in result.output
        assert "unused_export" in result.output

    def test_format_github_annotations(self, runner, sample):
        """--format=github produces ::warning/::error annotations."""
        from deadcode.cli import cli
        result = runner.invoke(cli, ["-p", str(sample), "scan", "--format", "github"])
        assert result.exit_code == 0
        assert "::warning" in result.output or "::error" in result.output
        assert "unusedHelper" in result.output

    def test_format_pretty_default(self, runner, sample):
        """Default pretty format shows table output."""
        from deadcode.cli import cli
        result = runner.invoke(cli, ["-p", str(sample), "scan", "--format", "pretty"])
        assert result.exit_code == 0
        assert "DeadCode Scan" in result.output

    def test_legacy_json_output_still_works(self, runner, sample):
        """Legacy --json-output flag maps to --format=json."""
        from deadcode.cli import cli
        import json
        result = runner.invoke(cli, ["-p", str(sample), "scan", "--json-output"])
        assert result.exit_code == 0
        # Scanner details may contain newlines; use strict=False
        payload = json.loads(result.output, strict=False)
        assert "findings" in payload
        assert "files_scanned" in payload
        assert len(payload["findings"]) >= 1
