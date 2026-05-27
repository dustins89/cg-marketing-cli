"""Ingest CallRail metrics into Neon.

Uses the server-side /calls/timeseries endpoint (daily granularity) for
volume metrics, plus client-side aggregation over raw /calls for the spam
rate and tracking-number breakdown.

Also pulls form submissions (`/form_submissions.json`) and writes daily
totals (dim=NULL) plus per-form-name (dim='form:<name>') counts to
metric_snapshots under metric='form_submission_count'.
"""
from __future__ import annotations

import datetime as dt
import sys
from collections import defaultdict

from callrail import client as cr
from callrail import pull

from ingest.core import Row, run_logger, write_rows, neon_conn

PLATFORM = "callrail"
LOOKBACK_DAYS_DEFAULT = 35


def main(days: int = LOOKBACK_DAYS_DEFAULT) -> int:
    with run_logger(PLATFORM) as state:
        aid = cr.resolve_account_id()
        # 1) Daily timeseries (volume + answered + first-time + leads)
        ts = pull.pull_timeseries(aid, days=days, since=None, interval="day")
        rows: list[Row] = []
        for r in ts:
            # date in CallRail comes as ISO "YYYY-MM-DD"
            d = dt.date.fromisoformat(str(r["date"])[:10])
            for metric in ("total_calls", "answered_calls", "missed_calls",
                           "first_time_callers", "leads"):
                v = r.get(metric)
                if v is not None:
                    rows.append(Row(PLATFORM, metric, d, float(v)))
            if r.get("average_duration_seconds") is not None:
                rows.append(Row(PLATFORM, "avg_duration_sec", d,
                                float(r["average_duration_seconds"])))

        # 2) Raw calls (for spam, by-source, by-number client-side aggregation)
        calls = pull.pull_calls(aid, days=days, since=None)
        # Bucket by date
        by_date: dict[dt.date, dict] = defaultdict(
            lambda: {"spam": 0, "by_source": defaultdict(int),
                     "by_number": defaultdict(int)}
        )
        for c in calls:
            start = c.get("start_time") or ""
            try:
                d = dt.date.fromisoformat(start[:10])
            except ValueError:
                continue
            bucket = by_date[d]
            if c.get("spam"):
                bucket["spam"] += 1
            src = c.get("source") or "(unknown)"
            bucket["by_source"][src] += 1
            num = c.get("tracking_phone_number") or "(unknown)"
            bucket["by_number"][num] += 1

        for d, b in by_date.items():
            rows.append(Row(PLATFORM, "spam_calls", d, float(b["spam"])))
            for src, n in b["by_source"].items():
                rows.append(Row(PLATFORM, "total_calls", d, float(n),
                                dimension=f"source:{src}"))
            for num, n in b["by_number"].items():
                rows.append(Row(PLATFORM, "total_calls", d, float(n),
                                dimension=f"tracking_number:{num}"))

        # 3) Form submissions — daily totals + per-form counts
        forms_seen = 0
        try:
            form_days = max(days, 30)
            forms = pull.pull_form_submissions(aid, days=form_days, since=None)
            forms_seen = len(forms)
            daily_total: dict[dt.date, int] = defaultdict(int)
            daily_by_form: dict[tuple[dt.date, str], int] = defaultdict(int)
            for f in forms:
                stamp = f.get("submitted_at") or f.get("created_at") or ""
                try:
                    d = dt.date.fromisoformat(str(stamp)[:10])
                except ValueError:
                    continue
                daily_total[d] += 1
                name = (f.get("form_name") or "(unnamed)").strip()[:120]
                daily_by_form[(d, name)] += 1
            for d, n in daily_total.items():
                rows.append(Row(PLATFORM, "form_submission_count", d, float(n)))
            for (d, name), n in daily_by_form.items():
                rows.append(Row(PLATFORM, "form_submission_count", d, float(n),
                                dimension=f"form:{name}"))
        except Exception as e:
            print(f"callrail forms pull failed: {e}", file=sys.stderr)

        conn = neon_conn()
        try:
            n = write_rows(conn, rows)
            state["rows_written"] = n
            state["meta"] = {"days": days, "calls_seen": len(calls),
                             "forms_seen": forms_seen}
            print(f"callrail: wrote {n} rows ({days}d, {len(calls)} calls, "
                  f"{forms_seen} form submissions)")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else LOOKBACK_DAYS_DEFAULT
    sys.exit(main(days))
