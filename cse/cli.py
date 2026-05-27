"""cse — Click CLI for Google Custom Search."""
from __future__ import annotations

import json
import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

import click
from rich.console import Console

from . import __version__
from . import client as client_mod
from . import pull as pull_mod
from .format import emit

console = Console()


@click.group(help="Google Custom Search API CLI — programmatic SERP audits.")
@click.version_option(__version__, prog_name="cse")
def cli() -> None:
    pass


def _search_opts(f):
    """Reusable filter options."""
    f = click.option("--site", default=None, help="Limit / exclude a domain.")(f)
    f = click.option("--site-filter", type=click.Choice(["i", "e"]), default="i",
                     help="i=include only --site, e=exclude.")(f)
    f = click.option("--date-restrict", default=None,
                     help="d[N]/w[N]/m[N]/y[N] (e.g. d7 = last 7 days).")(f)
    f = click.option("--exact-terms", default=None)(f)
    f = click.option("--exclude-terms", default=None)(f)
    f = click.option("--file-type", default=None, help="pdf, doc, xls, etc.")(f)
    f = click.option("--gl", default="us")(f)
    f = click.option("--cr", default=None, help="Country restriction (e.g. countryUS).")(f)
    f = click.option("--lr", default="lang_en", help="Language restriction.")(f)
    f = click.option("--sort", default=None, help="'date' to sort by recency.")(f)
    f = click.option("--rights", default=None,
                     help="cc_publicdomain | cc_attribute | cc_sharealike | etc.")(f)
    return f


@cli.command("search")
@click.argument("query", nargs=-1, required=True)
@click.option("--num", default=10, type=int, help="Results to fetch (max 10 per page).")
@_search_opts
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.option("--full", is_flag=True, help="Wider column set (OG tags, dates).")
def search_cmd(query, num, site, site_filter, date_restrict, exact_terms,
              exclude_terms, file_type, gl, cr, lr, sort, rights, fmt, full):
    """Run a CSE search and print results."""
    q = " ".join(query)
    raw = client_mod.search(q, num=num, site=site, site_filter=site_filter,
                            date_restrict=date_restrict, exact_terms=exact_terms,
                            exclude_terms=exclude_terms, file_type=file_type,
                            gl=gl, cr=cr, lr=lr, sort=sort, rights=rights)
    rows = pull_mod.parse_results(raw, q)
    info = raw.get("searchInformation") or {}
    title = (
        f"CSE '{q}' — {len(rows)} results "
        f"({info.get('formattedTotalResults', '?')} total, {info.get('formattedSearchTime', '?')}s)"
    )
    cols = pull_mod.COLUMNS_FULL if full else pull_mod.COLUMNS
    emit(rows, cols, fmt, title=title)


@cli.command("paginate")
@click.argument("query", nargs=-1, required=True)
@click.option("--max", "max_results", default=100, type=int,
              help="Total results to fetch across pages (CSE hard cap = 100).")
@_search_opts
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
def paginate_cmd(query, max_results, site, site_filter, date_restrict,
                exact_terms, exclude_terms, file_type, gl, cr, lr, sort,
                rights, fmt):
    """Paginate beyond a single 10-result page (max 100 results — CSE API cap)."""
    q = " ".join(query)
    rows = pull_mod.paginate(
        client_mod.search, q, max_results=max_results,
        site=site, site_filter=site_filter, date_restrict=date_restrict,
        exact_terms=exact_terms, exclude_terms=exclude_terms,
        file_type=file_type, gl=gl, cr=cr, lr=lr, sort=sort, rights=rights,
    )
    emit(rows, pull_mod.COLUMNS, fmt, title=f"CSE '{q}' — {len(rows)} results (paginated)")


@cli.command("images")
@click.argument("query", nargs=-1, required=True)
@click.option("--num", default=10, type=int)
@click.option("--img-type", type=click.Choice(["clipart", "face", "lineart", "news", "photo"]),
              default=None)
@click.option("--img-size", type=click.Choice(["huge", "large", "medium", "small",
                                                "xlarge", "xxlarge", "icon"]),
              default=None)
@click.option("--img-color-type", type=click.Choice(["color", "gray", "mono", "trans"]),
              default=None)
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
def images_cmd(query, num, img_type, img_size, img_color_type, fmt):
    """Image search (requires the engine to allow image search)."""
    q = " ".join(query)
    raw = client_mod.search(q, num=num, search_type="image",
                            img_type=img_type, img_size=img_size,
                            img_color_type=img_color_type)
    rows = pull_mod.parse_results(raw, q)
    emit(rows, pull_mod.COLUMNS_IMAGES, fmt, title=f"Image search '{q}' ({len(rows)})")


@cli.command("rank")
@click.argument("query", nargs=-1, required=True)
@click.option("--domain", required=True, help="Domain to find in results (e.g., your-domain.com).")
@click.option("--max-pages", default=10, type=int, help="Pages to scan (10 results each, CSE caps at 10 pages).")
@click.option("--gl", default="us")
@click.option("--date-restrict", default=None,
              help="Optional time filter (d7/w4/m1/y1).")
def rank_cmd(query, domain, max_pages, gl, date_restrict):
    """Find a domain's rank in CSE results for a query."""
    q = " ".join(query)
    found = None
    for page in range(min(max_pages, 10)):
        start = page * 10 + 1
        raw = client_mod.search(q, num=10, start=start, gl=gl, date_restrict=date_restrict)
        for i, item in enumerate(raw.get("items") or []):
            if domain in (item.get("displayLink") or ""):
                found = {"rank": page * 10 + i + 1, "title": item.get("title"), "link": item.get("link")}
                break
        if found:
            break
    if found:
        console.print(f"[green]Found {domain}[/green] for '{q}' at rank #{found['rank']}: {found['title']}")
        console.print(f"  {found['link']}")
    else:
        console.print(f"[yellow]{domain} not found[/yellow] in top {min(max_pages, 10)*10} for '{q}'")


@cli.command("info")
@click.argument("query", nargs=-1, required=True)
def info_cmd(query):
    """Search metadata only — total results, search time, spelling correction.

    Useful for "does Google know about this query?" without parsing the result list.
    """
    q = " ".join(query)
    raw = client_mod.search(q, num=1)
    info = pull_mod.parse_search_info(raw)
    print(json.dumps(info, indent=2, default=str))


def main():
    try:
        cli()
    except Exception as e:
        console.print(f"[red]error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
