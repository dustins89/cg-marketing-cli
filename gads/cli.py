"""gads — Click CLI entrypoint."""
from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning, module="google.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")

import click
from rich.console import Console

from . import __version__
from . import auth as auth_mod
from . import pull as pull_mod
from . import apply as apply_mod
from .client import get_client, get_customer_id
from .format import emit

console = Console()


@click.group(help="Personal Google Ads CLI — pull data, suggest changes, apply with confirmation.")
@click.version_option(__version__, prog_name="gads")
def cli() -> None:
    pass


# ─── auth ─────────────────────────────────────────────────────────────────────
@cli.group()
def auth() -> None:
    """Manage Google Ads API credentials."""


@auth.command("init")
def auth_init() -> None:
    """Run the OAuth flow and write google-ads.yaml."""
    auth_mod.init_auth()


@cli.command()
def whoami() -> None:
    """List customer IDs accessible to the configured refresh token."""
    auth_mod.whoami()


# ─── pull ─────────────────────────────────────────────────────────────────────
def _date_opts(f):
    f = click.option("--since", default=None, help="ISO date YYYY-MM-DD (overrides --days).")(f)
    f = click.option("--days", default=30, type=int, help="Lookback window in days (default 30).")(f)
    return f


def _format_opt(f):
    return click.option(
        "--format", "fmt", type=click.Choice(["table", "json"]), default="table",
        help="Output format.",
    )(f)


@cli.group("pull")
def pull_group() -> None:
    """Read commands — pull data from Google Ads."""


@pull_group.command("campaigns")
@_date_opts
@_format_opt
def pull_campaigns_cmd(days, since, fmt):
    client = get_client()
    cid = get_customer_id()
    rows = pull_mod.pull_campaigns(client, cid, days, since)
    emit(rows, pull_mod.COLUMNS["campaigns"], fmt, title=f"Campaigns ({len(rows)})")


@pull_group.command("adgroups")
@_date_opts
@_format_opt
def pull_adgroups_cmd(days, since, fmt):
    client = get_client()
    cid = get_customer_id()
    rows = pull_mod.pull_adgroups(client, cid, days, since)
    emit(rows, pull_mod.COLUMNS["adgroups"], fmt, title=f"Ad groups ({len(rows)})")


@pull_group.command("keywords")
@_date_opts
@_format_opt
def pull_keywords_cmd(days, since, fmt):
    client = get_client()
    cid = get_customer_id()
    rows = pull_mod.pull_keywords(client, cid, days, since)
    emit(rows, pull_mod.COLUMNS["keywords"], fmt, title=f"Keywords ({len(rows)})")


@pull_group.command("search-terms")
@_date_opts
@_format_opt
def pull_search_terms_cmd(days, since, fmt):
    client = get_client()
    cid = get_customer_id()
    rows = pull_mod.pull_search_terms(client, cid, days, since)
    emit(rows, pull_mod.COLUMNS["search_terms"], fmt, title=f"Search terms ({len(rows)})")


@pull_group.command("negatives")
@_format_opt
def pull_negatives_cmd(fmt):
    client = get_client()
    cid = get_customer_id()
    rows = pull_mod.pull_negatives(client, cid)
    emit(rows, pull_mod.COLUMNS["negatives"], fmt, title=f"Existing negatives ({len(rows)})")


@pull_group.command("ads")
@_date_opts
@_format_opt
def pull_ads_cmd(days, since, fmt):
    client = get_client()
    cid = get_customer_id()
    rows = pull_mod.pull_ads(client, cid, days, since)
    emit(rows, pull_mod.COLUMNS["ads"], fmt, title=f"Ads ({len(rows)})")


@pull_group.command("conversions")
@_date_opts
@_format_opt
def pull_conversions_cmd(days, since, fmt):
    client = get_client()
    cid = get_customer_id()
    rows = pull_mod.pull_conversions(client, cid, days, since)
    emit(rows, pull_mod.COLUMNS["conversions"], fmt, title=f"Conversions ({len(rows)})")


@pull_group.command("geo")
@_date_opts
@_format_opt
def pull_geo_cmd(days, since, fmt):
    """Geographic performance (country/region)."""
    rows = pull_mod.pull_geo(get_client(), get_customer_id(), days, since)
    emit(rows, pull_mod.COLUMNS["geo"], fmt, title=f"Geo ({len(rows)})")


@pull_group.command("age")
@_date_opts
@_format_opt
def pull_age_cmd(days, since, fmt):
    """Age-range performance."""
    rows = pull_mod.pull_age(get_client(), get_customer_id(), days, since)
    emit(rows, pull_mod.COLUMNS["age"], fmt, title=f"Age ({len(rows)})")


@pull_group.command("gender")
@_date_opts
@_format_opt
def pull_gender_cmd(days, since, fmt):
    """Gender performance."""
    rows = pull_mod.pull_gender(get_client(), get_customer_id(), days, since)
    emit(rows, pull_mod.COLUMNS["gender"], fmt, title=f"Gender ({len(rows)})")


@pull_group.command("device")
@_date_opts
@_format_opt
def pull_device_cmd(days, since, fmt):
    """Performance segmented by device (mobile/desktop/tablet)."""
    rows = pull_mod.pull_device(get_client(), get_customer_id(), days, since)
    emit(rows, pull_mod.COLUMNS["device"], fmt, title=f"Device ({len(rows)})")


@pull_group.command("user-lists")
@_format_opt
def pull_user_lists_cmd(fmt):
    """Customer Match + remarketing lists with sizes + match rate."""
    rows = pull_mod.pull_user_lists(get_client(), get_customer_id())
    emit(rows, pull_mod.COLUMNS["user-lists"], fmt, title=f"User lists ({len(rows)})")


@pull_group.command("recommendations")
@_format_opt
def pull_recommendations_cmd(fmt):
    """Pending Google Ads recommendations."""
    rows = pull_mod.pull_recommendations(get_client(), get_customer_id())
    emit(rows, pull_mod.COLUMNS["recommendations"], fmt,
         title=f"Recommendations ({len(rows)})")


@pull_group.command("change-history")
@_date_opts
@_format_opt
def pull_change_history_cmd(days, since, fmt):
    """Audit log of changes (last 90 days max via change_event)."""
    rows = pull_mod.pull_change_history(get_client(), get_customer_id(), days, since)
    emit(rows, pull_mod.COLUMNS["change-history"], fmt,
         title=f"Change history ({len(rows)})")


@pull_group.command("ad-strength")
@_date_opts
@_format_opt
def pull_ad_strength_cmd(days, since, fmt):
    """RSA ad strength + approval status per ad."""
    rows = pull_mod.pull_ad_strength(get_client(), get_customer_id(), days, since)
    emit(rows, pull_mod.COLUMNS["ad-strength"], fmt,
         title=f"Ad strength ({len(rows)})")


@pull_group.command("assets")
@_date_opts
@_format_opt
def pull_assets_cmd(days, since, fmt):
    """Asset-level performance (RSA + Performance Max)."""
    rows = pull_mod.pull_assets(get_client(), get_customer_id(), days, since)
    emit(rows, pull_mod.COLUMNS["assets"], fmt, title=f"Assets ({len(rows)})")


@pull_group.command("asset-groups")
@_date_opts
@_format_opt
def pull_asset_groups_cmd(days, since, fmt):
    """Asset Group (Performance Max) performance."""
    rows = pull_mod.pull_asset_groups(get_client(), get_customer_id(), days, since)
    emit(rows, pull_mod.COLUMNS["asset-groups"], fmt,
         title=f"Asset groups ({len(rows)})")


@pull_group.command("qs-history")
@_date_opts
@_format_opt
def pull_qs_history_cmd(days, since, fmt):
    """Daily Quality Score per keyword."""
    rows = pull_mod.pull_keyword_qs_history(get_client(), get_customer_id(), days, since)
    emit(rows, pull_mod.COLUMNS["qs-history"], fmt,
         title=f"QS history ({len(rows)})")


@pull_group.command("conversion-actions")
@_format_opt
def pull_conversion_actions_cmd(fmt):
    """Conversion action config — lookback windows, attribution model."""
    rows = pull_mod.pull_conversion_actions(get_client(), get_customer_id())
    emit(rows, pull_mod.COLUMNS["conversion-actions"], fmt,
         title=f"Conversion actions ({len(rows)})")


@pull_group.command("budget-pacing")
@_date_opts
@_format_opt
def pull_budget_pacing_cmd(days, since, fmt):
    """Daily-budget vs window spend with pace target + pace %."""
    rows = pull_mod.pull_budget_pacing(get_client(), get_customer_id(), days, since)
    emit(rows, pull_mod.COLUMNS["budget-pacing"], fmt,
         title=f"Budget pacing ({len(rows)})")


# ─── apply ────────────────────────────────────────────────────────────────────
@cli.command("apply")
@click.argument("changes_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--dry-run", is_flag=True, help="Print intended mutations without executing.")
@click.option("--yes", "assume_yes", is_flag=True, help="Skip per-change confirmation (use with care).")
def apply_cmd(changes_file, dry_run, assume_yes):
    """Apply changes from a pending-changes YAML file."""
    client = get_client()
    apply_mod.apply_file(client, changes_file, dry_run=dry_run, assume_yes=assume_yes)


def main():
    try:
        cli()
    except Exception as e:
        console.print(f"[red]error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
