"""sc — Click CLI entrypoint for Google Search Console."""
from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning, module="google.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")

import click
from rich.console import Console

from . import __version__
from . import pull as pull_mod
from .client import get_service, get_site_url
from .format import emit

console = Console()


@click.group(help="Personal Google Search Console CLI — organic queries, pages, devices.")
@click.version_option(__version__, prog_name="sc")
def cli() -> None:
    pass


def _date_opts(f):
    f = click.option("--since", default=None, help="ISO date YYYY-MM-DD (overrides --days).")(f)
    f = click.option("--days", default=30, type=int, help="Lookback window in days (default 30).")(f)
    return f


def _common_opts(f):
    f = click.option("--limit", default=100, type=int, help="Max rows (default 100, max 25000).")(f)
    f = click.option(
        "--format", "fmt", type=click.Choice(["table", "json"]), default="table",
        help="Output format.",
    )(f)
    f = click.option(
        "--type", "search_type",
        type=click.Choice(["web", "image", "video", "news", "discover", "googleNews"]),
        default="web", help="Search type (default web).",
    )(f)
    f = click.option(
        "--data-state", "data_state", type=click.Choice(["final", "all"]),
        default="final", help="`final` (3-day lag) or `all` (fresh, unfinalized).",
    )(f)
    return f


@cli.group("pull")
def pull_group() -> None:
    """Read commands — pull data from Search Console."""


def _run(name: str, func, days, since, limit, fmt, search_type, data_state, **extra):
    service = get_service()
    site = get_site_url()
    rows = func(service, site, days, since, limit,
                search_type=search_type, data_state=data_state, **extra)
    emit(rows, pull_mod.COLUMNS[name], fmt,
         title=f"{name} ({len(rows)}) — {site} [{search_type}/{data_state}]")


@pull_group.command("queries")
@_date_opts
@_common_opts
def queries_cmd(days, since, limit, fmt, search_type, data_state):
    _run("queries", pull_mod.pull_queries, days, since, limit, fmt, search_type, data_state)


@pull_group.command("pages")
@_date_opts
@_common_opts
def pages_cmd(days, since, limit, fmt, search_type, data_state):
    _run("pages", pull_mod.pull_pages, days, since, limit, fmt, search_type, data_state)


@pull_group.command("query-page")
@_date_opts
@_common_opts
def query_page_cmd(days, since, limit, fmt, search_type, data_state):
    _run("query-page", pull_mod.pull_query_page, days, since, limit, fmt, search_type, data_state)


@pull_group.command("countries")
@_date_opts
@_common_opts
def countries_cmd(days, since, limit, fmt, search_type, data_state):
    _run("countries", pull_mod.pull_countries, days, since, limit, fmt, search_type, data_state)


@pull_group.command("devices")
@_date_opts
@_common_opts
def devices_cmd(days, since, limit, fmt, search_type, data_state):
    _run("devices", pull_mod.pull_devices, days, since, limit, fmt, search_type, data_state)


@pull_group.command("search-appearance")
@_date_opts
@_common_opts
def search_appearance_cmd(days, since, limit, fmt, search_type, data_state):
    """SERP feature breakdown — Rich result, AMP, Web Light, etc."""
    _run("search-appearance", pull_mod.pull_search_appearance,
         days, since, limit, fmt, search_type, data_state)


@pull_group.command("timeseries")
@_date_opts
@_common_opts
@click.option("--group", "group", default="date",
              type=click.Choice(["date", "device", "country"]),
              help="`date` for pure timeseries, or `date` + one of device/country.")
def timeseries_cmd(days, since, limit, fmt, search_type, data_state, group):
    """Daily clicks/impressions/CTR/position trend — feeds WoW/MoM/YoY tiles."""
    name = "timeseries" if group == "date" else f"timeseries-{group}"
    service = get_service()
    site = get_site_url()
    rows = pull_mod.pull_timeseries(service, site, days, since, limit,
                                    search_type=search_type, data_state=data_state,
                                    group=group)
    emit(rows, pull_mod.COLUMNS[name], fmt,
         title=f"timeseries ({group}, {len(rows)}) — {site}")


@cli.command("inspect")
@click.argument("inspection_url")
@click.option("--language", default="en-US")
def inspect_cmd(inspection_url, language):
    """URL Inspection — indexation, mobile-usability, rich-results status for one URL."""
    import json as _json
    service = get_service()
    site = get_site_url()
    result = pull_mod.inspect_url(service, site, inspection_url, language_code=language)
    print(_json.dumps(result, indent=2, default=str))


@cli.command("sitemaps")
@click.option(
    "--format", "fmt", type=click.Choice(["table", "json"]), default="table",
)
def sitemaps_cmd(fmt):
    """List sitemaps + submission/download status + indexed counts."""
    service = get_service()
    site = get_site_url()
    rows = pull_mod.pull_sitemaps(service, site)
    emit(rows, pull_mod.COLUMNS["sitemaps"], fmt,
         title=f"Sitemaps ({len(rows)}) — {site}")


@cli.command("sitemap")
@click.argument("feedpath")
def sitemap_detail_cmd(feedpath):
    """Detail for a single submitted sitemap (errors, content types, indexed)."""
    import json as _json
    service = get_service()
    site = get_site_url()
    result = pull_mod.pull_sitemap_detail(service, site, feedpath)
    print(_json.dumps(result, indent=2, default=str))


@cli.command("sites")
def sites_cmd():
    """List verified properties accessible to the configured refresh token."""
    service = get_service()
    resp = service.sites().list().execute()
    entries = resp.get("siteEntry", [])
    if not entries:
        console.print("[yellow]No verified properties.[/yellow]")
        return
    rows = [
        {"siteUrl": e.get("siteUrl"), "permissionLevel": e.get("permissionLevel")}
        for e in entries
    ]
    emit(rows, ["siteUrl", "permissionLevel"], "table", title=f"Search Console properties ({len(rows)})")


def main():
    try:
        cli()
    except Exception as e:
        console.print(f"[red]error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
