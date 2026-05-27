"""Ingest YouTube Analytics metrics into Neon.

Pulls 30-day daily history per run (upserts via metric_snapshots PK so subsequent
runs are idempotent and self-healing for late-arriving data).

Metric set chosen from the YT deep audit (DBH context):
  - Channel is functionally a paid asset (98% of views come from ADVERTISING) →
    traffic_source breakdown is the headline tile, not raw view counts.
  - Top videos by views surface the TV-commercial proxy (172K-view asset).
  - Subscriber gain/loss is small but tracked for hygiene.

Schema written to metric_snapshots (platform='yt'):
  metric                                dimension
  ──────                                ─────────
  views                                 (null)            — daily total
  watch_time_minutes                    (null)
  average_view_duration_seconds         (null)            — daily avg, written as-is
  subscribers_gained                    (null)
  subscribers_lost                      (null)
  views                                 traffic_source:<TYPE>
  views                                 video:<TITLE>
  average_view_duration_seconds         video:<TITLE>     — single snapshot per video, dated end-of-window

YT Analytics lags 1-2 days; we look back 32 days and pull through (today - 2).
"""
from __future__ import annotations

import datetime as dt
import sys

from yt.client import get_service, get_channel_id
from ingest.core import Row, run_logger, write_rows, neon_conn

PLATFORM = "yt"
LOOKBACK_DAYS_DEFAULT = 30
ANALYTICS_LAG_DAYS = 2  # YT Analytics doesn't backfill the most-recent 1-2 days
TOP_VIDEO_LIMIT = 5


def _query_report(
    yta_svc,
    channel_id: str,
    start: dt.date,
    end: dt.date,
    *,
    dimensions: str,
    metrics: str,
    sort: str | None = None,
    filters: str | None = None,
    max_results: int = 1000,
) -> list[dict]:
    """Thin wrapper around yta.reports().query() that returns list-of-dicts."""
    kwargs = {
        "ids": f"channel=={channel_id}",
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": dimensions,
        "metrics": metrics,
        "maxResults": max_results,
    }
    if sort:
        kwargs["sort"] = sort
    if filters:
        kwargs["filters"] = filters
    resp = yta_svc.reports().query(**kwargs).execute()
    cols = [c["name"] for c in resp.get("columnHeaders", [])]
    return [dict(zip(cols, row)) for row in (resp.get("rows") or [])]


def _parse_date(s: str) -> dt.date:
    return dt.datetime.strptime(s, "%Y-%m-%d").date()


def _video_title_map(data_svc, video_ids: list[str]) -> dict[str, str]:
    """Resolve YT video IDs → titles. Batch 50 per Data API call."""
    out: dict[str, str] = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        if not batch:
            continue
        resp = data_svc.videos().list(part="snippet", id=",".join(batch)).execute()
        for v in resp.get("items", []):
            vid = v.get("id")
            title = ((v.get("snippet") or {}).get("title")) or vid
            out[vid] = title
    return out


def main(days: int = LOOKBACK_DAYS_DEFAULT) -> int:
    with run_logger(PLATFORM) as state:
        channel_id = get_channel_id()
        if not channel_id:
            raise RuntimeError(
                "youtube_channel_id missing from google-ads.yaml — add it and re-run."
            )
        yta = get_service("analytics")
        data = get_service("data")

        end = dt.date.today() - dt.timedelta(days=ANALYTICS_LAG_DAYS)
        start = end - dt.timedelta(days=days)

        rows: list[Row] = []

        # ── 1. Daily channel totals (no dimension other than day) ─────────────
        daily = _query_report(
            yta, channel_id, start, end,
            dimensions="day",
            metrics=(
                "views,estimatedMinutesWatched,averageViewDuration,"
                "subscribersGained,subscribersLost"
            ),
            sort="day",
        )
        for r in daily:
            d = _parse_date(r["day"])
            rows.append(Row(PLATFORM, "views",                          d, r.get("views") or 0))
            rows.append(Row(PLATFORM, "watch_time_minutes",             d, r.get("estimatedMinutesWatched") or 0))
            rows.append(Row(PLATFORM, "average_view_duration_seconds",  d, r.get("averageViewDuration") or 0))
            rows.append(Row(PLATFORM, "subscribers_gained",             d, r.get("subscribersGained") or 0))
            rows.append(Row(PLATFORM, "subscribers_lost",               d, r.get("subscribersLost") or 0))

        # ── 2. Daily views × traffic source type ─────────────────────────────
        # YT Analytics needs sort on a metric here; we'll fan back out to per-day rows.
        traffic = _query_report(
            yta, channel_id, start, end,
            dimensions="day,insightTrafficSourceType",
            metrics="views",
            sort="day",
        )
        for r in traffic:
            d = _parse_date(r["day"])
            src = r.get("insightTrafficSourceType") or "UNKNOWN"
            rows.append(Row(
                PLATFORM, "views", d, r.get("views") or 0,
                dimension=f"traffic_source:{src}",
            ))

        # ── 3. Top 5 videos by views (window total) — daily breakdown ────────
        # Step 3a: rank top videos in the window.
        top = _query_report(
            yta, channel_id, start, end,
            dimensions="video",
            metrics="views,averageViewDuration",
            sort="-views",
            max_results=TOP_VIDEO_LIMIT,
        )
        top_ids = [r["video"] for r in top if r.get("video")]
        title_map = _video_title_map(data, top_ids) if top_ids else {}

        if top_ids:
            # Step 3b: per-day views per top video (one filter call per video — small N).
            for vid in top_ids:
                title = title_map.get(vid, vid)
                # YT Analytics title can include commas/colons that would corrupt our
                # `video:<title>` parsing downstream; collapse them.
                clean_title = title.replace(":", " ").replace("|", " ").strip()[:120]
                daily_v = _query_report(
                    yta, channel_id, start, end,
                    dimensions="day",
                    metrics="views",
                    sort="day",
                    filters=f"video=={vid}",
                )
                for r in daily_v:
                    d = _parse_date(r["day"])
                    rows.append(Row(
                        PLATFORM, "views", d, r.get("views") or 0,
                        dimension=f"video:{clean_title}",
                        raw={"video_id": vid},
                    ))

            # Step 3c: avg view duration snapshot per top video, stamped at end-of-window
            for r in top:
                vid = r.get("video")
                if not vid:
                    continue
                title = title_map.get(vid, vid)
                clean_title = title.replace(":", " ").replace("|", " ").strip()[:120]
                rows.append(Row(
                    PLATFORM, "average_view_duration_seconds", end,
                    r.get("averageViewDuration") or 0,
                    dimension=f"video:{clean_title}",
                    raw={"video_id": vid},
                ))

        conn = neon_conn()
        try:
            n = write_rows(conn, rows)
            state["rows_written"] = n
            state["meta"] = {
                "days": days,
                "channel_id": channel_id,
                "top_video_count": len(top_ids),
                "window": {"start": start.isoformat(), "end": end.isoformat()},
            }
            print(f"yt: wrote {n} rows ({days}d, channel={channel_id})")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else LOOKBACK_DAYS_DEFAULT
    sys.exit(main(days))
