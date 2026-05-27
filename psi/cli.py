"""psi — Click CLI for PageSpeed Insights."""
from __future__ import annotations

import sys
import time
import warnings

warnings.filterwarnings("ignore", category=FutureWarning, module="google.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")

import json

import click
from rich.console import Console

from . import __version__
from .client import run_pagespeed, get_api_key
from .pull import (parse_psi, parse_psi_full_audits, parse_psi_resources,
                   COLUMNS, COLUMNS_FULL_AUDITS, COLUMNS_RESOURCES,
                   ALL_CATEGORIES)
from .format import emit

console = Console()


@click.group(help="Personal PageSpeed Insights CLI — Core Web Vitals + Lighthouse scores.")
@click.version_option(__version__, prog_name="psi")
def cli() -> None:
    pass


@cli.command("audit")
@click.argument("urls", nargs=-1, required=True)
@click.option("--strategy", type=click.Choice(["mobile", "desktop", "both"]), default="both",
              help="Run mobile, desktop, or both (default both = 2 calls per URL).")
@click.option("--category", "categories", multiple=True,
              type=click.Choice(["performance", "accessibility", "best-practices", "seo", "pwa"]),
              help="Repeatable. Default = all 5 categories.")
@click.option("--locale", default="en_US", help="Result locale (default en_US).")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table",
              help="Output format.")
@click.option("--raw", is_flag=True, help="Print raw PSI JSON responses, no parsing.")
@click.option("--sleep", "sleep_s", type=float, default=1.5,
              help="Seconds between API calls (default 1.5 to stay under 1 QPS).")
def audit_cmd(urls, strategy, categories, locale, fmt, raw, sleep_s):
    """Run PageSpeed audit on one or more URLs.

    Without an API key in google-ads.yaml (`psi_api_key`), free tier limits to
    ~1 query/sec and 25k/day. With a key, you get higher quotas.
    """
    if not get_api_key():
        console.print("[yellow]No psi_api_key in google-ads.yaml — running unauthenticated (lower quota).[/yellow]")
    strategies = ["MOBILE", "DESKTOP"] if strategy == "both" else [strategy.upper()]
    cats = [c.upper().replace("-", "_") for c in categories] if categories else None
    rows = []
    raw_out = {}
    for i, url in enumerate(urls):
        for s in strategies:
            console.print(f"  [{i+1}/{len(urls)}] {s.lower():7} {url}")
            try:
                resp = run_pagespeed(url, strategy=s, categories=cats, locale=locale)
                if raw:
                    raw_out.setdefault(url, {})[s] = resp
                else:
                    rows.append(parse_psi(resp, url, s))
            except Exception as e:
                console.print(f"    [red]error[/red]: {e}")
                rows.append({"url": url, "strategy": s, "error": str(e)})
            time.sleep(sleep_s)
    if raw:
        click.echo(json.dumps(raw_out, indent=2))
    else:
        emit(rows, COLUMNS, fmt, title=f"PSI audit ({len(rows)} runs)")


@cli.command("audits")
@click.argument("urls", nargs=-1, required=True)
@click.option("--strategy", type=click.Choice(["mobile", "desktop"]), default="mobile")
@click.option("--locale", default="en_US")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.option("--sleep", "sleep_s", type=float, default=1.5)
@click.option("--failed-only", is_flag=True, help="Only emit audits with score < 0.9.")
def audits_cmd(urls, strategy, locale, fmt, sleep_s, failed_only):
    """Deep audit — one row per individual Lighthouse audit (~150 per URL).

    Use this when you need to know exactly which a11y/seo/perf checks are
    failing, not just the category scores.
    """
    rows = []
    for i, url in enumerate(urls):
        console.print(f"  [{i+1}/{len(urls)}] {strategy:7} {url}")
        try:
            resp = run_pagespeed(url, strategy=strategy.upper(), locale=locale)
            audit_rows = parse_psi_full_audits(resp, url, strategy.upper())
            if failed_only:
                audit_rows = [r for r in audit_rows
                              if r.get("score") is not None and r["score"] < 0.9]
            rows.extend(audit_rows)
        except Exception as e:
            console.print(f"    [red]error[/red]: {e}")
        time.sleep(sleep_s)
    emit(rows, ["url"] + COLUMNS_FULL_AUDITS, fmt,
         title=f"PSI individual audits ({len(rows)} rows)")


@cli.command("resources")
@click.argument("url")
@click.option("--strategy", type=click.Choice(["mobile", "desktop"]), default="mobile")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
def resources_cmd(url, strategy, fmt):
    """Network request inventory — every resource Lighthouse saw, sorted by size."""
    resp = run_pagespeed(url, strategy=strategy.upper())
    rows = parse_psi_resources(resp, url, strategy.upper())
    emit(rows, COLUMNS_RESOURCES, fmt,
         title=f"Resources ({len(rows)}) — {url}")


def main():
    try:
        cli()
    except Exception as e:
        console.print(f"[red]error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
