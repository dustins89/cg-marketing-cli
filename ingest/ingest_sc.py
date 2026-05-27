"""Ingest Google Search Console metrics into Neon.

Writes to metric_snapshots:
  - Daily totals (dim=NULL):    clicks, impressions, ctr, position
  - By query (dim='query:X'):   top 100 queries × day × metrics
  - By page (dim='page:X'):     top 100 pages × day × metrics
  - By device (dim='device:X'): all device segments
  - Query × page (dim='query:Q|page:P'): last-28d totals (clicks, impressions,
    avg_position), top 100 by impressions, stamped at today. This is the
    SEO content roadmap — which page captures which keyword.

GSC data lags 2-3 days. We pull dataState='all' for fresher numbers and accept
the unfinalized data flag. Default lookback 45 days to overlap with prior runs.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from collections import defaultdict

from search_console.client import get_service, get_site_url
from search_console import pull as sc

from ingest.core import Row, run_logger, write_rows, neon_conn

PLATFORM = "sc"
LOOKBACK_DAYS_DEFAULT = 45

# Dimension string sizing — keep below the column's text-length budget while
# preserving uniqueness. Query is rarely long; page URLs can be huge.
_QUERY_MAX = 120
_PAGE_MAX = 180


def _truncate_query(q: str) -> str:
    q = q.strip()
    return q[:_QUERY_MAX]


def _truncate_page(p: str) -> str:
    """Pages come as full URLs (https://host/path...). Strip protocol+host so
    the dim stays compact, then truncate. Falls back gracefully on parse fail.
    """
    if not p:
        return ""
    try:
        # Drop scheme + netloc — keep path + query.
        if "://" in p:
            after = p.split("://", 1)[1]
            slash = after.find("/")
            path = after[slash:] if slash >= 0 else "/"
        else:
            path = p
    except Exception:
        path = p
    return path[:_PAGE_MAX]


def main(days: int = LOOKBACK_DAYS_DEFAULT) -> int:
    with run_logger(PLATFORM) as state:
        service = get_service()
        site = get_site_url()
        rows: list[Row] = []

        # 1) Daily totals via timeseries
        ts = sc.pull_timeseries(service, site, days=days, since=None, limit=10000,
                                search_type="web", data_state="all",
                                group="date")
        date_totals: dict[dt.date, dict] = {}
        for r in ts:
            try:
                d = dt.date.fromisoformat(str(r["date"]))
            except ValueError:
                continue
            date_totals[d] = r
            rows.append(Row(PLATFORM, "clicks",      d, float(r.get("clicks", 0))))
            rows.append(Row(PLATFORM, "impressions", d, float(r.get("impressions", 0))))
            rows.append(Row(PLATFORM, "ctr",         d, float(r.get("ctr", 0))))
            rows.append(Row(PLATFORM, "position",    d, float(r.get("position", 0))))

        # 2) Daily × query (top queries grouped per day)
        try:
            qrows = sc._query(service, site, ["date", "query"], days=days, since=None,
                              limit=5000, search_type="web", data_state="all",
                              paginate=True)
            for r in qrows:
                try:
                    d = dt.date.fromisoformat(str(r["date"]))
                except ValueError:
                    continue
                q = (r.get("query") or "")[:200]
                if not q:
                    continue
                rows.append(Row(PLATFORM, "clicks",      d, float(r.get("clicks", 0)),
                                dimension=f"query:{q}"))
                rows.append(Row(PLATFORM, "impressions", d, float(r.get("impressions", 0)),
                                dimension=f"query:{q}"))
        except Exception as e:
            print(f"sc query pull failed: {e}", file=sys.stderr)

        # 3) Daily × page (top pages grouped per day)
        try:
            prows = sc._query(service, site, ["date", "page"], days=days, since=None,
                              limit=5000, search_type="web", data_state="all",
                              paginate=True)
            for r in prows:
                try:
                    d = dt.date.fromisoformat(str(r["date"]))
                except ValueError:
                    continue
                p = (r.get("page") or "")[:300]
                if not p:
                    continue
                rows.append(Row(PLATFORM, "clicks",      d, float(r.get("clicks", 0)),
                                dimension=f"page:{p}"))
                rows.append(Row(PLATFORM, "impressions", d, float(r.get("impressions", 0)),
                                dimension=f"page:{p}"))
        except Exception as e:
            print(f"sc page pull failed: {e}", file=sys.stderr)

        # 4) Daily × device
        try:
            drows = sc._query(service, site, ["date", "device"], days=days, since=None,
                              limit=5000, search_type="web", data_state="all")
            for r in drows:
                try:
                    d = dt.date.fromisoformat(str(r["date"]))
                except ValueError:
                    continue
                dev = (r.get("device") or "").upper() or "UNKNOWN"
                rows.append(Row(PLATFORM, "clicks",      d, float(r.get("clicks", 0)),
                                dimension=f"device:{dev}"))
                rows.append(Row(PLATFORM, "impressions", d, float(r.get("impressions", 0)),
                                dimension=f"device:{dev}"))
        except Exception as e:
            print(f"sc device pull failed: {e}", file=sys.stderr)

        # 5) Query × page (last 28d totals, top 100 by impressions)
        # Stamped at today's date — replaces in place each run (no time series).
        try:
            qp_rows = sc.pull_query_page(service, site, days=28, since=None,
                                         limit=100, search_type="web",
                                         data_state="all")
            # API returns sorted by clicks by default; re-sort by impressions
            # and clip to top 100 to honor the "top 100 by impressions" spec.
            qp_rows = sorted(qp_rows, key=lambda r: int(r.get("impressions", 0)),
                             reverse=True)[:100]
            today = dt.date.today()
            for r in qp_rows:
                q = _truncate_query(r.get("query") or "")
                p = _truncate_page(r.get("page") or "")
                if not q or not p:
                    continue
                dim = f"query:{q}|page:{p}"
                rows.append(Row(PLATFORM, "clicks",       today,
                                float(r.get("clicks", 0)),       dimension=dim))
                rows.append(Row(PLATFORM, "impressions",  today,
                                float(r.get("impressions", 0)),  dimension=dim))
                rows.append(Row(PLATFORM, "avg_position", today,
                                float(r.get("position", 0)),     dimension=dim))
        except Exception as e:
            print(f"sc query-page pull failed: {e}", file=sys.stderr)

        conn = neon_conn()
        try:
            n = write_rows(conn, rows)
            state["rows_written"] = n
            state["meta"] = {"days": days, "site": site}
            print(f"sc: wrote {n} rows ({days}d) — site={site}")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else LOOKBACK_DAYS_DEFAULT
    sys.exit(main(days))
