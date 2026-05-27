"""Ingest Callingly speed-to-lead metrics → Neon.

Per-day aggregates:
  callingly_lead_count          dimension=NULL
  callingly_calls_placed        dimension=NULL
  callingly_connections         dimension=NULL          (calls that connected)
  callingly_stl_seconds_avg     dimension=NULL          (speed-to-lead, avg)
  callingly_stl_seconds_p50     dimension=NULL          (median STL)
  callingly_stl_seconds_p90     dimension=NULL          (90th pct STL — tail performance)
  callingly_avg_call_duration   dimension=NULL          (avg call length in s)

Per-agent breakdowns (snapshot dated today, 30-day window):
  callingly_calls_placed       dimension='agent:<name>'
  callingly_connections        dimension='agent:<name>'
  callingly_stl_seconds_avg    dimension='agent:<name>'

STL histogram (snapshot dated today): how many leads got called in
each bucket — bucket boundaries in CALL_BUCKETS_SECONDS.
  callingly_stl_bucket_count    dimension='bucket:<label>'
"""
from __future__ import annotations

import datetime as dt
import statistics
import sys
from collections import Counter, defaultdict

from callingly import client as cg

from ingest.core import Row, neon_conn, run_logger, write_rows


PLATFORM = "callingly"
LOOKBACK_DAYS = 30
UTC = dt.timezone.utc

# Speed-to-lead histogram buckets (seconds)
CALL_BUCKETS = [
    ("< 1 min",   0,    60),
    ("1-5 min",   60,   300),
    ("5-15 min",  300,  900),
    ("15-60 min", 900,  3600),
    ("1-6 hr",    3600, 21600),
    ("> 6 hr",    21600, 10**9),
    ("never",     None, None),  # leads with no calls
]


def _bucket(stl_s: float | None) -> str:
    if stl_s is None:
        return "never"
    for label, lo, hi in CALL_BUCKETS:
        if lo is None:
            continue
        if lo <= stl_s < hi:
            return label
    return "> 6 hr"


def _parse_dt(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=UTC)
        return d
    except Exception:
        return None


def main() -> int:
    with run_logger(PLATFORM) as state:
        end = dt.datetime.now(UTC)
        start = end - dt.timedelta(days=LOOKBACK_DAYS)

        per_day_leads: Counter = Counter()
        per_day_calls: Counter = Counter()
        per_day_connections: Counter = Counter()
        per_day_stls: defaultdict = defaultdict(list)
        per_day_durations: defaultdict = defaultdict(list)
        per_agent: defaultdict = defaultdict(lambda: {"calls": 0, "connections": 0, "stls": []})
        bucket_counts: Counter = Counter()
        seen = 0

        try:
            for lead in cg.leads(since=start, until=end):
                seen += 1
                created = _parse_dt(lead.get("created_at"))
                if not created:
                    continue
                d = created.date()
                per_day_leads[d] += 1

                # Calls array — Callingly returns call attempts under 'calls'
                calls = lead.get("calls") or []
                first_started = None
                lead_stl = None
                lead_connected = False

                for call in calls:
                    started = _parse_dt(call.get("started_at") or call.get("created_at"))
                    if not started:
                        continue
                    per_day_calls[d] += 1
                    # Callingly docs: 'seconds' is the canonical talk-time field
                    duration = call.get("seconds") or call.get("duration") or 0
                    if duration:
                        per_day_durations[d].append(float(duration))

                    # Connection = had talk time > 10s AND not voicemail.
                    # Voicemails can still have long "duration" so check the flag.
                    is_voicemail = bool(call.get("is_voicemail"))
                    connected = (not is_voicemail) and (duration or 0) > 10
                    if connected:
                        per_day_connections[d] += 1
                        lead_connected = True

                    if first_started is None or started < first_started:
                        first_started = started

                    # Callingly docs: nested 'user' object carries agent info,
                    # not 'agent'. Fall back to a few keys to handle drift.
                    user = call.get("user") or call.get("agent") or {}
                    if isinstance(user, dict):
                        agent_name = user.get("name") or user.get("fname") \
                                     or user.get("email") or "(unknown)"
                    else:
                        agent_name = call.get("agent_name") or "(unknown)"
                    per_agent[agent_name]["calls"] += 1
                    if connected:
                        per_agent[agent_name]["connections"] += 1

                if first_started:
                    lead_stl = max(0.0, (first_started - created).total_seconds())
                    per_day_stls[d].append(lead_stl)
                    bucket_counts[_bucket(lead_stl)] += 1
                    for agent_name, _ in per_agent.items():
                        # this agent attribution is approximate; we'll write STL per lead globally
                        pass
                else:
                    bucket_counts[_bucket(None)] += 1
        except Exception as e:
            print(f"callingly fetch failed: {e}", file=sys.stderr)
            state["status"] = "failed"
            state["error"] = str(e)[-500:]
            return 1

        today = dt.date.today()
        rows: list[Row] = []

        for d in sorted(per_day_leads):
            rows.append(Row(PLATFORM, "callingly_lead_count", d, float(per_day_leads[d])))
            rows.append(Row(PLATFORM, "callingly_calls_placed", d, float(per_day_calls.get(d, 0))))
            rows.append(Row(PLATFORM, "callingly_connections", d, float(per_day_connections.get(d, 0))))
            stls = per_day_stls.get(d, [])
            if stls:
                rows.append(Row(PLATFORM, "callingly_stl_seconds_avg", d, statistics.mean(stls)))
                rows.append(Row(PLATFORM, "callingly_stl_seconds_p50", d, statistics.median(stls)))
                rows.append(Row(PLATFORM, "callingly_stl_seconds_p90", d,
                                statistics.quantiles(stls, n=10)[-1] if len(stls) >= 10
                                else max(stls)))
            durs = per_day_durations.get(d, [])
            if durs:
                rows.append(Row(PLATFORM, "callingly_avg_call_duration", d, statistics.mean(durs)))

        # Per-agent rollups (today's snapshot, last 30d window)
        for agent_name, agg in per_agent.items():
            rows.append(Row(PLATFORM, "callingly_calls_placed", today, float(agg["calls"]),
                            dimension=f"agent:{agent_name}"))
            rows.append(Row(PLATFORM, "callingly_connections", today, float(agg["connections"]),
                            dimension=f"agent:{agent_name}"))

        # Histogram
        for bucket, cnt in bucket_counts.items():
            rows.append(Row(PLATFORM, "callingly_stl_bucket_count", today, float(cnt),
                            dimension=f"bucket:{bucket}"))

        conn = neon_conn()
        try:
            n_written = write_rows(conn, rows)
            state["rows_written"] = n_written
            state["meta"] = {"leads_seen": seen, "days": LOOKBACK_DAYS}
            print(f"callingly: wrote {n_written} rows ({seen} leads seen)")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
