"""gbp — Click CLI for Google Business Profile."""
from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning, module="google.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")

import json

import click
from rich.console import Console

from . import __version__
from . import pull as pull_mod
from .client import get_service, get_account_id, get_location_id
from .format import emit

console = Console()


@click.group(help="Personal Google Business Profile CLI — accounts, locations, performance, Q&A.")
@click.version_option(__version__, prog_name="gbp")
def cli() -> None:
    pass


@cli.group("pull")
def pull_group() -> None:
    """Read commands — pull data from Google Business Profile."""


def _fmt_opt(f):
    return click.option(
        "--format", "fmt", type=click.Choice(["table", "json"]), default="table",
        help="Output format.",
    )(f)


@pull_group.command("accounts")
@_fmt_opt
def accounts_cmd(fmt):
    """List GBP accounts the configured token can access."""
    svc = get_service("account")
    rows = pull_mod.pull_accounts(svc)
    emit(rows, pull_mod.COLUMNS["accounts"], fmt, title=f"GBP accounts ({len(rows)})")


@pull_group.command("locations")
@click.option("--account", default=None,
              help="Account name (accounts/XXX). Defaults to gbp_account_id from yaml.")
@_fmt_opt
def locations_cmd(account, fmt):
    """List locations under an account."""
    svc = get_service("info")
    acct = account or get_account_id()
    if not acct:
        raise click.ClickException(
            "No account specified. Pass --account accounts/XXX or "
            "add gbp_account_id to google-ads.yaml."
        )
    rows = pull_mod.pull_locations(svc, acct)
    emit(rows, pull_mod.COLUMNS["locations"], fmt, title=f"Locations under {acct} ({len(rows)})")


@pull_group.command("location")
@click.option("--name", default=None,
              help="Full location name (locations/XXX). Defaults to gbp_location_id.")
@click.option("--mask", default="*",
              help="Comma-separated readMask. Default '*' = all fields.")
def location_cmd(name, mask):
    """Get full detail for one location (always JSON — too many fields for a table)."""
    svc = get_service("info")
    loc = name or get_location_id()
    if not loc:
        raise click.ClickException(
            "No location specified. Pass --name locations/XXX or "
            "add gbp_location_id to google-ads.yaml."
        )
    detail = pull_mod.pull_location_detail(svc, loc, mask)
    click.echo(json.dumps(detail, indent=2))


@pull_group.command("performance")
@click.option("--location", default=None,
              help="Location name (locations/XXX). Defaults to gbp_location_id.")
@click.option("--days", default=30, type=int,
              help="Lookback days (default 30, max 540 per API limits).")
@_fmt_opt
def performance_cmd(location, days, fmt):
    """Daily performance metrics — Search/Maps impressions, calls, directions, website clicks."""
    perf = get_service("performance")
    loc = location or get_location_id()
    if not loc:
        raise click.ClickException(
            "No location specified. Pass --location locations/XXX or "
            "add gbp_location_id to google-ads.yaml."
        )
    rows = pull_mod.pull_performance(perf, loc, days)
    emit(rows, pull_mod.COLUMNS["performance"], fmt, title=f"Performance ({days}d) — {loc}")


@pull_group.command("qna")
@click.option("--location", default=None,
              help="Location name (locations/XXX). Defaults to gbp_location_id.")
@_fmt_opt
def qna_cmd(location, fmt):
    """List Q&A for a location."""
    svc = get_service("qa")
    loc = location or get_location_id()
    if not loc:
        raise click.ClickException(
            "No location specified. Pass --location locations/XXX or "
            "add gbp_location_id to google-ads.yaml."
        )
    rows = pull_mod.pull_qna(svc, loc)
    emit(rows, pull_mod.COLUMNS["qna"], fmt, title=f"Q&A ({len(rows)}) — {loc}")


@pull_group.command("categories")
@click.option("--region", default="US", help="Region code (default US).")
@click.option("--language", default="en", help="Language code (default en).")
@_fmt_opt
def categories_cmd(region, language, fmt):
    """List GBP business categories — search for the right primaryCategory by displayName."""
    svc = get_service("info")
    rows = pull_mod.pull_categories(svc, region, language)
    emit(rows, pull_mod.COLUMNS["categories"], fmt, title=f"GBP categories ({len(rows)})")


@pull_group.command("search-keywords")
@click.option("--location", default=None,
              help="Location name (locations/XXX). Defaults to gbp_location_id.")
@click.option("--months", default=3, type=int, help="Months back (default 3).")
@_fmt_opt
def search_keywords_cmd(location, months, fmt):
    """Search keywords driving GBP impressions over the last N months."""
    perf = get_service("performance")
    loc = location or get_location_id()
    if not loc:
        raise click.ClickException("No location specified.")
    rows = pull_mod.pull_search_keywords(perf, loc, months_back=months)
    emit(rows, pull_mod.COLUMNS["search-keywords"], fmt,
         title=f"Search keywords ({months}mo, {len(rows)}) — {loc}")


@pull_group.command("reviews")
@click.option("--account", default=None,
              help="Account ID or accounts/XXX. Defaults to gbp_account_id.")
@click.option("--location", default=None,
              help="Location ID or locations/XXX. Defaults to gbp_location_id.")
@_fmt_opt
def reviews_cmd(account, location, fmt):
    """List reviews for the location (legacy v4 — requires allowlist)."""
    acct = account or get_account_id()
    loc = location or get_location_id()
    if not acct or not loc:
        raise click.ClickException("Need both gbp_account_id and gbp_location_id.")
    rows = pull_mod.pull_reviews(acct, loc)
    emit(rows, pull_mod.COLUMNS["reviews"], fmt, title=f"Reviews ({len(rows)}) — {loc}")


@pull_group.command("local-posts")
@click.option("--account", default=None)
@click.option("--location", default=None)
@_fmt_opt
def local_posts_cmd(account, location, fmt):
    """List Local Posts on the profile (legacy v4 — requires allowlist)."""
    acct = account or get_account_id()
    loc = location or get_location_id()
    if not acct or not loc:
        raise click.ClickException("Need both gbp_account_id and gbp_location_id.")
    rows = pull_mod.pull_local_posts(acct, loc)
    emit(rows, pull_mod.COLUMNS["local-posts"], fmt,
         title=f"Local posts ({len(rows)}) — {loc}")


@pull_group.command("media")
@click.option("--account", default=None)
@click.option("--location", default=None)
@_fmt_opt
def media_cmd(account, location, fmt):
    """List media (photos/videos) for the location (legacy v4 — requires allowlist)."""
    acct = account or get_account_id()
    loc = location or get_location_id()
    if not acct or not loc:
        raise click.ClickException("Need both gbp_account_id and gbp_location_id.")
    rows = pull_mod.pull_media(acct, loc)
    emit(rows, pull_mod.COLUMNS["media"], fmt, title=f"Media ({len(rows)}) — {loc}")


@pull_group.command("attributes")
@click.option("--location", default=None)
@_fmt_opt
def attributes_cmd(location, fmt):
    """List attributes set on the location."""
    svc = get_service("info")
    loc = location or get_location_id()
    if not loc:
        raise click.ClickException("No location specified.")
    rows = pull_mod.pull_attributes(svc, loc)
    emit(rows, pull_mod.COLUMNS["attributes"], fmt,
         title=f"Attributes ({len(rows)}) — {loc}")


@pull_group.command("verifications")
@click.option("--location", default=None)
@_fmt_opt
def verifications_cmd(location, fmt):
    """List verification history + expiry for the location."""
    svc = get_service("verifications")
    loc = location or get_location_id()
    if not loc:
        raise click.ClickException("No location specified.")
    rows = pull_mod.pull_verifications(svc, loc)
    emit(rows, pull_mod.COLUMNS["verifications"], fmt,
         title=f"Verifications ({len(rows)}) — {loc}")


def main():
    try:
        cli()
    except Exception as e:
        console.print(f"[red]error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
