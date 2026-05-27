"""maps — Click CLI for Google Places API (competitive intel)."""
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


@click.group(help="Google Places API CLI — competitive GBP intel for local search.")
@click.version_option(__version__, prog_name="maps")
def cli() -> None:
    pass


def _fmt(f):
    return click.option(
        "--format", "fmt", type=click.Choice(["table", "json"]), default="table",
    )(f)


@cli.command("search")
@click.argument("query", nargs=-1, required=True)
@click.option("--lat", type=float, default=None, help="Center latitude for location bias.")
@click.option("--lng", type=float, default=None, help="Center longitude for location bias.")
@click.option("--radius-km", type=float, default=20.0, help="Bias radius in km (default 20).")
@click.option("--limit", default=20, type=int, help="Max results (max 20 per call).")
@_fmt
def search_cmd(query, lat, lng, radius_km, limit, fmt):
    """Free-text place search. Use --lat/--lng for <your-city>-area bias.

    <Your City> center: --lat 0.0 --lng 0.0
    """
    q = " ".join(query)
    bias = None
    if lat is not None and lng is not None:
        bias = {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius_km * 1000}}
    raw = client_mod.text_search(q, location_bias=bias, max_results=limit)
    rows = pull_mod.parse_places(raw)
    emit(rows, pull_mod.COLUMNS["search"], fmt, title=f"Places for '{q}' ({len(rows)})")


@cli.command("detail")
@click.argument("place_id")
@_fmt
def detail_cmd(place_id, fmt):
    """Get full detail for one place by place_id (e.g., ChIJxxxx...)."""
    raw = client_mod.place_details(place_id)
    if fmt == "json":
        click.echo(json.dumps(raw, indent=2))
    else:
        row = pull_mod.parse_place_detail(raw)
        emit([row], pull_mod.COLUMNS["detail"], "table", title=f"Place {place_id}")


def main():
    try:
        cli()
    except Exception as e:
        console.print(f"[red]error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
