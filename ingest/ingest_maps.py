"""Ingest Google Maps (Places API) competitor intelligence into Neon.

For each tracked query (e.g. "we buy houses <your-city>"), pull the top ~20
results from Places API New and write per-competitor metrics:
  - rating
  - review_count
  - rank_in_query (1-N order in the SERP results)

Dimension format: 'query:<Q>|place:<Name>' so the dashboard can drill into
competitors per query.

Tracked queries live in the QUERIES list below — extend as needed. Location
bias is <your-city> metro (DBH's primary market).
"""
from __future__ import annotations

import datetime as dt
import sys

from maps.client import text_search

from ingest.core import Row, run_logger, write_rows, neon_conn

PLATFORM = "maps"

# <your-city> metro location bias (40-mile radius)
PITTSBURGH_BIAS = {
    "circle": {
        "center": {"latitude": 0.0, "longitude": 0.0},
        "radius": 50000.0,  # Places API caps at 50km (~31 miles)
    }
}

# Curated competitor-intel queries — extend as needed
QUERIES = [
    "we buy houses <your-city>",
    "sell my house fast <your-city>",
    "cash for houses <your-city>",
    "home buyers <your-city>",
]

# Your business name as it appears in Google Maps (for self-tracking)
SELF_NAMES = ("<Your Business>", "DBH")


def main() -> int:
    with run_logger(PLATFORM) as state:
        today = dt.date.today()
        rows: list[Row] = []
        self_ranks: dict[str, int | None] = {}

        for query in QUERIES:
            try:
                resp = text_search(query, location_bias=PITTSBURGH_BIAS, max_results=20)
                places = resp.get("places", [])
            except Exception as e:
                print(f"maps query {query!r} failed: {e}", file=sys.stderr)
                continue

            self_rank: int | None = None
            for rank, p in enumerate(places, start=1):
                name = (p.get("displayName") or {}).get("text") or "?"
                place_id = p.get("id") or name
                rating = p.get("rating")
                review_count = p.get("userRatingCount", 0)

                dim_q = f"query:{query}"
                dim_p = f"{dim_q}|place:{name}"

                if rating is not None:
                    rows.append(Row(PLATFORM, "rating", today, float(rating), dim_p))
                if review_count is not None:
                    rows.append(Row(PLATFORM, "review_count", today, float(review_count), dim_p))
                rows.append(Row(PLATFORM, "rank_in_query", today, float(rank), dim_p))

                # Detect our own listing
                if any(s.lower() in name.lower() for s in SELF_NAMES):
                    self_rank = rank
                    rows.append(Row(PLATFORM, "self_rank", today, float(rank), dim_q))

            self_ranks[query] = self_rank
            print(f"  {query!r}: {len(places)} places, self_rank={self_rank}")

        conn = neon_conn()
        try:
            n = write_rows(conn, rows)
            state["rows_written"] = n
            state["meta"] = {"queries": len(QUERIES), "self_ranks": self_ranks}
            print(f"maps: wrote {n} rows ({len(QUERIES)} queries)")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
