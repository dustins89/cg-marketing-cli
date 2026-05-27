"""Ingest Calendly scheduled_events → Neon.

For each day in the lookback window writes:
  bookings_count          dimension=NULL
  bookings_count          dimension='event_type:<name>'
  bookings_canceled_count dimension=NULL
  bookings_canceled_count dimension='event_type:<name>'

Plus heatmap-style buckets for booking time-of-day (when do consults happen):
  booking_hour_count      dimension='dow:<0-6>|hour:<0-23>'

Lead-time (how far ahead people book) — average per day:
  booking_leadtime_hours_avg  dimension=NULL  (avg over the day's bookings)
"""
from __future__ import annotations

import datetime as dt
import sys
from collections import Counter, defaultdict
from zoneinfo import ZoneInfo

from calendly import client as cal

from ingest.core import Row, neon_conn, run_logger, write_rows


PLATFORM = "calendly"
LOOKBACK_DAYS = 90
NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc


def main() -> int:
    with run_logger(PLATFORM) as state:
        try:
            org_uri = cal.organization_uri()
            print(f"calendly org: {org_uri}")
        except Exception as e:
            print(f"calendly auth failed: {e}", file=sys.stderr)
            state["status"] = "failed"
            state["error"] = str(e)[-500:]
            return 1

        end = dt.datetime.now(UTC)
        start = end - dt.timedelta(days=LOOKBACK_DAYS)

        per_day_total: Counter = Counter()        # date -> count
        per_day_type: defaultdict = defaultdict(Counter)  # date -> Counter(event_type -> count)
        per_day_cancel: Counter = Counter()
        per_day_cancel_type: defaultdict = defaultdict(Counter)
        heatmap: Counter = Counter()              # (dow, hour) -> count
        leadtime_sum: defaultdict = defaultdict(float)
        leadtime_n: defaultdict = defaultdict(int)
        seen = 0

        try:
            for ev in cal.scheduled_events(min_start_time=start, max_start_time=end):
                seen += 1
                start_utc = dt.datetime.fromisoformat(ev["start_time"].replace("Z", "+00:00"))
                start_local = start_utc.astimezone(NY)
                d = start_local.date()
                # `name` is the human-readable event-type label ("Property
                # Specialist Call", "Quick Chat"). `event_type` is a URI to
                # the type config — use the name for dimensions.
                etype = (ev.get("name") or "").strip() or "unknown"
                etype = etype.replace("|", "_")
                status = (ev.get("status") or "active").lower()

                if status == "canceled":
                    per_day_cancel[d] += 1
                    per_day_cancel_type[d][etype] += 1
                else:
                    per_day_total[d] += 1
                    per_day_type[d][etype] += 1
                    heatmap[(start_local.weekday(), start_local.hour)] += 1

                # Lead time: created_at → start_time
                created_iso = ev.get("created_at")
                if created_iso:
                    created_utc = dt.datetime.fromisoformat(created_iso.replace("Z", "+00:00"))
                    lead_hours = max(0.0, (start_utc - created_utc).total_seconds() / 3600)
                    leadtime_sum[d] += lead_hours
                    leadtime_n[d] += 1
        except Exception as e:
            print(f"calendly events fetch failed: {e}", file=sys.stderr)
            state["status"] = "partial"
            state["error"] = str(e)[-500:]

        today = dt.date.today()
        rows: list[Row] = []

        # Per-day rollups
        all_days = set(per_day_total) | set(per_day_cancel)
        for d in sorted(all_days):
            rows.append(Row(PLATFORM, "bookings_count", d, float(per_day_total.get(d, 0))))
            rows.append(Row(PLATFORM, "bookings_canceled_count", d, float(per_day_cancel.get(d, 0))))
            n = leadtime_n.get(d, 0)
            if n:
                rows.append(Row(PLATFORM, "booking_leadtime_hours_avg", d,
                                leadtime_sum[d] / n))
            for etype, cnt in per_day_type.get(d, {}).items():
                rows.append(Row(PLATFORM, "bookings_count", d, float(cnt),
                                dimension=f"event_type:{etype}"))
            for etype, cnt in per_day_cancel_type.get(d, {}).items():
                rows.append(Row(PLATFORM, "bookings_canceled_count", d, float(cnt),
                                dimension=f"event_type:{etype}"))

        # Heatmap — single snapshot dated today
        for (dow, hour), n in heatmap.items():
            rows.append(Row(PLATFORM, "booking_hour_count", today, float(n),
                            dimension=f"dow:{dow}|hour:{hour}"))

        conn = neon_conn()
        try:
            n_written = write_rows(conn, rows)
            state["rows_written"] = n_written
            state["meta"] = {"events_seen": seen, "days": LOOKBACK_DAYS}
            print(f"calendly: wrote {n_written} rows ({seen} events seen)")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
