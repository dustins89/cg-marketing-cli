"""Ingest GA4 Data API metrics into Neon — sessions/conversions by channel + source/medium,
plus per-event volume + utm fill-rate (for the Event-tracking-health tile)."""
from __future__ import annotations

import datetime as dt
import sys
import traceback

from ga4.client import get_client, get_property_id
from ga4 import pull

from ingest.core import Row, run_logger, write_rows, neon_conn

PLATFORM = "ga4"
LOOKBACK_DAYS_DEFAULT = 35
EVENT_HEALTH_LOOKBACK_DAYS = 7
EVENT_HEALTH_TOP_N = 30


def main(days: int = LOOKBACK_DAYS_DEFAULT) -> int:
    with run_logger(PLATFORM) as state:
        client = get_client()
        pid = get_property_id()
        rows: list[Row] = []

        # Daily totals — need a custom pull (date dim isn't in existing presets)
        # Reuse the internal _run helper via direct request
        from google.analytics.data_v1beta.types import (
            DateRange, Dimension, Metric, RunReportRequest,
            Filter, FilterExpression, FilterExpressionList,
        )
        start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
        end = dt.date.today().isoformat()

        def run(dimensions: list[str], metrics: list[str]) -> list[dict]:
            req = RunReportRequest(
                property=f"properties/{pid}",
                dimensions=[Dimension(name=d) for d in dimensions],
                metrics=[Metric(name=m) for m in metrics],
                date_ranges=[DateRange(start_date=start, end_date=end)],
                limit=1000,
            )
            resp = client.run_report(req)
            out = []
            for r in resp.rows:
                row = {}
                for i, d in enumerate(dimensions):
                    row[d] = r.dimension_values[i].value
                for i, m in enumerate(metrics):
                    row[m] = float(r.metric_values[i].value or 0)
                out.append(row)
            return out

        # Daily site-level totals
        for r in run(["date"], ["sessions", "conversions", "totalRevenue", "screenPageViews"]):
            d = dt.datetime.strptime(r["date"], "%Y%m%d").date()
            rows.append(Row(PLATFORM, "sessions",          d, r["sessions"]))
            rows.append(Row(PLATFORM, "conversions",       d, r["conversions"]))
            rows.append(Row(PLATFORM, "total_revenue_usd", d, r["totalRevenue"]))
            rows.append(Row(PLATFORM, "screen_page_views", d, r["screenPageViews"]))

        # Daily x channel group (sessions, conversions)
        for r in run(["date", "sessionDefaultChannelGroup"], ["sessions", "conversions"]):
            d = dt.datetime.strptime(r["date"], "%Y%m%d").date()
            ch = r.get("sessionDefaultChannelGroup") or "(unknown)"
            rows.append(Row(PLATFORM, "sessions",    d, r["sessions"],
                            dimension=f"channel:{ch}"))
            rows.append(Row(PLATFORM, "conversions", d, r["conversions"],
                            dimension=f"channel:{ch}"))

        # Daily x source/medium
        for r in run(["date", "sessionSourceMedium"], ["sessions", "conversions"]):
            d = dt.datetime.strptime(r["date"], "%Y%m%d").date()
            sm = r.get("sessionSourceMedium") or "(unknown)"
            rows.append(Row(PLATFORM, "sessions",    d, r["sessions"],
                            dimension=f"source_medium:{sm}"))
            rows.append(Row(PLATFORM, "conversions", d, r["conversions"],
                            dimension=f"source_medium:{sm}"))

        # ─── Event tracking health (7d) ──────────────────────────────────────
        # Per-event total volume + count where session source is set (proxy for
        # utm fill rate). Two runReport calls; diff in the dashboard tile.
        # Wrapped so failures here don't break the rest of the ingest.
        try:
            health_start = (dt.date.today() - dt.timedelta(days=EVENT_HEALTH_LOOKBACK_DAYS)).isoformat()
            health_end = dt.date.today().isoformat()
            health_date = dt.date.today()  # snapshot date — all rows share it

            def run_event_report(filter_expr: FilterExpression | None) -> list[dict]:
                req = RunReportRequest(
                    property=f"properties/{pid}",
                    dimensions=[Dimension(name="eventName")],
                    metrics=[Metric(name="eventCount")],
                    date_ranges=[DateRange(start_date=health_start, end_date=health_end)],
                    dimension_filter=filter_expr,
                    limit=EVENT_HEALTH_TOP_N,
                )
                resp = client.run_report(req)
                out = []
                for r in resp.rows:
                    out.append({
                        "eventName": r.dimension_values[0].value,
                        "eventCount": float(r.metric_values[0].value or 0),
                    })
                return out

            # 1) Total per event (top N by volume)
            totals = run_event_report(None)

            # 2) Same, but only events where sessionSource is set (i.e. utm/attribution present)
            #    Filter: sessionSource is NOT in ('(direct)', '(not set)')
            with_utm_filter = FilterExpression(
                not_expression=FilterExpression(
                    filter=Filter(
                        field_name="sessionSource",
                        in_list_filter=Filter.InListFilter(
                            values=["(direct)", "(not set)", ""],
                        ),
                    ),
                ),
            )
            with_utm = run_event_report(with_utm_filter)
            with_utm_by_name = {r["eventName"]: r["eventCount"] for r in with_utm}

            for r in totals:
                ev = r["eventName"]
                rows.append(Row(
                    PLATFORM, "event_count", health_date, r["eventCount"],
                    dimension=f"event:{ev}",
                    raw={"lookback_days": EVENT_HEALTH_LOOKBACK_DAYS},
                ))
                rows.append(Row(
                    PLATFORM, "event_count_with_utm", health_date,
                    with_utm_by_name.get(ev, 0.0),
                    dimension=f"event:{ev}",
                    raw={"lookback_days": EVENT_HEALTH_LOOKBACK_DAYS},
                ))
        except Exception:
            print(f"ga4: event-health pull failed (continuing):\n{traceback.format_exc()}",
                  file=sys.stderr)

        conn = neon_conn()
        try:
            n = write_rows(conn, rows)
            state["rows_written"] = n
            state["meta"] = {"days": days}
            print(f"ga4: wrote {n} rows ({days}d)")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else LOOKBACK_DAYS_DEFAULT
    sys.exit(main(days))
