"""Output helpers — JSON for piping/sharing, Rich tables for terminal."""
from __future__ import annotations

import json
import sys
from typing import Iterable

from rich.console import Console
from rich.table import Table

console = Console()


def micros_to_dollars(micros: int | None) -> float:
    if micros is None:
        return 0.0
    return round(int(micros) / 1_000_000, 2)


def emit(rows: list[dict], columns: list[str], fmt: str, title: str = "") -> None:
    """Emit rows in the requested format.

    fmt: "table" | "json"
    columns: ordered list of dict keys to display in table mode
    """
    if fmt == "json":
        json.dump(rows, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return

    table = Table(title=title, show_lines=False)
    for col in columns:
        table.add_column(col)
    for row in rows:
        table.add_row(*[_render(row.get(c)) for c in columns])
    console.print(table)


def _render(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)
