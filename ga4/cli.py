"""ga4 — Click CLI entrypoint."""
from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning, module="google.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")

import click
from rich.console import Console

from . import __version__
from . import pull as pull_mod
from .client import get_admin_service, get_client, get_property_id
from .format import emit

console = Console()


@click.group(help="Personal GA4 Data API CLI — pull landing-page, channel, and event data.")
@click.version_option(__version__, prog_name="ga4")
def cli() -> None:
    pass


def _date_opts(f):
    f = click.option("--since", default=None, help="ISO date YYYY-MM-DD (overrides --days).")(f)
    f = click.option("--days", default=30, type=int, help="Lookback window in days (default 30).")(f)
    return f


def _common_opts(f):
    f = click.option("--limit", default=100, type=int, help="Max rows (default 100).")(f)
    f = click.option(
        "--format", "fmt", type=click.Choice(["table", "json"]), default="table",
        help="Output format.",
    )(f)
    return f


@cli.group("pull")
def pull_group() -> None:
    """Read commands — pull data from GA4."""


def _run(name: str, func, days, since, limit, fmt):
    client = get_client()
    pid = get_property_id()
    rows = func(client, pid, days, since, limit)
    emit(rows, pull_mod.COLUMNS[name], fmt, title=f"{name} ({len(rows)})")


@pull_group.command("landing-pages")
@_date_opts
@_common_opts
def landing_pages_cmd(days, since, limit, fmt):
    _run("landing-pages", pull_mod.pull_landing_pages, days, since, limit, fmt)


@pull_group.command("channels")
@_date_opts
@_common_opts
def channels_cmd(days, since, limit, fmt):
    _run("channels", pull_mod.pull_channels, days, since, limit, fmt)


@pull_group.command("source-medium")
@_date_opts
@_common_opts
def source_medium_cmd(days, since, limit, fmt):
    _run("source-medium", pull_mod.pull_source_medium, days, since, limit, fmt)


@pull_group.command("geo")
@_date_opts
@_common_opts
def geo_cmd(days, since, limit, fmt):
    _run("geo", pull_mod.pull_geo, days, since, limit, fmt)


@pull_group.command("devices")
@_date_opts
@_common_opts
def devices_cmd(days, since, limit, fmt):
    _run("devices", pull_mod.pull_devices, days, since, limit, fmt)


@pull_group.command("conversions-by-page")
@_date_opts
@_common_opts
def conversions_by_page_cmd(days, since, limit, fmt):
    _run("conversions-by-page", pull_mod.pull_conversions_by_page, days, since, limit, fmt)


@pull_group.command("events")
@_date_opts
@_common_opts
def events_cmd(days, since, limit, fmt):
    _run("events", pull_mod.pull_events, days, since, limit, fmt)


@pull_group.command("realtime")
@click.option("--limit", default=100, type=int)
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.option("--dim", "dims", multiple=True,
              help="Repeatable. Default: unifiedScreenName,country.")
@click.option("--metric", "metrics", multiple=True,
              help="Repeatable. Default: activeUsers,screenPageViews,eventCount.")
def realtime_cmd(limit, fmt, dims, metrics):
    """Realtime — events from the last 30 minutes."""
    client = get_client()
    pid = get_property_id()
    rows = pull_mod.pull_realtime(client, pid,
                                 dimensions=list(dims) or None,
                                 metrics=list(metrics) or None,
                                 limit=limit)
    cols = list(dims) + list(metrics) if (dims and metrics) else pull_mod.COLUMNS["realtime"]
    emit(rows, cols, fmt, title=f"Realtime ({len(rows)})")


@pull_group.command("pivot")
@_date_opts
@_common_opts
@click.option("--row-dim", required=True, help="Pivot row dimension (e.g. sessionSource).")
@click.option("--col-dim", required=True, help="Pivot column dimension (e.g. landingPage).")
@click.option("--metric", required=True, help="Metric to pivot on (e.g. conversions).")
def pivot_cmd(days, since, limit, fmt, row_dim, col_dim, metric):
    """2D pivot — row_dim × col_dim × metric."""
    client = get_client()
    pid = get_property_id()
    rows = pull_mod.pull_pivot(client, pid, row_dim, col_dim, metric, days, since, limit)
    emit(rows, [row_dim, col_dim, metric], fmt,
         title=f"Pivot {row_dim} × {col_dim} → {metric} ({len(rows)})")


@pull_group.command("funnel")
@_date_opts
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="json")
@click.option("--step", "steps", multiple=True, required=True,
              help="Repeatable: NAME=EVENT_NAME (e.g. landed=page_view login=user_signin).")
@click.option("--breakdown", default=None,
              help="Optional dimension to split the funnel by (e.g. deviceCategory).")
def funnel_cmd(days, since, fmt, steps, breakdown):
    """Funnel report (preview API)."""
    import json as _json
    client = get_client()
    pid = get_property_id()
    parsed = []
    for s in steps:
        if "=" not in s:
            raise click.ClickException(f"--step expects NAME=EVENT format, got {s!r}")
        name, event = s.split("=", 1)
        parsed.append({"name": name, "event": event})
    rows = pull_mod.pull_funnel(client, pid, parsed, days, since, dimension=breakdown)
    if fmt == "json":
        print(_json.dumps(rows, indent=2, default=str))
    else:
        cols = list(rows[0].keys()) if rows else []
        emit(rows, cols, "table", title=f"Funnel ({len(rows)})")


@pull_group.command("metadata")
@click.option("--kind", type=click.Choice(["dimensions", "metrics", "all"]), default="all")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
def metadata_cmd(kind, fmt):
    """Discover available dimensions + metrics (incl. custom)."""
    import json as _json
    client = get_client()
    pid = get_property_id()
    meta = pull_mod.get_metadata(client, pid)
    if kind == "all" and fmt == "json":
        print(_json.dumps(meta, indent=2, default=str))
        return
    if kind in ("dimensions", "all"):
        emit(meta["dimensions"], pull_mod.COLUMNS["metadata-dimensions"], fmt,
             title=f"Dimensions ({len(meta['dimensions'])})")
    if kind in ("metrics", "all"):
        emit(meta["metrics"], pull_mod.COLUMNS["metadata-metrics"], fmt,
             title=f"Metrics ({len(meta['metrics'])})")


@pull_group.command("compatibility")
@click.option("--dim", "dims", multiple=True, required=True,
              help="Repeatable: dimension api_name to check.")
@click.option("--metric", "metrics", multiple=True, required=True,
              help="Repeatable: metric api_name to check.")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
def compatibility_cmd(dims, metrics, fmt):
    """Check whether a set of dims+metrics can be queried together."""
    import json as _json
    client = get_client()
    pid = get_property_id()
    result = pull_mod.check_compatibility(client, pid, list(dims), list(metrics))
    if fmt == "json":
        print(_json.dumps(result, indent=2, default=str))
        return
    emit(result["dimension_compatibilities"], pull_mod.COLUMNS["compatibility"],
         "table", title="Dimensions")
    emit(result["metric_compatibilities"], pull_mod.COLUMNS["compatibility"],
         "table", title="Metrics")


# ─── audiences (Admin API) ───────────────────────────────────────────────────

@cli.group("audiences")
def audiences_group() -> None:
    """Audiences + audience-export snapshots."""


@audiences_group.command("list")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
def audiences_list_cmd(fmt):
    """List audiences defined on the property."""
    rows = pull_mod.list_audiences(get_admin_service(), get_property_id())
    emit(rows, pull_mod.COLUMNS["audiences"], fmt, title=f"Audiences ({len(rows)})")


@audiences_group.command("exports")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
def audience_exports_cmd(fmt):
    """List existing audience export snapshots."""
    rows = pull_mod.list_audience_exports(get_admin_service(), get_property_id())
    emit(rows, pull_mod.COLUMNS["audience-exports"], fmt,
         title=f"Audience exports ({len(rows)})")


@audiences_group.command("create-export")
@click.argument("audience_resource")
@click.option("--dim", "dims", multiple=True, default=("deviceId",),
              help="Dimensions to include in the export (default: deviceId).")
def create_audience_export_cmd(audience_resource, dims):
    """Kick off an audience export snapshot."""
    import json as _json
    result = pull_mod.create_audience_export(
        get_admin_service(), get_property_id(), audience_resource, dimensions=list(dims)
    )
    print(_json.dumps(result, indent=2, default=str))


# ─── BQ export config ────────────────────────────────────────────────────────

@cli.command("bq-exports")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
def bq_exports_cmd(fmt):
    """List BigQuery export links configured for the property."""
    rows = pull_mod.bq_export_settings(get_admin_service(), get_property_id())
    emit(rows, pull_mod.COLUMNS["bq-exports"], fmt,
         title=f"BigQuery exports ({len(rows)})")


# ─── key events (Admin API: mark events as conversions) ──────────────────────

@cli.group("key-events")
def key_events_group() -> None:
    """List + create GA4 key events (formerly known as conversion events)."""


@key_events_group.command("list")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
def key_events_list_cmd(fmt):
    """List currently-marked key events for the configured property."""
    rows = pull_mod.list_key_events(get_admin_service(), get_property_id())
    emit(rows, pull_mod.COLUMNS["key-events"], fmt, title=f"Key events ({len(rows)})")


@key_events_group.command("create")
@click.argument("event_name")
@click.option("--counting", type=click.Choice(["ONCE_PER_EVENT", "ONCE_PER_SESSION"]),
              default="ONCE_PER_EVENT", help="How to count: every fire, or once per session.")
def key_events_create_cmd(event_name, counting):
    """Mark an event name as a key event so it counts as a conversion in GA4."""
    result = pull_mod.create_key_event(get_admin_service(), get_property_id(),
                                       event_name=event_name, counting_method=counting)
    console.print(f"[green]✓[/green] Created key event: {result['event_name']} (counting={result['counting_method']})")


def main():
    try:
        cli()
    except Exception as e:
        console.print(f"[red]error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
