"""fb — Click CLI entrypoint for Meta (Facebook) Marketing API + Pixel."""
from __future__ import annotations

import json as _json
import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning, module="google.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")

import click
from rich.console import Console

from . import __version__
from . import pull as pull_mod
from .client import get_ad_account_id, get_pixel_id, init_api
from .format import emit

_LEVELS = click.Choice(["account", "campaign", "adset", "ad"])
_TIME_INC = click.Choice(["1", "7", "monthly", "all_days"])

console = Console()


@click.group(help="Personal Meta (Facebook) Marketing API + Pixel CLI.")
@click.version_option(__version__, prog_name="fb")
def cli() -> None:
    pass


def _date_opts(f):
    f = click.option("--since", default=None, help="ISO date YYYY-MM-DD (overrides --days).")(f)
    f = click.option("--days", default=30, type=int, help="Lookback window in days (default 30).")(f)
    return f


def _format_opt(f):
    return click.option(
        "--format", "fmt", type=click.Choice(["table", "json"]), default="table",
        help="Output format.",
    )(f)


# ─── connectivity / discovery ─────────────────────────────────────────────────

@cli.command("whoami")
def whoami_cmd():
    """Verify the access token works and show identity."""
    init_api()
    info = pull_mod.whoami()
    console.print(info)


@cli.command("ad-accounts")
@_format_opt
def ad_accounts_cmd(fmt):
    """List ad accounts the configured token can see."""
    init_api()
    rows = pull_mod.list_ad_accounts()
    emit(rows, pull_mod.COLUMNS["ad-accounts"], fmt, title=f"Ad accounts ({len(rows)})")


@cli.command("account-info")
@click.option("--account", "ad_account_id", default=None)
def account_info_cmd(ad_account_id):
    """Account balance, spend cap, status, currency, country."""
    init_api()
    aid = ad_account_id or get_ad_account_id()
    info = pull_mod.pull_account_info(aid)
    print(_json.dumps(info, indent=2, default=str))


# ─── pull ─────────────────────────────────────────────────────────────────────

@cli.group("pull")
def pull_group() -> None:
    """Read commands — campaigns, ads, pixel events."""


@pull_group.command("campaigns")
@_date_opts
@_format_opt
@click.option("--account", "ad_account_id", default=None,
              help="Override ad account (default: fb_ad_account_id from yaml).")
def pull_campaigns_cmd(days, since, fmt, ad_account_id):
    """Campaign-level performance + lead/purchase action counts."""
    init_api()
    aid = ad_account_id or get_ad_account_id()
    rows = pull_mod.pull_campaigns(aid, days, since)
    emit(rows, pull_mod.COLUMNS["campaigns"], fmt, title=f"Campaigns ({len(rows)}) — {aid}")


@pull_group.command("pixel-info")
@click.option("--pixel", "pixel_id", default=None,
              help="Override pixel ID (default: fb_pixel_id from yaml).")
def pull_pixel_info_cmd(pixel_id):
    """Pixel config: ID, last_fired_time, automatic-matching fields, etc."""
    init_api()
    pid = pixel_id or get_pixel_id()
    info = pull_mod.pull_pixel_info(pid)
    print(_json.dumps(info, indent=2, default=str))


@pull_group.command("pixel-events")
@_date_opts
@_format_opt
@click.option("--pixel", "pixel_id", default=None)
def pull_pixel_events_cmd(days, since, fmt, pixel_id):
    """Recent events received by the pixel, grouped by event_name."""
    init_api()
    pid = pixel_id or get_pixel_id()
    rows = pull_mod.pull_pixel_events(pid, days, since)
    emit(rows, pull_mod.COLUMNS["pixel-events"], fmt, title=f"Pixel events ({len(rows)}) — {pid}")


@pull_group.command("pixel-event-quality")
@_date_opts
@_format_opt
@click.option("--pixel", "pixel_id", default=None)
def pull_pixel_event_quality_cmd(days, since, fmt, pixel_id):
    """CAPI / Pixel event-quality — match rate + EMQ score per event."""
    init_api()
    pid = pixel_id or get_pixel_id()
    rows = pull_mod.pull_pixel_event_quality(pid, days, since)
    emit(rows, pull_mod.COLUMNS["pixel-event-quality"], fmt,
         title=f"Event quality ({len(rows)}) — {pid}")


@pull_group.command("adsets")
@_date_opts
@_format_opt
@click.option("--account", "ad_account_id", default=None)
def pull_adsets_cmd(days, since, fmt, ad_account_id):
    """Adset-level performance."""
    init_api()
    aid = ad_account_id or get_ad_account_id()
    rows = pull_mod.pull_adsets(aid, days, since)
    emit(rows, pull_mod.COLUMNS["adsets"], fmt, title=f"Adsets ({len(rows)}) — {aid}")


@pull_group.command("ads")
@_date_opts
@_format_opt
@click.option("--account", "ad_account_id", default=None)
def pull_ads_cmd(days, since, fmt, ad_account_id):
    """Ad-level performance — creative-fatigue drilldown."""
    init_api()
    aid = ad_account_id or get_ad_account_id()
    rows = pull_mod.pull_ads(aid, days, since)
    emit(rows, pull_mod.COLUMNS["ads"], fmt, title=f"Ads ({len(rows)}) — {aid}")


@pull_group.command("breakdown")
@_date_opts
@_format_opt
@click.option("--breakdown", required=True,
              help="age, gender, age_gender, country, region, dma, "
                   "impression_device, publisher_platform, platform_position, "
                   "device_platform, product_id, "
                   "hourly_stats_aggregated_by_advertiser_time_zone")
@click.option("--level", type=_LEVELS, default="account")
@click.option("--account", "ad_account_id", default=None)
def pull_breakdown_cmd(days, since, fmt, breakdown, level, ad_account_id):
    """Insights split by a breakdown dimension (placement, demo, geo, device)."""
    init_api()
    aid = ad_account_id or get_ad_account_id()
    rows = pull_mod.pull_breakdown(aid, breakdown, days, since, level=level)
    cols = pull_mod.breakdown_columns(breakdown, level=level)
    emit(rows, cols, fmt, title=f"Breakdown {breakdown} @ {level} ({len(rows)}) — {aid}")


@pull_group.command("time-series")
@_date_opts
@_format_opt
@click.option("--level", type=_LEVELS, default="account")
@click.option("--interval", type=_TIME_INC, default="1",
              help="1=daily, 7=weekly, monthly, all_days.")
@click.option("--account", "ad_account_id", default=None)
def pull_time_series_cmd(days, since, fmt, level, interval, ad_account_id):
    """Daily/weekly/monthly insights for trend tiles."""
    init_api()
    aid = ad_account_id or get_ad_account_id()
    inc = int(interval) if interval.isdigit() else interval
    rows = pull_mod.pull_time_series(aid, days, since, level=level, time_increment=inc)
    emit(rows, pull_mod.COLUMNS["time-series"], fmt,
         title=f"Time series ({interval}, {len(rows)}) — {aid}")


@pull_group.command("custom-audiences")
@_format_opt
@click.option("--account", "ad_account_id", default=None)
def pull_custom_audiences_cmd(fmt, ad_account_id):
    """List Custom Audiences with sizes + delivery status."""
    init_api()
    aid = ad_account_id or get_ad_account_id()
    rows = pull_mod.list_custom_audiences(aid)
    emit(rows, pull_mod.COLUMNS["custom-audiences"], fmt,
         title=f"Custom audiences ({len(rows)}) — {aid}")


@pull_group.command("lead-forms")
@_format_opt
@click.option("--page", "page_id", required=True, help="Facebook Page ID.")
def pull_lead_forms_cmd(fmt, page_id):
    """List Lead Ad forms on a Page."""
    init_api()
    rows = pull_mod.list_lead_forms(page_id)
    emit(rows, pull_mod.COLUMNS["lead-forms"], fmt,
         title=f"Lead forms ({len(rows)}) — page {page_id}")


@pull_group.command("lead-form-leads")
@_date_opts
@_format_opt
@click.option("--form", "form_id", required=True)
def pull_lead_form_leads_cmd(days, since, fmt, form_id):
    """Pull leads submitted via a Lead Ad form."""
    init_api()
    rows = pull_mod.pull_lead_form_leads(form_id, days, since)
    emit(rows, pull_mod.COLUMNS["lead-form-leads"], fmt,
         title=f"Leads ({len(rows)}) — form {form_id}")


@pull_group.command("ad-creative")
@click.option("--ad", "ad_id", required=True)
def pull_ad_creative_cmd(ad_id):
    """Pull copy + CTA + preview URL for a single ad."""
    init_api()
    info = pull_mod.pull_ad_creative(ad_id)
    print(_json.dumps(info, indent=2, default=str))


def main():
    try:
        cli()
    except Exception as e:
        console.print(f"[red]error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
