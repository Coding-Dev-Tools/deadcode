"""Tests for __main__.py entry point and CLI edge cases."""

from __future__ import annotations

import sys
import subprocess


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
