"""lsa — Click CLI for Google Local Services Ads."""
from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning, module="google.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")

import click
from rich.console import Console

from . import __version__
from . import pull as pull_mod
from .client import get_service, get_account_id
from .format import emit

console = Console()


@click.group(help="Google Local Services Ads CLI — account reports + detailed leads.")
@click.version_option(__version__, prog_name="lsa")
def cli() -> None:
    pass


def _fmt(f):
    return click.option(
        "--format", "fmt", type=click.Choice(["table", "json"]), default="table",
    )(f)


@cli.group("pull")
def pull_group() -> None:
    """Read commands — pull data from Local Services Ads."""


@pull_group.command("account")
@click.option("--customer", default=None, help="LSA customer ID. Defaults to lsa_customer_id or customer_id from yaml.")
@click.option("--days", default=30, type=int, help="Lookback days (default 30).")
@_fmt
def account_cmd(customer, days, fmt):
    """Account-level LSA performance — daily totals for leads, calls, ratings."""
    svc = get_service()
    cid = customer or get_account_id()
    if not cid:
        raise click.ClickException("No customer ID. Pass --customer XXXX or add lsa_customer_id to yaml.")
    rows = pull_mod.pull_account_reports(svc, cid, days)
    emit(rows, pull_mod.COLUMNS["account"], fmt, title=f"LSA account reports ({days}d) — {cid}")


@pull_group.command("leads")
@click.option("--customer", default=None, help="LSA customer ID. Defaults to lsa_customer_id or customer_id from yaml.")
@click.option("--days", default=30, type=int, help="Lookback days (default 30).")
@_fmt
def leads_cmd(customer, days, fmt):
    """Lead-level LSA report — every individual lead with type, price, dispute status."""
    svc = get_service()
    cid = customer or get_account_id()
    if not cid:
        raise click.ClickException("No customer ID. Pass --customer XXXX or add lsa_customer_id to yaml.")
    rows = pull_mod.pull_detailed_leads(svc, cid, days)
    emit(rows, pull_mod.COLUMNS["leads"], fmt, title=f"LSA detailed leads ({days}d) — {cid}")


def main():
    try:
        cli()
    except Exception as e:
        console.print(f"[red]error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
