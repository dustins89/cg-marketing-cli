"""Ingest Meta (Facebook) Marketing API metrics into Neon."""
from __future__ import annotations

import datetime as dt
import sys

from fb.client import get_ad_account_id, init_api
from fb import pull

from ingest.core import Row, run_logger, write_rows, neon_conn

PLATFORM = "fb"
LOOKBACK_DAYS_DEFAULT = 35


def main(days: int = LOOKBACK_DAYS_DEFAULT) -> int:
    with run_logger(PLATFORM) as state:
        init_api()
        aid = get_ad_account_id()
        # Daily time-series (account level)
        ts = pull.pull_time_series(aid, days=days, since=None, level="account",
                                   time_increment=1)
        rows: list[Row] = []
        for r in ts:
            d = dt.date.fromisoformat(str(r["date_start"]))
            for metric_name, value_key in [
                ("spend_usd",          "spend_usd"),
                ("impressions",        "impressions"),
                ("reach",              "reach"),
                ("clicks",             "clicks"),
                ("ctr",                "ctr"),
                ("cpc",                "cpc"),
                ("cpm",                "cpm"),
                ("leads",              "leads"),
                ("purchases",          "purchases"),
                ("link_clicks",        "link_clicks"),
                ("landing_page_views", "landing_page_views"),
            ]:
                v = r.get(value_key)
                if v is not None:
                    rows.append(Row(PLATFORM, metric_name, d, float(v)))

        # Campaign-level daily for the by-campaign breakdown
        camp_ts = pull.pull_time_series(aid, days=days, since=None, level="campaign",
                                        time_increment=1)
        for r in camp_ts:
            d = dt.date.fromisoformat(str(r["date_start"]))
            cname = r.get("campaign_name") or "(unknown)"
            dim = f"campaign:{cname}"
            for metric_name, value_key in [
                ("spend_usd",   "spend_usd"),
                ("impressions", "impressions"),
                ("clicks",      "clicks"),
                ("leads",       "leads"),
            ]:
                v = r.get(value_key)
                if v is not None:
                    rows.append(Row(PLATFORM, metric_name, d, float(v), dim))

        # Publisher-platform breakdown for the "Audience Network waste" check
        try:
            pp = pull.pull_breakdown(aid, "publisher_platform", days=days, since=None,
                                     level="account")
            # pp doesn't carry per-date — store as a single "today" snapshot
            today = dt.date.today()
            for r in pp:
                plat = r.get("publisher_platform") or "(unknown)"
                rows.append(Row(PLATFORM, "spend_usd", today, float(r.get("spend_usd", 0) or 0),
                                dimension=f"publisher_platform:{plat}"))
        except Exception as e:
            print(f"fb breakdown publisher_platform skipped: {e}", file=sys.stderr)

        # Ad-creative performance — last 7d, top 50 by spend.
        # Surfaces ad-level CPL outliers (audit found 5x perf gap between identical-named ads).
        try:
            ads = pull.pull_ads(aid, days=7, since=None)
            ads_sorted = sorted(ads, key=lambda x: float(x.get("spend_usd", 0) or 0), reverse=True)[:50]
            # Fetch status per ad (insights endpoint doesn't carry it).
            statuses: dict[str, str] = {}
            try:
                from facebook_business.adobjects.ad import Ad
                for a in ads_sorted:
                    ad_id = a.get("ad_id")
                    if not ad_id:
                        continue
                    try:
                        info = Ad(fbid=ad_id).api_get(fields=["effective_status"])
                        statuses[ad_id] = info.get("effective_status") or "UNKNOWN"
                    except Exception:
                        statuses[ad_id] = "UNKNOWN"
            except Exception as e:
                print(f"fb ad status lookup skipped: {e}", file=sys.stderr)

            today = dt.date.today()
            for r in ads_sorted:
                ad_id = r.get("ad_id") or "(unknown)"
                ad_name = (r.get("ad_name") or "(unknown)").replace("|", "/")  # keep dimension parser safe
                status = statuses.get(ad_id, "UNKNOWN")
                dim = f"ad:{ad_id}|ad_name:{ad_name}|status:{status}"
                spend_v = float(r.get("spend_usd", 0) or 0)
                impressions_v = int(r.get("impressions", 0) or 0)
                clicks_v = int(r.get("clicks", 0) or 0)
                leads_v = float(r.get("leads", 0) or 0)
                ctr_v = float(r.get("ctr", 0) or 0)
                cpl_v = (spend_v / leads_v) if leads_v > 0 else None
                rows.append(Row(PLATFORM, "spend_usd",   today, spend_v,        dimension=dim))
                rows.append(Row(PLATFORM, "impressions", today, impressions_v,  dimension=dim))
                rows.append(Row(PLATFORM, "clicks",      today, clicks_v,       dimension=dim))
                rows.append(Row(PLATFORM, "ctr",         today, ctr_v,          dimension=dim))
                rows.append(Row(PLATFORM, "leads",       today, leads_v,        dimension=dim))
                if cpl_v is not None:
                    rows.append(Row(PLATFORM, "cpl",     today, cpl_v,          dimension=dim))
        except Exception as e:
            print(f"fb ad-creative perf skipped: {e}", file=sys.stderr)

        # Pixel event quality (EMQ scores per event) — last 7d.
        # Confirms CAPI hashed-PII fan-out is being matched server-side.
        try:
            from fb.client import get_pixel_id
            pid = get_pixel_id()
            eq = pull.pull_pixel_event_quality(pid, days=7, since=None)
            today = dt.date.today()
            # Multiple buckets per event — keep the highest (most-recent reliable) EMQ score.
            best: dict[str, float] = {}
            for r in eq:
                name = r.get("event_name")
                score = r.get("emq_score")
                if not name or score is None:
                    continue
                s = float(score)
                if name not in best or s > best[name]:
                    best[name] = s
            for name, score in best.items():
                rows.append(Row(PLATFORM, "emq_score", today, score,
                                dimension=f"event:{name}"))
            # Also emit a rollup (null dimension) so the KPI card averages cleanly.
            if best:
                avg = sum(best.values()) / len(best)
                rows.append(Row(PLATFORM, "emq_score", today, avg))
        except Exception as e:
            print(f"fb pixel EMQ skipped: {e}", file=sys.stderr)

        conn = neon_conn()
        try:
            n = write_rows(conn, rows)
            state["rows_written"] = n
            state["meta"] = {"days": days}
            print(f"fb: wrote {n} rows ({days}d)")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else LOOKBACK_DAYS_DEFAULT
    sys.exit(main(days))
