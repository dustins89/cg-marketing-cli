"""postalytics — Click CLI entrypoint for Postalytics direct mail."""
from __future__ import annotations

import json
import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning, module="google.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")

import click
from rich.console import Console

from . import __version__
from . import pull as pull_mod
from .format import emit

console = Console()


@click.group(help="Personal Postalytics CLI — pull campaign stats + run audit.")
@click.version_option(__version__, prog_name="postalytics")
def cli() -> None:
    pass


def _format_opt(f):
    return click.option(
        "--format", "fmt", type=click.Choice(["table", "json"]), default="table",
        help="Output format.",
    )(f)


# ─── pull ─────────────────────────────────────────────────────────────────────

@cli.group("pull")
def pull_group() -> None:
    """Read commands — campaigns, events."""


@pull_group.command("campaigns")
@click.option("--live-only", is_flag=True,
              help="Filter to is_live_mode=1 campaigns only.")
@click.option("--with-stats", is_flag=True,
              help="Backfill real stat numbers (N+1 calls).")
@_format_opt
def campaigns_cmd(live_only, with_stats, fmt):
    """List all campaigns. Use --with-stats for real delivery numbers."""
    if with_stats:
        rows = pull_mod.list_campaigns_with_stats(only_live=live_only)
        cols = pull_mod.COLUMNS["campaigns-with-stats"]
    else:
        rows = pull_mod.list_campaigns()
        if live_only:
            rows = [r for r in rows if r.get("is_live_mode") == 1]
        cols = pull_mod.COLUMNS["campaigns"]
    title = f"Postalytics campaigns ({len(rows)})"
    if live_only:
        title += " — live only"
    emit(rows, cols, fmt, title=title)


@pull_group.command("campaign")
@click.argument("drop_id", type=int)
@_format_opt
def campaign_cmd(drop_id, fmt):
    """Detail for a single campaign by drop_id — includes real stats."""
    row = pull_mod.get_campaign(drop_id)
    if row is None:
        console.print(f"[yellow]No campaign found for drop_id={drop_id}[/yellow]")
        sys.exit(1)
    emit([row], list(row.keys()), fmt, title=f"Campaign {drop_id}")


@pull_group.command("events")
@click.argument("drop_id", type=int)
@click.option("--page", type=int, default=1, help="Page number (100/page).")
@click.option("--page-size", type=int, default=100, help="Items per page (max 100).")
@click.option("--since-days", type=int, default=None,
              help="Walk pages until events older than N days; client-side filter.")
@_format_opt
def events_cmd(drop_id, page, page_size, since_days, fmt):
    """List delivery / scan events for a campaign."""
    if since_days is not None:
        import datetime as dt
        since = dt.date.today() - dt.timedelta(days=since_days)
        rows = pull_mod.get_events_since(drop_id, since=since)
        title = f"Events for drop {drop_id} — last {since_days}d ({len(rows)})"
    else:
        rows = pull_mod.get_events(drop_id, page=page, page_size=page_size)
        title = f"Events for drop {drop_id} — page {page} ({len(rows)})"
    emit(rows, pull_mod.COLUMNS["events"], fmt, title=title)


# ─── audit ────────────────────────────────────────────────────────────────────

@cli.command("audit")
@click.option("--all", "include_all", is_flag=True,
              help="Include non-live campaigns (default: live only).")
@click.option("--json-out", type=click.Path(dir_okay=False),
              help="Write the full audit blob to this file.")
def audit_cmd(include_all, json_out):
    """Account rollup — totals, derived rates, flagged issues."""
    blob = pull_mod.audit(only_live=not include_all)

    console.print(f"\n[bold]Postalytics audit[/bold] "
                  f"({blob['scope']} campaigns, generated {blob['generated_at']})")
    console.print(f"  {len(blob['campaigns'])} campaigns scanned\n")

    console.print("[bold]Totals[/bold]")
    emit([blob["totals"]], pull_mod.COLUMNS["totals"], "table", title="")
    console.print()

    console.print("[bold]Derived rates[/bold]")
    emit([blob["rates"]], pull_mod.COLUMNS["rates"], "table", title="")
    console.print()

    console.print("[bold]Per-campaign[/bold]")
    emit(blob["campaigns"], pull_mod.COLUMNS["campaigns-with-stats"], "table", title="")
    console.print()

    if blob["flags"]:
        console.print("[bold red]Flags[/bold red]")
        for f in blob["flags"]:
            console.print(f"  • {f}")
        console.print()
    else:
        console.print("[green]No flags raised.[/green]\n")

    if json_out:
        with open(json_out, "w") as fh:
            json.dump(blob, fh, indent=2, default=str)
        console.print(f"[dim]Full audit JSON → {json_out}[/dim]")


def main():
    try:
        cli()
    except Exception as e:
        console.print(f"[red]error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
