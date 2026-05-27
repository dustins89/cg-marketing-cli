"""cegg — Click CLI entrypoint for Crazy Egg."""
from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning, module="google.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")

import click
from rich.console import Console

from . import __version__
from . import pull as pull_mod
from . import apply as apply_mod
from .format import emit

console = Console()


@click.group(help="Personal Crazy Egg CLI — list / create / stop heatmaps.")
@click.version_option(__version__, prog_name="cegg")
def cli() -> None:
    pass


def _format_opt(f):
    return click.option(
        "--format", "fmt", type=click.Choice(["table", "json"]), default="table",
        help="Output format.",
    )(f)


# ─── connectivity / auth ──────────────────────────────────────────────────────

@cli.command("status")
def status_cmd():
    """Check that the Crazy Egg API is reachable (unauthenticated)."""
    resp = pull_mod.status()
    console.print(resp)


@cli.command("auth-check")
def auth_check_cmd():
    """Verify the API key + signing implementation works."""
    resp = pull_mod.authenticate()
    console.print(resp)


# ─── pull ─────────────────────────────────────────────────────────────────────

@cli.group("pull")
def pull_group() -> None:
    """Read commands — list heatmaps + heatmap detail."""


@pull_group.command("snapshots")
@click.option("--status", default=None,
              help="Filter by status (running / stopped / completed / processing).")
@click.option("--device", default=None,
              help="Filter by device (desktop / phone / tablet).")
@click.option("--full", is_flag=True, help="Wider columns incl. matching rules.")
@_format_opt
def snapshots_cmd(status, device, full, fmt):
    """List heatmaps. Filter by status/device with optional flags."""
    if status or device:
        rows = pull_mod.list_snapshots_filtered(status=status, device=device)
    else:
        rows = pull_mod.list_snapshots()
    cols = pull_mod.COLUMNS["snapshots-full"] if full else pull_mod.COLUMNS["snapshots"]
    title = f"Heatmaps ({len(rows)})"
    if status:
        title += f" — status={status}"
    if device:
        title += f" — device={device}"
    emit(rows, cols, fmt, title=title)


@pull_group.command("summary")
@_format_opt
def summary_cmd(fmt):
    """Group heatmaps by status × device — finds stale / completed / out-of-visits buckets."""
    rows = pull_mod.snapshot_summary()
    emit(rows, pull_mod.COLUMNS["summary"], fmt, title=f"Heatmap summary ({len(rows)} buckets)")


@pull_group.command("snapshot")
@click.argument("snapshot_id")
def snapshot_cmd(snapshot_id):
    """Fetch detail for a single heatmap."""
    import json
    print(json.dumps(pull_mod.get_snapshot(snapshot_id), indent=2, default=str))


# ─── apply ────────────────────────────────────────────────────────────────────

@cli.command("apply")
@click.argument("changes_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--dry-run", is_flag=True, help="Print intended mutations without executing.")
@click.option("--yes", "assume_yes", is_flag=True, help="Skip per-change confirmation (use with care).")
def apply_cmd(changes_file, dry_run, assume_yes):
    """Apply changes from a pending-changes YAML file."""
    apply_mod.apply_file(changes_file, dry_run=dry_run, assume_yes=assume_yes)


def main():
    try:
        cli()
    except Exception as e:
        console.print(f"[red]error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
