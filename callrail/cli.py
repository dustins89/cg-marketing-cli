"""callrail — Click CLI entrypoint for the CallRail v3 API."""
from __future__ import annotations

import sys

import click
from rich.console import Console

from . import __version__
from . import pull as pull_mod
from .client import resolve_account_id
from .format import emit

console = Console()


@click.group(help="Personal CallRail v3 API CLI.")
@click.version_option(__version__, prog_name="callrail")
def cli() -> None:
    pass


# ─── option decorators ───────────────────────────────────────────────────────

def _date_opts(f):
    f = click.option("--since", default=None, help="ISO date YYYY-MM-DD (overrides --days).")(f)
    f = click.option("--days", default=30, type=int, help="Lookback window in days (default 30).")(f)
    return f


def _format_opt(f):
    return click.option(
        "--format", "fmt", type=click.Choice(["table", "json"]), default="table",
        help="Output format.",
    )(f)


def _account_opt(f):
    return click.option(
        "--account", "account_id", default=None,
        help="Override CallRail account_id (default: callrail_account_id in yaml, "
             "else first account the key sees).",
    )(f)


def _filter_opts(f):
    """Shared filters for /calls, /summary, /timeseries."""
    f = click.option("--direction", type=click.Choice(["inbound", "outbound", "all"]),
                     default=None, help="Filter call direction.")(f)
    f = click.option("--lead-status",
                     type=click.Choice(["good_lead", "not_a_lead", "not_scored"]),
                     default=None)(f)
    f = click.option("--answer-status",
                     type=click.Choice(["answered", "missed", "voicemail", "all"]),
                     default=None)(f)
    f = click.option("--device", type=click.Choice(["desktop", "mobile", "all"]),
                     default=None)(f)
    f = click.option("--tracker-id", default=None, help="Filter to a single tracking number.")(f)
    f = click.option("--company-id", default=None, help="Filter to a single company.")(f)
    f = click.option("--tag", "tags", multiple=True,
                     help="Repeatable: --tag foo --tag bar.")(f)
    f = click.option("--first-time-callers/--no-first-time-callers", default=None)(f)
    return f


def _collect_filters(**kwargs) -> dict:
    """Pack CLI kwargs into the dict pull_* funcs expect, dropping empties."""
    tags = list(kwargs.get("tags") or []) or None
    return {
        "direction": kwargs.get("direction"),
        "lead_status": kwargs.get("lead_status"),
        "answer_status": kwargs.get("answer_status"),
        "device": kwargs.get("device"),
        "tracker_id": kwargs.get("tracker_id"),
        "company_id": kwargs.get("company_id"),
        "tags": tags,
        "first_time_callers": kwargs.get("first_time_callers"),
    }


# ─── discovery commands ──────────────────────────────────────────────────────

@cli.command("accounts")
@_format_opt
def accounts_cmd(fmt):
    """List CallRail accounts the configured API key can see."""
    rows = pull_mod.pull_accounts()
    emit(rows, pull_mod.COLUMNS["accounts"], fmt, title=f"CallRail accounts ({len(rows)})")


@cli.command("companies")
@_account_opt
@_format_opt
def companies_cmd(account_id, fmt):
    """List companies in the account."""
    aid = resolve_account_id(account_id)
    rows = pull_mod.pull_companies(aid)
    emit(rows, pull_mod.COLUMNS["companies"], fmt, title=f"Companies ({len(rows)}) — {aid}")


@cli.command("trackers")
@_account_opt
@_format_opt
def trackers_cmd(account_id, fmt):
    """List tracking numbers (active + disabled)."""
    aid = resolve_account_id(account_id)
    rows = pull_mod.pull_trackers(aid)
    emit(rows, pull_mod.COLUMNS["trackers"], fmt, title=f"Trackers ({len(rows)}) — {aid}")


@cli.command("users")
@_account_opt
@_format_opt
def users_cmd(account_id, fmt):
    """List users with access to the account."""
    aid = resolve_account_id(account_id)
    rows = pull_mod.pull_users(aid)
    emit(rows, pull_mod.COLUMNS["users"], fmt, title=f"Users ({len(rows)}) — {aid}")


@cli.command("tags")
@_account_opt
@_format_opt
def tags_cmd(account_id, fmt):
    """List tags configured in the account."""
    aid = resolve_account_id(account_id)
    rows = pull_mod.pull_tags(aid)
    emit(rows, pull_mod.COLUMNS["tags"], fmt, title=f"Tags ({len(rows)}) — {aid}")


# ─── raw calls + forms ───────────────────────────────────────────────────────

@cli.command("calls")
@_date_opts
@_account_opt
@_filter_opts
@_format_opt
def calls_cmd(days, since, account_id, fmt, **filters):
    """Raw calls in the window (sorted newest first)."""
    aid = resolve_account_id(account_id)
    rows = pull_mod.pull_calls(aid, days, since, **_collect_filters(**filters))
    emit(rows, pull_mod.COLUMNS["calls"], fmt, title=f"Calls ({len(rows)}) — {aid}")


@cli.command("forms")
@_date_opts
@_account_opt
@_format_opt
def forms_cmd(days, since, account_id, fmt):
    """CallRail-tracked web form submissions."""
    aid = resolve_account_id(account_id)
    rows = pull_mod.pull_form_submissions(aid, days, since)
    emit(rows, pull_mod.COLUMNS["forms"], fmt, title=f"Form submissions ({len(rows)}) — {aid}")


# ─── server-side aggregations ────────────────────────────────────────────────

@cli.command("summary")
@_date_opts
@_account_opt
@_filter_opts
@_format_opt
def summary_cmd(days, since, account_id, fmt, **filters):
    """Rollup tile (server-side): total/answered/missed/first-time/leads/avg-duration."""
    aid = resolve_account_id(account_id)
    rows = pull_mod.pull_summary(aid, days, since, **_collect_filters(**filters))
    emit(rows, pull_mod.COLUMNS["summary"], fmt, title=f"Summary — {aid}")


def _grouped_cmd(group_by_key: str, help_text: str):
    """Factory for the by-* subcommands. All hit /calls/summary?group_by=X."""

    @_date_opts
    @_account_opt
    @_filter_opts
    @_format_opt
    def _cmd(days, since, account_id, fmt, **filters):
        aid = resolve_account_id(account_id)
        rows = pull_mod.pull_grouped(aid, group_by_key, days, since,
                                     **_collect_filters(**filters))
        cols = [group_by_key] + pull_mod.COLUMNS["grouped"]
        emit(rows, cols, fmt, title=f"By {group_by_key} ({len(rows)}) — {aid}")

    _cmd.__doc__ = help_text
    return _cmd


cli.command(f"by-source")(_grouped_cmd("source", "Calls grouped by CallRail source (last-touch)."))
cli.command(f"by-campaign")(_grouped_cmd("campaign", "Calls grouped by campaign name."))
cli.command(f"by-keywords")(_grouped_cmd("keywords", "Calls grouped by paid keyword."))
cli.command(f"by-referrer")(_grouped_cmd("referrer", "Calls grouped by referrer domain."))
cli.command(f"by-landing-page")(_grouped_cmd("landing_page", "Calls grouped by landing page URL."))
cli.command(f"by-company")(_grouped_cmd("company", "Calls grouped by company."))


@cli.command("by-number")
@_date_opts
@_account_opt
@_filter_opts
@_format_opt
def by_number_cmd(days, since, account_id, fmt, **filters):
    """Calls grouped by tracking number (client-side over raw /calls)."""
    aid = resolve_account_id(account_id)
    rows = pull_mod.pull_by_number(aid, days, since, **_collect_filters(**filters))
    emit(rows, pull_mod.COLUMNS["by-number"], fmt,
         title=f"By tracking number ({len(rows)}) — {aid}")


@cli.command("timeseries")
@_date_opts
@_account_opt
@_filter_opts
@_format_opt
@click.option("--interval", type=click.Choice(["hour", "day", "week", "month", "year"]),
              default="day", help="Aggregation interval (default day). Max 200 data points.")
def timeseries_cmd(days, since, account_id, fmt, interval, **filters):
    """Time-series — daily/weekly/monthly call totals for trend tiles."""
    aid = resolve_account_id(account_id)
    rows = pull_mod.pull_timeseries(aid, days, since, interval=interval,
                                    **_collect_filters(**filters))
    emit(rows, pull_mod.COLUMNS["timeseries"], fmt,
         title=f"Timeseries ({interval}, {len(rows)} pts) — {aid}")


def main():
    try:
        cli()
    except Exception as e:
        console.print(f"[red]error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
