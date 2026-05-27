"""Ingest Custom Search Engine rank tracking into Neon.

For each tracked keyword, search the CSE (configured to search the entire web)
and find your domain's position. Write to metric_snapshots:
  - rank (1 = #1, null if not in top 30)
  - top_competitor (1 row per keyword, dimension carries the top competitor domain)

CSE quota: 100 free queries/day. Watch the keyword count.
"""
from __future__ import annotations

import datetime as dt
import sys

from cse.client import search

from ingest.core import Row, run_logger, write_rows, neon_conn

PLATFORM = "cse"

# Target keywords for SEO rank tracking. Tier 1 = highest-intent.
# REPLACE THESE with the actual keywords you want to track. Examples below are
# from a <your-city>-area home buyer; substitute your geo + intent + brand terms.
KEYWORDS = [
    # Tier 1: high-intent local searches (replace "<your city>" with your market)
    "we buy houses <your city>",
    "sell my house fast <your city>",
    "cash for houses <your city>",
    "sell house as is <your city>",
    "we buy ugly houses <your city>",
    # Tier 2: branded (your business name + slug)
    "<your business name>",
    "<yourbrandslug>",
    # Tier 3: broader intent
    "sell house fast",
    "cash home buyers near me",
    "we buy houses <your state abbrev>",
    "<your city> home buyer",
    "investment home buyer <your city>",
    "no realtor sell house <your city>",
    # Tier 4: state-level
    "we buy houses <your state>",
    "cash home buyers <your state>",
]

# Your domain — what to look for in CSE results
SELF_DOMAIN = "your-domain.com"
MAX_PAGES = 3  # search 30 results deep (3 × 10)


def find_rank(items: list, domain: str) -> int | None:
    for i, item in enumerate(items, start=1):
        link = (item.get("link") or item.get("displayLink") or "").lower()
        if domain.lower() in link:
            return i
    return None


def main() -> int:
    with run_logger(PLATFORM) as state:
        today = dt.date.today()
        rows: list[Row] = []
        kw_ranks: dict[str, int | None] = {}

        for kw in KEYWORDS:
            all_items: list = []
            top_competitor: str | None = None
            try:
                for page in range(MAX_PAGES):
                    resp = search(kw, num=10, start=page * 10 + 1, gl="us")
                    items = resp.get("items") or []
                    if page == 0 and items:
                        top_competitor = (items[0].get("displayLink") or "").lower()
                    all_items.extend(items)
                    if len(items) < 10:
                        break
            except Exception as e:
                print(f"cse {kw!r} failed: {e}", file=sys.stderr)
                continue

            rank = find_rank(all_items, SELF_DOMAIN)
            kw_ranks[kw] = rank

            dim = f"keyword:{kw}"
            # Rank — write 99 if not in top 30 so trend charts have continuous data
            rank_value = float(rank) if rank else 99.0
            rows.append(Row(PLATFORM, "rank", today, rank_value, dim))
            # Top competitor as a string-shaped dim variant so dashboards can table it
            if top_competitor:
                rows.append(Row(PLATFORM, "top_competitor_present", today, 1.0,
                                f"{dim}|competitor:{top_competitor}"))

            print(f"  {kw!r}: rank={rank or 'not in top 30'} top={top_competitor}")

        conn = neon_conn()
        try:
            n = write_rows(conn, rows)
            state["rows_written"] = n
            state["meta"] = {"keywords": len(KEYWORDS), "ranks": kw_ranks}
            print(f"cse: wrote {n} rows ({len(KEYWORDS)} keywords)")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
