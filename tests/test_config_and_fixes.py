"""Tests for DeadCode config, --fail option, and bug fixes."""

from __future__ import annotations

import json
import pytest
from deadcode.cli import cli
from deadcode.config import DeadCodeConfig
from deadcode.scanner import DeadCodeScanner


@pytest.fixture
def runner():
    from click.testing import CliRunner
    return CliRunner()


@pytest.fixture
def sample_project(tmp_path):
    """Create a sample TS/React project structure."""
    utils = tmp_path / "src" / "utils.ts"
    utils.parent.mkdir(parents=True, exist_ok=True)
    utils.write_text(
        'export function usedHelper() { return 1; }\n'
        'export function unusedHelper() { return 2; }\n'
        'export const USED_CONST = "used";\n'
        'export const UNUSED_CONST = "unused";\n'
    )

    button = tmp_path / "src" / "components" / "Button.tsx"
    button.parent.mkdir(parents=True, exist_ok=True)
    button.write_text(
        'import { usedHelper, USED_CONST } from "../utils";\n'
        'export function Button() {\n'
        '  return <button className="btn-primary">{usedHelper()}</button>;\n'
        '}\n'
    )

    widget = tmp_path / "src" / "components" / "UnusedWidget.tsx"
    widget.write_text(
        'export function UnusedWidget() {\n'
        '  return <div>Unused</div>;\n'
        '}\n'
    )

    css = tmp_path / "src" / "styles" / "main.css"
    css.parent.mkdir(parents=True, exist_ok=True)
    css.write_text(
        '.btn-primary {\n'
        '  background: blue;\n'
        '}\n'
        '.orphaned-class {\n'
        '  color: red;\n'
        '}\n'
    )

    page = tmp_path / "src" / "app" / "page.tsx"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        'import { Button } from "../components/Button";\n'
        'export default function Page() {\n'
        '  return <Button />;\n'
        '}\n'
    )

    deadpage = tmp_path / "src" / "app" / "deadpage" / "page.tsx"
    deadpage.parent.mkdir(parents=True, exist_ok=True)
    deadpage.write_text(
        'export default function DeadPage() {\n'
        '  return <div>Dead</div>;\n'
        '}\n'
    )

    return tmp_path


class TestConfig:
    def test_default_config(self):
        config = DeadCodeConfig()
        assert config.ignore == []
        assert config.categories == ["unused_export", "dead_route", "orphaned_css", "unreferenced_component"]
        assert config.fail_threshold == -1

    def test_from_dict(self):
        data = {"ignore": ["generated/"], "categories": ["unused_export"], "fail_threshold": 5}
        config = DeadCodeConfig.from_dict(data)
        assert config.ignore == ["generated/"]
        assert config.categories == ["unused_export"]
        assert config.fail_threshold == 5

    def test_from_dict_partial(self):
        data = {"ignore": ["legacy/"]}
        config = DeadCodeConfig.from_dict(data)
        assert config.ignore == ["legacy/"]
        assert config.categories == ["unused_export", "dead_route", "orphaned_css", "unreferenced_component"]

    def test_load_from_yml(self, tmp_path):
        config_file = tmp_path / ".deadcode.yml"
        config_file.write_text(
            'ignore:\n'
            '  - "generated/"\n'
            '  - "legacy/"\n'
            'categories:\n'
            '  - unused_export\n'
            'fail_threshold: 3\n'
        )
        config = DeadCodeConfig.load(tmp_path)
        assert config.ignore == ["generated/", "legacy/"]
        assert config.categories == ["unused_export"]
        assert config.fail_threshold == 3

    def test_load_missing_yml(self, tmp_path):
        config = DeadCodeConfig.load(tmp_path)
        assert config.ignore == []
        assert config.fail_threshold == -1

    def test_load_empty_yml(self, tmp_path):
        config_file = tmp_path / ".deadcode.yml"
        config_file.write_text("")
        config = DeadCodeConfig.load(tmp_path)
        assert config.ignore == []

    def test_load_invalid_yml(self, tmp_path):
        config_file = tmp_path / ".deadcode.yml"
        config_file.write_text("not a dict: but\n  nested: weirdly")
        config = DeadCodeConfig.load(tmp_path)
        # Should fall back to defaults
        assert config.ignore == []


class TestFailOption:
    def test_fail_exits_1_when_threshold_met(self, runner, sample_project):
        result = runner.invoke(cli, ["-p", str(sample_project), "scan", "--fail", "1"])
        assert result.exit_code == 1

    def test_fail_exits_0_when_below_threshold(self, runner, sample_project):
        # Set a very high threshold
        result = runner.invoke(cli, ["-p", str(sample_project), "scan", "--fail", "999"])
        assert result.exit_code == 0

    def test_fail_zero_exits_1_on_any_finding(self, runner, sample_project):
        result = runner.invoke(cli, ["-p", str(sample_project), "scan", "--fail", "0"])
        assert result.exit_code == 1

    def test_fail_with_json_output(self, runner, sample_project):
        result = runner.invoke(cli, ["-p", str(sample_project), "scan", "--json-output", "--fail", "1"])
        assert result.exit_code == 1
        # JSON should still be valid
        data = json.loads(result.output, strict=False)
        assert "findings" in data

    def test_fail_from_config(self, runner, tmp_path):
        """Test that fail_threshold in .deadcode.yml triggers exit 1."""
        # Create a project with dead code and a config
        utils = tmp_path / "src" / "mod.ts"
        utils.parent.mkdir(parents=True, exist_ok=True)
        utils.write_text('export function unusedFunc() { return 1; }\n')

        config = tmp_path / ".deadcode.yml"
        config.write_text('fail_threshold: 1\n')

        result = runner.invoke(cli, ["-p", str(tmp_path), "scan"])
        assert result.exit_code == 1


class TestConfigIgnoreMerge:
    def test_config_ignore_used_in_scan(self, runner, tmp_path):
        """Config file ignore patterns should be applied during scan."""
        mod = tmp_path / "src" / "mod.ts"
        mod.parent.mkdir(parents=True, exist_ok=True)
        mod.write_text('export function unused() { return 1; }\n')

        config = tmp_path / ".deadcode.yml"
        config.write_text('ignore:\n  - "src/"\n')

        result = runner.invoke(cli, ["-p", str(tmp_path), "scan", "--json-output"])
        assert result.exit_code == 0
        data = json.loads(result.output, strict=False)
        # Should have 0 findings since src/ is ignored
        assert len(data["findings"]) == 0

    def test_cli_ignore_overrides_config(self, runner, tmp_path):
        """CLI --ignore should be merged with config ignore."""
        mod = tmp_path / "src" / "mod.ts"
        mod.parent.mkdir(parents=True, exist_ok=True)
        mod.write_text('export function unused() { return 1; }\n')

        # -i is a group-level option, must come before subcommand
        result = runner.invoke(cli, ["-p", str(tmp_path), "-i", "src/", "scan", "--json-output"])
        assert result.exit_code == 0
        data = json.loads(result.output, strict=False)
        assert len(data["findings"]) == 0


class TestBugFixUnreferencedComponents:
    def test_component_imported_not_reported(self, tmp_path):
        """Verify the bug fix: components that ARE imported should not be reported."""
        comp = tmp_path / "src" / "Button.tsx"
        comp.parent.mkdir(parents=True, exist_ok=True)
        comp.write_text(
            'export function Button() { return <div>Hi</div>; }\n'
        )
        app = tmp_path / "src" / "App.tsx"
        app.write_text(
            'import { Button } from "./Button";\n'
            'export function App() { return <Button />; }\n'
        )

        scanner = DeadCodeScanner(tmp_path)
        result = scanner.scan()

        comp_names = {f.name for f in result.unreferenced_components}
        assert "Button" not in comp_names, "Button should not be unreferenced — it's imported by App.tsx"

    def test_component_not_imported_is_reported(self, tmp_path):
        """Component with zero imports should still be reported."""
        comp = tmp_path / "src" / "Orphan.tsx"
        comp.parent.mkdir(parents=True, exist_ok=True)
        comp.write_text(
            'export function Orphan() { return <div>Orphan</div>; }\n'
        )

        scanner = DeadCodeScanner(tmp_path)
        result = scanner.scan()

        comp_names = {f.name for f in result.unreferenced_components}
        assert "Orphan" in comp_names


class TestLicenseDepRemoved:
    """Verify revenueholdings-license is fully removed and commands work without it."""

    def test_no_license_import_in_cli(self):
        """The cli module should not reference revenueholdings_license."""
        import deadcode.cli as cli_mod
        import inspect
        source = inspect.getsource(cli_mod)
        assert "revenueholdings_license" not in source
        assert "require_license" not in source

    def test_no_license_optional_dep(self):
        """pyproject.toml should not have license optional dep."""
        from pathlib import Path
        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        content = pyproject.read_text()
        assert "revenueholdings-license" not in content

    def test_scan_works_without_license(self, runner, sample_project):
        """All commands should work without the license package."""
        result = runner.invoke(cli, ["-p", str(sample_project), "scan"])
        assert result.exit_code == 0

    def test_stats_works_without_license(self, runner, sample_project):
        result = runner.invoke(cli, ["-p", str(sample_project), "stats"])
        assert result.exit_code == 0

    def test_remove_dry_run_without_license(self, runner, sample_project):
        result = runner.invoke(cli, ["-p", str(sample_project), "remove", "--dry-run"])
        assert result.exit_code == 0

class TestIncludeCLI:
    """Tests for the --include CLI option (whitelist)."""

    def test_include_filters_scan(self, runner, tmp_path):
        """--include should limit scan to matching directories."""
        mod = tmp_path / "src" / "mod.ts"
        mod.parent.mkdir(parents=True, exist_ok=True)
        mod.write_text('export function unusedInSrc() { return 1; }\n')

        lib = tmp_path / "lib" / "helper.ts"
        lib.parent.mkdir(parents=True, exist_ok=True)
        lib.write_text('export function unusedInLib() { return 2; }\n')

        result = runner.invoke(cli, ["-p", str(tmp_path), "--include", "src/", "scan", "--json-output"])
        assert result.exit_code == 0
        data = json.loads(result.output, strict=False)
        finding_names = {f["name"] for f in data["findings"]}
        assert "unusedInSrc" in finding_names
        assert "unusedInLib" not in finding_names

    def test_include_multiple_dirs(self, runner, tmp_path):
        """Multiple --include flags should scan all matching dirs."""
        mod = tmp_path / "src" / "mod.ts"
        mod.parent.mkdir(parents=True, exist_ok=True)
        mod.write_text('export function foo() { return 1; }\n')

        lib = tmp_path / "lib" / "helper.ts"
        lib.parent.mkdir(parents=True, exist_ok=True)
        lib.write_text('export function bar() { return 2; }\n')

        result = runner.invoke(cli, ["-p", str(tmp_path), "--include", "src/", "--include", "lib/", "scan", "--json-output"])
        assert result.exit_code == 0
        data = json.loads(result.output, strict=False)
        assert data["files_scanned"] == 2

    def test_include_in_stats(self, runner, tmp_path):
        """--include should also work with stats command."""
        mod = tmp_path / "src" / "mod.ts"
        mod.parent.mkdir(parents=True, exist_ok=True)
        mod.write_text('export function foo() { return 1; }\n')

        lib = tmp_path / "lib" / "helper.ts"
        lib.parent.mkdir(parents=True, exist_ok=True)
        lib.write_text('export function bar() { return 2; }\n')

        result = runner.invoke(cli, ["-p", str(tmp_path), "--include", "src/", "stats"])
        assert result.exit_code == 0
        assert "Files scanned: 1" in result.output

    def test_include_in_remove_dry_run(self, runner, tmp_path):
        """--include should also work with remove --dry-run."""
        mod = tmp_path / "src" / "mod.ts"
        mod.parent.mkdir(parents=True, exist_ok=True)
        mod.write_text('export function foo() { return 1; }\n')

        lib = tmp_path / "lib" / "helper.ts"
        lib.parent.mkdir(parents=True, exist_ok=True)
        lib.write_text('export function bar() { return 2; }\n')

        result = runner.invoke(cli, ["-p", str(tmp_path), "--include", "src/", "remove", "--dry-run"])

        assert result.exit_code == 0

    def test_include_with_ignore_more_restrictive(self, runner, tmp_path):
        """--include and --ignore should work together (include first, then ignore)."""
        mod = tmp_path / "src" / "mod.ts"
        mod.parent.mkdir(parents=True, exist_ok=True)
        mod.write_text('export function foo() { return 1; }\n')

        internal = tmp_path / "src" / "internal" / "helper.ts"
        internal.parent.mkdir(parents=True, exist_ok=True)
        internal.write_text('export function bar() { return 2; }\n')

        result = runner.invoke(cli, ["-p", str(tmp_path), "--include", "src/", "-i", "src/internal/", "scan", "--json-output"])
        assert result.exit_code == 0
        data = json.loads(result.output, strict=False)
        assert data["files_scanned"] == 1, "only mod.ts should be scanned, internal/ ignored"
        finding_names = {f["name"] for f in data["findings"]}
        assert "foo" in finding_names
        assert "bar" not in finding_names

    def test_include_no_match_returns_no_files(self, runner, tmp_path):
        """--include matching nothing should yield 0 files scanned."""
        mod = tmp_path / "src" / "mod.ts"
        mod.parent.mkdir(parents=True, exist_ok=True)
        mod.write_text('export function foo() { return 1; }\n')

        result = runner.invoke(cli, ["-p", str(tmp_path), "--include", "nonexistent/", "scan", "--json-output"])
        assert result.exit_code == 0
        data = json.loads(result.output, strict=False)
        assert data["files_scanned"] == 0

    def test_include_invalid_pattern_graceful(self, runner, tmp_path):
        """--include should handle invalid gitignore patterns without crashing."""
        mod = tmp_path / "src" / "mod.ts"
        mod.parent.mkdir(parents=True, exist_ok=True)
        mod.write_text('export function foo() { return 1; }\n')

        result = runner.invoke(cli, ["-p", str(tmp_path), "--include", "src/[invalid", "scan"])
        assert result.exit_code in (0, 2), "should not crash, may produce error or proceed"
