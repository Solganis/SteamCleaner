from __future__ import annotations

import click

from steamcleaner.cleaner.engine import CleanEngine
from steamcleaner.models.scan_result import ScanResult
from steamcleaner.scanner.engine import ScanEngine
from steamcleaner.scanner.exclusions import ExclusionRegistry
from steamcleaner.utils.fs import format_size


def _build_scanner() -> ScanEngine:
    from steamcleaner.platform import create_adapter

    platform = create_adapter()
    exclusions = ExclusionRegistry()
    return ScanEngine(platform, exclusions)


def _print_results(result: ScanResult):
    if not result.entries:
        click.echo("No junk found.")
        return

    by_client = result.by_client()
    for client_name, entries in sorted(by_client.items()):
        click.echo(f"\n  [{client_name}]")
        for entry in sorted(entries, key=lambda entry: entry.size_bytes, reverse=True):
            click.echo(f"    {format_size(entry.size_bytes):>10}  {entry.path}")

    click.echo(f"\n  Total: {format_size(result.total_bytes)} in {len(result.entries)} items")


@click.group(invoke_without_command=True)
@click.version_option(package_name="steamcleaner")
@click.pass_context
def cli(ctx: click.Context):
    """SteamCleaner — reclaim disk space from game clients."""
    if ctx.invoked_subcommand is None:
        from steamcleaner.ui.gui.app import run_gui

        run_gui()


@cli.command()
def scan():
    """Scan for junk files across installed game clients."""
    engine = _build_scanner()

    def on_progress(msg: str, _count: int):
        click.echo(f"  {msg}")

    click.echo("Scanning...")
    result = engine.scan(progress=on_progress)
    _print_results(result)


@cli.command()
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be deleted without deleting.")
@click.option("--no-trash", is_flag=True, default=False, help="Permanently delete instead of sending to trash.")
@click.confirmation_option(prompt="This will delete junk files. Continue?")
def clean(*, dry_run: bool, no_trash: bool):
    """Delete detected junk files."""
    scanner = _build_scanner()

    click.echo("Scanning...")
    result = scanner.scan()

    if not result.entries:
        click.echo("No junk found. Nothing to clean.")
        return

    _print_results(result)

    if dry_run:
        click.echo("\n  [DRY RUN] No files were deleted.")
        return

    cleaner = CleanEngine(use_trash=not no_trash, dry_run=dry_run)
    stats = cleaner.clean(result)

    click.echo(f"\n  Deleted: {stats.deleted} items ({format_size(stats.bytes_freed)})")
    if stats.skipped:
        click.echo(f"  Skipped: {stats.skipped} items")
    for error in stats.errors:
        click.echo(f"  Error: {error}", err=True)
