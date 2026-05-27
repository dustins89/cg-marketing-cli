"""Ingest Google Business Profile performance metrics into Neon."""
from __future__ import annotations

import datetime as dt
import sys
from googleapiclient.errors import HttpError

from gbp import client as gbp_client
from gbp import pull

from ingest.core import Row, run_logger, write_rows, neon_conn

PLATFORM = "gbp"
LOOKBACK_DAYS_DEFAULT = 35

# Map GBP metric names to our internal naming
METRIC_MAP = {
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH": "search_impressions",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH":  "search_impressions",
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS":   "maps_impressions",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS":    "maps_impressions",
    "CALL_CLICKS":                         "call_clicks",
    "WEBSITE_CLICKS":                      "website_clicks",
    "BUSINESS_DIRECTION_REQUESTS":         "direction_requests",
    "BUSINESS_CONVERSATIONS":              "conversations",
}


def main(days: int = LOOKBACK_DAYS_DEFAULT) -> int:
    with run_logger(PLATFORM) as state:
        loc = gbp_client.get_location_id()
        if not loc:
            # GBP not configured (locations unverified, yaml key missing, etc).
            # Don't crash the workflow — record the skip and exit 0.
            print("gbp_location_id not configured in google-ads.yaml — skipping GBP ingest")
            state["status"] = "ok"
            state["meta"] = {"skipped": "gbp_location_id not configured"}
            return 0
        perf_svc = gbp_client.get_service("performance")
        ts = pull.pull_performance(perf_svc, loc, days)

        # ts is list of {date, BUSINESS_IMPRESSIONS_DESKTOP_MAPS, …}
        # Sum desktop + mobile within each metric family.
        rows: list[Row] = []
        for r in ts:
            d = dt.date.fromisoformat(r["date"])
            collapsed: dict[str, float] = {}
            for src, dst in METRIC_MAP.items():
                collapsed[dst] = collapsed.get(dst, 0) + float(r.get(src, 0) or 0)
            for metric, value in collapsed.items():
                rows.append(Row(PLATFORM, metric, d, value))

        # Reviews — single point-in-time average (not a daily series)
        acct = gbp_client.get_account_id()
        try:
            if acct:
                review_rows = pull.pull_reviews(acct, loc, max_pages=20)
                if review_rows:
                    avg = sum(_star_to_int(r.get("starRating")) for r in review_rows) / len(review_rows)
                    today = dt.date.today()
                    rows.append(Row(PLATFORM, "review_rating_avg", today, round(avg, 2)))
                    rows.append(Row(PLATFORM, "review_count_total", today, float(len(review_rows))))
        except Exception as e:
            print(f"gbp reviews skipped (likely v4 allowlist not granted): {e}", file=sys.stderr)

        # Search keywords — what people typed before the GBP appeared (last ~30d).
        # API returns monthly buckets; we pull the most-recent month and stamp at today.
        # Requires the GBP to be verified — unverified locations 404.
        try:
            kw_rows = pull.pull_search_keywords(perf_svc, loc, months_back=1)
            today = dt.date.today()
            # Collapse to most-recent (year, month) bucket per keyword.
            by_kw: dict[str, int] = {}
            most_recent: tuple[int, int] | None = None
            for kw in kw_rows:
                ym = (kw.get("year") or 0, kw.get("month") or 0)
                if most_recent is None or ym > most_recent:
                    most_recent = ym
            for kw in kw_rows:
                ym = (kw.get("year") or 0, kw.get("month") or 0)
                if ym != most_recent:
                    continue
                term = (kw.get("keyword") or "").strip()
                if not term:
                    continue
                by_kw[term] = by_kw.get(term, 0) + int(kw.get("impressions") or 0)
            for term, imps in by_kw.items():
                rows.append(Row(PLATFORM, "gbp_search_count", today, float(imps),
                                dimension=f"keyword:{term[:200]}"))
        except HttpError as e:
            # 404 = unverified location (API hides search keywords). Log and skip.
            status = getattr(getattr(e, "resp", None), "status", None)
            print(f"gbp search-keywords skipped (HTTP {status} — likely "
                  f"unverified GBP): {e}", file=sys.stderr)
        except Exception as e:
            print(f"gbp search-keywords skipped: {e}", file=sys.stderr)

        # Local posts — view/click counts where exposed by the legacy v4 API.
        # Allowlist-gated; gracefully no-op if 403.
        try:
            if acct:
                posts = pull.pull_local_posts(acct, loc, max_pages=10)
                today = dt.date.today()
                for p in posts:
                    name = p.get("name") or ""
                    # name = 'accounts/X/locations/Y/localPosts/<id>' — keep last seg
                    post_id = name.rsplit("/", 1)[-1] if name else ""
                    if not post_id:
                        continue
                    # Use summary as title proxy (Local Posts have no `title` field
                    # except for events — fall back to event_title when present).
                    title = (p.get("event_title") or p.get("summary") or "").strip()
                    title_safe = title[:120].replace("|", " ").replace("\n", " ")
                    dim = f"post:{post_id}|post_title:{title_safe}"
                    # The legacy `localPosts.list` response does not include
                    # insights — surface a 1 per post as `post_count` so the UI
                    # at least lists them. View/click metrics only land if a
                    # future allowlist exposes them via `reportInsights`.
                    rows.append(Row(PLATFORM, "post_views", today, 0.0, dimension=dim))
                    rows.append(Row(PLATFORM, "post_clicks", today, 0.0, dimension=dim))
        except RuntimeError as e:
            # legacy_get raises RuntimeError on 403 PERMISSION_DENIED
            print(f"gbp local-posts skipped (v4 allowlist not granted): {e}", file=sys.stderr)
        except Exception as e:
            print(f"gbp local-posts skipped: {e}", file=sys.stderr)

        # Q&A — count of questions asked on the listing.
        try:
            qa_svc = gbp_client.get_service("qa")
            qa_rows = pull.pull_qna(qa_svc, loc)
            today = dt.date.today()
            rows.append(Row(PLATFORM, "qna_question_count", today, float(len(qa_rows))))
        except HttpError as e:
            status = getattr(getattr(e, "resp", None), "status", None)
            print(f"gbp Q&A skipped (HTTP {status} — likely unverified GBP): {e}",
                  file=sys.stderr)
        except Exception as e:
            print(f"gbp Q&A skipped: {e}", file=sys.stderr)

        conn = neon_conn()
        try:
            n = write_rows(conn, rows)
            state["rows_written"] = n
            state["meta"] = {"days": days, "location": loc}
            print(f"gbp: wrote {n} rows ({days}d)")
        finally:
            conn.close()
    return 0


def _star_to_int(s) -> int:
    """CallRail-style starRating is 'FIVE' / 'FOUR' / etc."""
    mapping = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}
    if isinstance(s, int):
        return s
    return mapping.get(str(s).upper(), 0)


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else LOOKBACK_DAYS_DEFAULT
    sys.exit(main(days))
