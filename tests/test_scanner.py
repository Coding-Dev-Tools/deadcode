"""Tests for DeadCode scanner and CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner


@pytest.fixture
def runner():
    from click.testing import CliRunner
    return CliRunner()


@pytest.fixture
def sample_project(tmp_path):
    """Create a sample TS/React project structure."""
    # src/utils.ts - with unused export
    utils = tmp_path / "src" / "utils.ts"
    utils.parent.mkdir(parents=True, exist_ok=True)
    utils.write_text(
        'export function usedHelper() { return 1; }\n'
        'export function unusedHelper() { return 2; }\n'
        'export const USED_CONST = "used";\n'
        'export const UNUSED_CONST = "unused";\n'
    )

    # src/components/Button.tsx - component that imports from utils
    button = tmp_path / "src" / "components" / "Button.tsx"
    button.parent.mkdir(parents=True, exist_ok=True)
    button.write_text(
        'import { usedHelper, USED_CONST } from "../utils";\n'
        'export function Button() {\n'
        '  return <button className="btn-primary">{usedHelper()}</button>;\n'
        '}\n'
    )

    # src/components/UnusedWidget.tsx - never imported
    widget = tmp_path / "src" / "components" / "UnusedWidget.tsx"
    widget.write_text(
        'export function UnusedWidget() {\n'
        '  return <div>Unused</div>;\n'
        '}\n'
    )

    # src/styles/main.css - with orphaned class
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

    # src/app/page.tsx - Next.js page (entry point)
    page = tmp_path / "src" / "app" / "page.tsx"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        'import { Button } from "../components/Button";\n'
        'export default function Page() {\n'
        '  return <Button />;\n'
        '}\n'
    )

    # src/app/deadpage/page.tsx - dead route
    deadpage = tmp_path / "src" / "app" / "deadpage" / "page.tsx"
    deadpage.parent.mkdir(parents=True, exist_ok=True)
    deadpage.write_text(
        'export default function DeadPage() {\n'
        '  return <div>Dead</div>;\n'
        '}\n'
    )

    return tmp_path


class TestScanner:
    def test_scan_finds_unused_exports(self, sample_project):
        scanner = DeadCodeScanner(sample_project)
        result = scanner.scan()

        unused_names = {f.name for f in result.unused_exports}
        assert "unusedHelper" in unused_names
        assert "UNUSED_CONST" in unused_names
        assert "usedHelper" not in unused_names
        assert "USED_CONST" not in unused_names

    def test_scan_finds_orphaned_css(self, sample_project):
        scanner = DeadCodeScanner(sample_project)
        result = scanner.scan()

        orphaned_names = {f.name for f in result.orphaned_css}
        assert "orphaned-class" in orphaned_names
        assert "btn-primary" not in orphaned_names

    def test_scan_finds_unreferenced_components(self, sample_project):
        scanner = DeadCodeScanner(sample_project)
        result = scanner.scan()

        comp_names = {f.name for f in result.unreferenced_components}
        assert "UnusedWidget" in comp_names
        assert "Button" not in comp_names

    def test_scan_finds_dead_routes(self, sample_project):
        scanner = DeadCodeScanner(sample_project)
        result = scanner.scan()

        route_names = {f.name for f in result.dead_routes}
        assert "/deadpage" in route_names

    def test_scan_files_counted(self, sample_project):
        scanner = DeadCodeScanner(sample_project)
        result = scanner.scan()
        assert result.files_scanned > 0

    def test_empty_project(self, tmp_path):
        scanner = DeadCodeScanner(tmp_path)
        result = scanner.scan()
        assert result.files_scanned == 0
        assert len(result.findings) == 0

    def test_ignore_patterns(self, sample_project):
        scanner = DeadCodeScanner(sample_project, ignore_patterns=["src/styles/"])
        result = scanner.scan()
        # Orphaned CSS should not appear since we're ignoring styles dir
        assert len(result.orphaned_css) == 0

    def test_scan_result_properties(self, sample_project):
        scanner = DeadCodeScanner(sample_project)
        result = scanner.scan()
        # Verify all findings are categorized
        for f in result.findings:
            assert f.category in ("unused_export", "dead_route", "orphaned_css", "unreferenced_component")


class TestExportParsing:
    def test_named_exports(self, tmp_path):
        f = tmp_path / "test.ts"
        f.write_text(
            'export function foo() {}\n'
            'export const bar = 1;\n'
            'export type Baz = string;\n'
            'export interface Qux {}\n'
        )
        scanner = DeadCodeScanner(tmp_path)
        result = scanner.scan()

        export_names = {f.name for f in result.unused_exports}
        assert "foo" in export_names
        assert "bar" in export_names
        assert "Baz" in export_names
        assert "Qux" in export_names

    def test_export_list(self, tmp_path):
        f = tmp_path / "test.ts"
        f.write_text(
            'const alpha = 1;\n'
            'const beta = 2;\n'
            'export { alpha, beta };\n'
        )
        scanner = DeadCodeScanner(tmp_path)
        result = scanner.scan()

        export_names = {f.name for f in result.unused_exports}
        assert "alpha" in export_names
        assert "beta" in export_names

    def test_used_exports_not_reported(self, tmp_path):
        mod = tmp_path / "mod.ts"
        mod.write_text('export function myFunc() { return 1; }\n')
        app = tmp_path / "app.ts"
        app.write_text('import { myFunc } from "./mod";\nmyFunc();\n')

        scanner = DeadCodeScanner(tmp_path)
        result = scanner.scan()

        unused_names = {f.name for f in result.unused_exports}
        assert "myFunc" not in unused_names


class TestCSSParsing:
    def test_orphaned_css_detection(self, tmp_path):
        css = tmp_path / "styles.css"
        css.write_text(
            '.used-class { color: blue; }\n'
            '.orphaned-class { color: red; }\n'
        )
        component = tmp_path / "Component.tsx"
        component.write_text(
            'export function Component() {\n'
            '  return <div className="used-class">Hi</div>;\n'
            '}\n'
        )

        scanner = DeadCodeScanner(tmp_path)
        result = scanner.scan()

        orphaned = {f.name for f in result.orphaned_css}
        assert "orphaned-class" in orphaned
        assert "used-class" not in orphaned


class TestRouteDetection:
    def test_nextjs_app_router_route(self, tmp_path):
        page = tmp_path / "app" / "about" / "page.tsx"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text('export default function About() { return <div>About</div>; }\n')

        scanner = DeadCodeScanner(tmp_path)
        result = scanner.scan()

        route_names = {f.name for f in result.dead_routes}
        assert "/about" in route_names

    def test_root_route_not_dead(self, tmp_path):
        page = tmp_path / "app" / "page.tsx"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text('export default function Home() { return <div>Home</div>; }\n')

        scanner = DeadCodeScanner(tmp_path)
        result = scanner.scan()

        # Root route should not be reported as dead
        route_names = {f.name for f in result.dead_routes}
        assert "/" not in route_names

    def test_linked_route_not_dead(self, tmp_path):
        page = tmp_path / "app" / "page.tsx"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            'export default function Home() { return <a href="/about">About</a>; }\n'
        )
        about = tmp_path / "app" / "about" / "page.tsx"
        about.parent.mkdir(parents=True, exist_ok=True)
        about.write_text('export default function About() { return <div>About</div>; }\n')

        scanner = DeadCodeScanner(tmp_path)
        result = scanner.scan()

        route_names = {f.name for f in result.dead_routes}
        assert "/about" not in route_names


class TestCLIIntegration:
    def test_version(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.1" in result.output

    def test_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "scan" in result.output
        assert "remove" in result.output
        assert "stats" in result.output

    def test_scan_command(self, runner, sample_project):
        result = runner.invoke(cli, ["-p", str(sample_project), "scan"])
        assert result.exit_code == 0
        assert "DeadCode Scan" in result.output

    def test_scan_json_output(self, runner, sample_project):
        result = runner.invoke(cli, ["-p", str(sample_project), "scan", "--json-output"])
        assert result.exit_code == 0
        data = json.loads(result.output, strict=False)
        assert "findings" in data
        assert "files_scanned" in data

    def test_scan_category_filter(self, runner, sample_project):
        result = runner.invoke(cli, ["-p", str(sample_project), "scan", "-c", "orphaned_css"])
        assert result.exit_code == 0
        # Text output should mention the category
        assert "Orphaned CSS" in result.output

    def test_scan_nonexistent_dir(self, runner):
        result = runner.invoke(cli, ["-p", "/nonexistent/path", "scan"])
        assert result.exit_code != 0

    def test_remove_dry_run(self, runner, sample_project):
        result = runner.invoke(cli, ["-p", str(sample_project), "remove", "--dry-run"])
        assert result.exit_code == 0
        assert "WOULD REMOVE" in result.output or "Nothing removable" in result.output or result.exit_code == 0

    def test_stats_command(self, runner, sample_project):
        result = runner.invoke(cli, ["-p", str(sample_project), "stats"])
        assert result.exit_code == 0
        assert "Files scanned" in result.output
        assert "Unused exports" in result.output

    def test_scan_ignore_option(self, runner, tmp_path):
        """--ignore option should exclude matching files from scan."""
        mod = tmp_path / "src" / "mod.ts"
        mod.parent.mkdir(parents=True, exist_ok=True)
        mod.write_text('export function unusedFunc() { return 1; }\n')

        result = runner.invoke(cli, ["-p", str(tmp_path), "-i", "src/", "scan", "--json-output"])
        assert result.exit_code == 0
        import json
        data = json.loads(result.output, strict=False)
        assert data["files_scanned"] == 0, "src/ ignored, should have 0 files"

    def test_remove_category_filter(self, runner, sample_project):
        """remove --dry-run --category should filter by category."""
        result = runner.invoke(cli, ["-p", str(sample_project), "remove", "--dry-run", "-c", "orphaned_css"])
        assert result.exit_code == 0
        # Should mention orphaned class
        assert "orphaned-class" in result.output or "Nothing removable" in result.output

    def test_remove_nonexistent_dir(self, runner):
        """remove should give graceful error for nonexistent project dir."""
        result = runner.invoke(cli, ["-p", "/nonexistent/test/path", "remove", "--dry-run"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_stats_nonexistent_dir(self, runner):
        """stats should handle nonexistent project dir gracefully."""
        result = runner.invoke(cli, ["-p", "/nonexistent/stats/path", "stats"])
        # Should not crash — scan returns 0 files for nonexistent dir
        assert result.exit_code == 0
        assert "Files scanned: 0" in result.output

    def test_main_module_entry_point(self, runner):
        """Test that python -m deadcode works (__main__ entry point fix)."""
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-m", "deadcode", "--help"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent / "src"),
        )
        assert result.returncode == 0
        assert "DeadCode" in result.stdout
        assert "scan" in result.stdout
        assert "remove" in result.stdout
        assert "stats" in result.stdout


class TestIncludePatterns:
    """Tests for the include_patterns scanner feature."""

    def test_include_patterns_filters_files(self, tmp_path):
        """When include_patterns is set, only matching files should be scanned."""
        # Create files in two dirs
        mod = tmp_path / "src" / "mod.ts"
        mod.parent.mkdir(parents=True, exist_ok=True)
        mod.write_text('export function foo() { return 1; }\\n')

        lib = tmp_path / "lib" / "helper.ts"
        lib.parent.mkdir(parents=True, exist_ok=True)
        lib.write_text('export function bar() { return 2; }\\n')

        scanner = DeadCodeScanner(tmp_path, include_patterns=["src/"])
        result = scanner.scan()

        # Only src/mod.ts should be scanned, not lib/helper.ts
        assert result.files_scanned == 1

    def test_include_patterns_allows_multiple(self, tmp_path):
        """include_patterns can specify multiple directories."""
        mod = tmp_path / "src" / "mod.ts"
        mod.parent.mkdir(parents=True, exist_ok=True)
        mod.write_text('export function foo() { return 1; }\\n')

        lib = tmp_path / "lib" / "helper.ts"
        lib.parent.mkdir(parents=True, exist_ok=True)
        lib.write_text('export function bar() { return 2; }\\n')

        scanner = DeadCodeScanner(tmp_path, include_patterns=["src/", "lib/"])
        result = scanner.scan()
        assert result.files_scanned == 2

    def test_include_patterns_none_scans_all(self, tmp_path):
        """When include_patterns is None, all scannable files are included."""
        mod = tmp_path / "src" / "mod.ts"
        mod.parent.mkdir(parents=True, exist_ok=True)
        mod.write_text('export function foo() { return 1; }\\n')

        lib = tmp_path / "lib" / "helper.ts"
        lib.parent.mkdir(parents=True, exist_ok=True)
        lib.write_text('export function bar() { return 2; }\\n')

        scanner = DeadCodeScanner(tmp_path)
        result = scanner.scan()
        assert result.files_scanned == 2

class TestScanFormat:
    """Tests for the new --format scan option."""

    def test_format_compact(self, runner, sample_project):
        result = runner.invoke(cli, ["-p", str(sample_project), "scan", "--format=compact"])
        assert result.exit_code == 0

    def test_format_github(self, runner, sample_project):
        result = runner.invoke(cli, ["-p", str(sample_project), "scan", "--format=github"])
        assert result.exit_code == 0

    def test_format_compact_with_findings(self, runner, sample_project):
        result = runner.invoke(cli, ["-p", str(sample_project), "scan", "--format=compact"])
        assert result.exit_code == 0
        assert "unusedHelper" in result.output or "No dead code" in result.output

    def test_format_github_with_findings(self, runner, sample_project):
        result = runner.invoke(cli, ["-p", str(sample_project), "scan", "--format=github"])
        assert result.exit_code == 0
        assert "::" in result.output or "No dead code" in result.output

    def test_format_json_legacy_alias(self, runner, sample_project):
        result = runner.invoke(cli, ["-p", str(sample_project), "scan", "--json-output"])
        assert result.exit_code == 0
        data = json.loads(result.output, strict=False)
        assert "findings" in data

    def test_format_json_explicit(self, runner, sample_project):
        result = runner.invoke(cli, ["-p", str(sample_project), "scan", "--format=json"])
        assert result.exit_code == 0
        data = json.loads(result.output, strict=False)
        assert "findings" in data

    def test_format_compact_empty(self, runner, tmp_path):
        result = runner.invoke(cli, ["-p", str(tmp_path), "scan", "--format=compact"])
        assert result.exit_code == 0
        assert "OK \u2014 0 findings" in result.output

    def test_format_github_empty(self, runner, tmp_path):
        result = runner.invoke(cli, ["-p", str(tmp_path), "scan", "--format=github"])
        assert result.exit_code == 0
        assert "deadcode: 0 findings" in result.output

    def test_format_pretty_default(self, runner, sample_project):
        result = runner.invoke(cli, ["-p", str(sample_project), "scan"])
        assert result.exit_code == 0
        assert "DeadCode Scan" in result.output
