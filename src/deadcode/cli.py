"""DeadCode CLI — Detect and remove unused code in TS/React/Next.js projects."""

from __future__ import annotations

import click
import json
import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table

try:
    from revenueholdings_license import require_license
except ImportError:
    import warnings
    warnings.warn("revenueholdings-license not installed; license checks skipped", stacklevel=2)
    def require_license(product: str) -> None:  # type: ignore[misc]
        pass

from . import __version__
from .config import DeadCodeConfig
from .scanner import DeadCodeScanner, Finding

console = Console()
err_console = Console(stderr=True)

ALL_CATEGORIES = ["unused_export", "dead_route", "orphaned_css", "unreferenced_component"]


@click.group()
@click.option("--project", "-p", default=".", help="Project directory to scan")
@click.option("--ignore", "-i", multiple=True, help="Additional ignore patterns (gitignore-style)")
@click.version_option(__version__, prog_name="deadcode")
@click.pass_context
def cli(ctx: click.Context, project: str, ignore: tuple[str, ...]) -> None:
    """DeadCode — Find and remove dead code in TS/React/Next.js projects.

    Scans for unused exports, dead routes, orphaned CSS classes,
    and unreferenced components.
    """
    ctx.ensure_object(dict)
    ctx.obj["project"] = project
    ctx.obj["ignore"] = list(ignore) if ignore else None
    # Load .deadcode.yml config
    ctx.obj["config"] = DeadCodeConfig.load(project)


def _merge_config_ignore(ctx: click.Context) -> list[str] | None:
    """Merge CLI --ignore flags with .deadcode.yml ignore patterns."""
    cli_ignore = ctx.obj.get("ignore")
    config = ctx.obj.get("config")
    config_ignore = config.ignore if config else []

    if cli_ignore and config_ignore:
        return config_ignore + cli_ignore
    if cli_ignore:
        return cli_ignore
    if config_ignore:
        return config_ignore
    return None


def _get_fail_threshold(ctx: click.Context) -> int:
    """Get fail threshold from config."""
    config = ctx.obj.get("config")
    return config.fail_threshold if config else -1


# ── scan ──────────────────────────────────────────────────────────────


@cli.command()
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON")
@click.option("--category", "-c", type=click.Choice(ALL_CATEGORIES), default=None, help="Filter by category")
@click.option("--fail", "fail_threshold", type=int, default=None,
              help="Exit code 1 if findings >= threshold (overrides .deadcode.yml)")
@click.pass_context
def scan(ctx: click.Context, json_output: bool, category: str | None, fail_threshold: int | None) -> None:
    """Scan project for dead code."""
    if require_license:
        require_license("deadcode")
    project = ctx.obj["project"]
    ignore = _merge_config_ignore(ctx)

    if not Path(project).exists():
        err_console.print(f"[red]Project directory '{project}' not found.[/red]")
        sys.exit(1)

    scanner = DeadCodeScanner(project, ignore_patterns=ignore)
    result = scanner.scan()

    # Filter by category
    findings = result.findings
    if category:
        findings = [f for f in findings if f.category == category]

    # Also respect config-level category filter if no CLI override
    config = ctx.obj.get("config")
    if not category and config and config.categories:
        findings = [f for f in findings if f.category in config.categories]

    if json_output:
        output = {
            "files_scanned": result.files_scanned,
            "findings": [
                {"file": f.file, "line": f.line, "name": f.name,
                 "category": f.category, "detail": f.detail, "removable": f.removable}
                for f in findings
            ],
            "errors": result.errors,
        }
        console.print(json.dumps(output, indent=2, default=str))
    else:
        # Summary
        console.print(f"\n[bold]DeadCode Scan[/bold] — {result.files_scanned} files scanned\n")

        if not findings:
            console.print("[green]✓ No dead code found![/green]")
        else:
            # Group by category
            by_category: dict[str, list[Finding]] = {}
            for f in findings:
                by_category.setdefault(f.category, []).append(f)

            category_labels = {
                "unused_export": "Unused Exports",
                "dead_route": "Dead Routes",
                "orphaned_css": "Orphaned CSS",
                "unreferenced_component": "Unreferenced Components",
            }

            for cat, cat_findings in by_category.items():
                label = category_labels.get(cat, cat)
                console.print(f"\n[bold yellow]{label}[/bold yellow] ({len(cat_findings)})")

                table = Table(show_header=True)
                table.add_column("File", style="cyan")
                table.add_column("Line", style="magenta", justify="right")
                table.add_column("Name", style="green")
                table.add_column("Detail")

                for f in cat_findings[:50]:  # Limit display
                    table.add_row(f.file, str(f.line), f.name, f.detail[:60])

                console.print(table)
                if len(cat_findings) > 50:
                    console.print(f"  [dim]... and {len(cat_findings) - 50} more[/dim]")

            # Total
            removable = sum(1 for f in findings if f.removable)
            console.print(f"\n[bold]Total:[/bold] {len(findings)} findings ({removable} removable)")

        if result.errors:
            console.print(f"\n[yellow]{len(result.errors)} scan errors (use --json-output to see)[/yellow]")

    # CI fail threshold
    effective_threshold = fail_threshold if fail_threshold is not None else _get_fail_threshold(ctx)
    if effective_threshold >= 0 and len(findings) >= effective_threshold:
        if not json_output:
            console.print(f"\n[red]FAIL: {len(findings)} findings >= threshold {effective_threshold}[/red]")
        sys.exit(1)


# ── remove ────────────────────────────────────────────────────────────


@cli.command()
@click.option("--dry-run", is_flag=True, help="Preview what would be removed without making changes")
@click.option("--category", "-c", type=click.Choice(ALL_CATEGORIES),
              default=None, help="Only remove findings in this category")
@click.pass_context
def remove(ctx: click.Context, dry_run: bool, category: str | None) -> None:
    """Remove dead code (with --dry-run for preview).

    WARNING: This modifies files. Always use --dry-run first and
    commit your code before running without it.
    """
    project = ctx.obj["project"]
    ignore = _merge_config_ignore(ctx)

    if not dry_run:
        console.print("[red]WARNING: This will modify files. Use --dry-run first![/red]")
        console.print("[dim]Press Ctrl+C to abort. Running in 3 seconds...[/dim]")
        import time
        time.sleep(3)

    scanner = DeadCodeScanner(project, ignore_patterns=ignore)
    result = scanner.scan()

    findings = result.findings
    if category:
        findings = [f for f in findings if f.category == category]

    # Also respect config-level category filter if no CLI override
    config = ctx.obj.get("config")
    if not category and config and config.categories:
        findings = [f for f in findings if f.category in config.categories]

    # Only remove removable findings
    removable = [f for f in findings if f.removable]

    if not removable:
        console.print("[green]✓ Nothing removable found.[/green]")
        return

    # Group by file
    by_file: dict[str, list[Finding]] = {}
    for f in removable:
        by_file.setdefault(f.file, []).append(f)

    removed_count = 0
    project_path = Path(project).resolve()

    for rel_file, file_findings in sorted(by_file.items()):
        filepath = project_path / rel_file
        if not filepath.exists():
            continue

        try:
            lines = filepath.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        except Exception as e:
            console.print(f"[red]Error reading {rel_file}: {e}[/red]")
            continue

        # Remove lines in reverse order to preserve line numbers
        lines_to_remove = sorted(set(f.line for f in file_findings), reverse=True)

        if dry_run:
            for line_num in sorted(lines_to_remove):
                content = lines[line_num - 1].rstrip() if line_num <= len(lines) else ""
                console.print(f"[yellow]WOULD REMOVE[/yellow] {rel_file}:{line_num} — {content.strip()[:80]}")
            removed_count += len(lines_to_remove)
        else:
            for line_num in lines_to_remove:
                if 0 < line_num <= len(lines):
                    lines[line_num - 1] = ""  # Blank the line (safer than deleting)
            filepath.write_text("".join(lines), encoding="utf-8")
            removed_count += len(lines_to_remove)
            console.print(f"[green]✓[/green] Cleaned {rel_file} ({len(lines_to_remove)} lines)")

    action = "Would remove" if dry_run else "Removed"
    console.print(f"\n[bold]{action}: {removed_count} dead code entries[/bold]")


# ── stats ─────────────────────────────────────────────────────────────


@cli.command()
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Show quick stats about the project's dead code."""
    if require_license:
        require_license("deadcode")
    project = ctx.obj["project"]
    ignore = _merge_config_ignore(ctx)
    scanner = DeadCodeScanner(project, ignore_patterns=ignore)
    result = scanner.scan()

    console.print(f"Files scanned: [bold]{result.files_scanned}[/bold]")
    console.print(f"Unused exports: [bold yellow]{len(result.unused_exports)}[/bold yellow]")
    console.print(f"Dead routes: [bold red]{len(result.dead_routes)}[/bold red]")
    console.print(f"Orphaned CSS: [bold magenta]{len(result.orphaned_css)}[/bold magenta]")
    console.print(f"Unreferenced components: [bold cyan]{len(result.unreferenced_components)}[/bold cyan]")
    console.print(f"Total findings: [bold]{len(result.findings)}[/bold]")

    if result.errors:
        console.print(f"[yellow]Errors: {len(result.errors)}[/yellow]")


if __name__ == "__main__":
    cli()
