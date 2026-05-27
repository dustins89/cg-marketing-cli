"""Ingest Google Ads metrics into Neon metric_snapshots.

Pulls (per day-segment GAQL):
  - campaign-level: cost_usd, impressions, clicks, conversions, ctr, cpa_usd,
    plus impression-share columns (search_is, top_is, abs_top_is,
    budget_lost_is, rank_lost_is) — audit-depth-v2 requirement.

Dimension shape: 'campaign:<name>' on campaign-level rows.
"""
from __future__ import annotations

import datetime as dt
import sys
from typing import Iterable

from gads.client import get_client, get_customer_id
from gads.format import micros_to_dollars
from gads.pull import (
    pull_change_history,
    pull_geo,
    pull_recommendations,
    pull_search_terms,
)

from ingest.core import Row, run_logger, write_rows, neon_conn


PLATFORM = "gads"
LOOKBACK_DAYS_DEFAULT = 35      # always overlap a bit for late-arriving conversions
SEARCH_TERMS_LOOKBACK_DAYS = 7  # weekly rollup for search terms (low daily volume)
SEARCH_TERM_MAX_LEN = 200       # truncate to keep dimension manageable
CHANGE_HISTORY_LOOKBACK_DAYS = 7
GEO_LOOKBACK_DAYS = 14
GEO_TOP_N = 20                  # top 20 geos by impressions (audit-context #A4)


def _pct(v) -> float | None:
    try:
        f = float(v)
        if f < 0:
            return None
        return round(f * 100, 3)
    except (TypeError, ValueError):
        return None


def gen_campaign_rows(client, customer_id: str, days: int) -> Iterable[Row]:
    today = dt.date.today()
    start = (today - dt.timedelta(days=days)).isoformat()
    end = today.isoformat()
    query = f"""
        SELECT
          segments.date,
          campaign.id,
          campaign.name,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value,
          metrics.ctr,
          metrics.search_impression_share,
          metrics.search_top_impression_share,
          metrics.search_absolute_top_impression_share,
          metrics.search_budget_lost_impression_share,
          metrics.search_rank_lost_impression_share
        FROM campaign
        WHERE segments.date BETWEEN '{start}' AND '{end}'
    """
    ga = client.get_service("GoogleAdsService")
    for r in ga.search(customer_id=customer_id, query=query):
        d = dt.date.fromisoformat(r.segments.date)
        dim = f"campaign:{r.campaign.name}"
        cost = micros_to_dollars(r.metrics.cost_micros)
        conv = float(r.metrics.conversions)
        clicks = int(r.metrics.clicks)
        impressions = int(r.metrics.impressions)
        # Emit one row per (date × campaign × metric)
        yield Row(PLATFORM, "cost_usd",    d, cost,          dim)
        yield Row(PLATFORM, "impressions", d, impressions,   dim)
        yield Row(PLATFORM, "clicks",      d, clicks,        dim)
        yield Row(PLATFORM, "conversions", d, conv,          dim)
        yield Row(PLATFORM, "conv_value_usd", d, float(r.metrics.conversions_value), dim)
        yield Row(PLATFORM, "ctr",         d, float(r.metrics.ctr or 0), dim)
        if conv > 0:
            yield Row(PLATFORM, "cpa_usd", d, round(cost / conv, 2), dim)
        # Impression share columns — only emit if value is non-null
        for src_field, metric_name in [
            ("search_impression_share",                "search_is"),
            ("search_top_impression_share",            "top_is"),
            ("search_absolute_top_impression_share",   "abs_top_is"),
            ("search_budget_lost_impression_share",    "budget_lost_is"),
            ("search_rank_lost_impression_share",      "rank_lost_is"),
        ]:
            v = _pct(getattr(r.metrics, src_field))
            if v is not None:
                yield Row(PLATFORM, metric_name, d, v, dim)

    # Also emit account-level rollups (dimension=None) so the overview tile can
    # read with a single dimensionLike=NULL query.
    # We do this with a second pass aggregating in Python — cheaper than
    # re-querying GAQL.


def gen_search_term_rows(client, customer_id: str,
                         days: int = SEARCH_TERMS_LOOKBACK_DAYS) -> list[Row]:
    """Pull search terms for the last N days, emit one row per (term,metric).

    Rollup-style: all rows stamped with today's date. Dimension shape:
      'search_term:<term>|campaign:<campaign_name>'
    Skips junk (cost <= 0.01 AND impressions <= 5).
    """
    raw = pull_search_terms(client, customer_id, days=days, since=None)
    today = dt.date.today()
    out: list[Row] = []
    for r in raw:
        cost = float(r.get("spend_usd") or 0)
        impressions = int(r.get("impressions") or 0)
        if cost <= 0.01 and impressions <= 5:
            continue
        term = (r.get("search_term") or "").strip()
        if not term:
            continue
        if len(term) > SEARCH_TERM_MAX_LEN:
            term = term[:SEARCH_TERM_MAX_LEN]
        campaign = (r.get("campaign_name") or "").strip()
        dim = f"search_term:{term}|campaign:{campaign}"
        clicks = int(r.get("clicks") or 0)
        conv = float(r.get("conversions") or 0)
        conv_value = float(r.get("conv_value_usd") or 0)
        out.append(Row(PLATFORM, "cost_usd",       today, cost,        dim))
        out.append(Row(PLATFORM, "impressions",    today, impressions, dim))
        out.append(Row(PLATFORM, "clicks",         today, clicks,      dim))
        out.append(Row(PLATFORM, "conversions",    today, conv,        dim))
        out.append(Row(PLATFORM, "conv_value_usd", today, conv_value,  dim))
    return out


def gen_recommendation_rows(client, customer_id: str) -> list[Row]:
    """Aggregate pending Google recommendations by type.

    Emits two metrics per type, dated today:
      - recommendation_count           value=<count of pending recs>
      - recommendation_impact_usd      value=<sum of potential - base cost>
                                       (positive = projected savings/lift)

    Dismissed recommendations are skipped — only pending ones count as
    "things Dustin hasn't acted on yet".
    """
    raw = pull_recommendations(client, customer_id)
    today = dt.date.today()
    by_type: dict[str, dict[str, float]] = {}
    for r in raw:
        if r.get("dismissed"):
            continue
        rtype = (r.get("type") or "UNKNOWN").strip() or "UNKNOWN"
        base_cost = float(r.get("base_cost_usd") or 0)
        potential_cost = float(r.get("potential_cost_usd") or 0)
        # Impact = lift if positive, savings if negative; we normalize to
        # |delta| so the tile shows "magnitude of opportunity"
        impact = abs(potential_cost - base_cost)
        slot = by_type.setdefault(rtype, {"count": 0.0, "impact": 0.0})
        slot["count"] += 1
        slot["impact"] += impact

    out: list[Row] = []
    for rtype, agg in by_type.items():
        dim = f"recommendation_type:{rtype}"
        out.append(Row(PLATFORM, "recommendation_count",      today, agg["count"],  dim))
        out.append(Row(PLATFORM, "recommendation_impact_usd", today, round(agg["impact"], 2), dim))
    return out


def gen_change_history_rows(client, customer_id: str,
                            days: int = CHANGE_HISTORY_LOOKBACK_DAYS) -> list[Row]:
    """Aggregate change events by (resource_type, user_email) for the window.

    Stamps all rows with today's date as a rolling weekly snapshot. Dimension:
      'change_type:<resource_type>|user:<user_email>'
    """
    raw = pull_change_history(client, customer_id, days=days, since=None)
    today = dt.date.today()
    counts: dict[tuple[str, str], int] = {}
    for r in raw:
        rtype = (r.get("resource_type") or "UNKNOWN").strip() or "UNKNOWN"
        user = (r.get("user_email") or "unknown").strip() or "unknown"
        key = (rtype, user)
        counts[key] = counts.get(key, 0) + 1

    out: list[Row] = []
    for (rtype, user), n in counts.items():
        dim = f"change_type:{rtype}|user:{user}"
        out.append(Row(PLATFORM, "change_count", today, float(n), dim))
    return out


def gen_geo_rows(client, customer_id: str,
                 days: int = GEO_LOOKBACK_DAYS,
                 top_n: int = GEO_TOP_N) -> list[Row]:
    """Geo performance rollup for the last N days.

    Audit context #A4: <your-city>-proper vs outlying spend imbalance —
    surface top-N geos by impressions so the dashboard can flag inverted
    bid logic. Dimension shape:
      'geo:<location_label>'
    where location_label = "<country_criterion_id>|<location_type>|<campaign>"
    (geographic_view returns ids, not names — best we can do without a
    separate geo_target_constant lookup).
    """
    raw = pull_geo(client, customer_id, days=days, since=None)
    today = dt.date.today()
    # Aggregate across campaigns so each geo target rolls up to one row.
    agg: dict[str, dict[str, float]] = {}
    for r in raw:
        country = str(r.get("country_criterion_id") or "unknown")
        loc_type = (r.get("location_type") or "UNKNOWN").strip() or "UNKNOWN"
        campaign = (r.get("campaign_name") or "").strip() or "(unknown)"
        label = f"{country}|{loc_type}|{campaign}"
        slot = agg.setdefault(label, {
            "impressions": 0.0, "clicks": 0.0, "cost_usd": 0.0,
            "conversions": 0.0,
        })
        slot["impressions"] += int(r.get("impressions") or 0)
        slot["clicks"]      += int(r.get("clicks") or 0)
        slot["cost_usd"]    += float(r.get("spend_usd") or 0)
        slot["conversions"] += float(r.get("conversions") or 0)

    # Keep top N by impressions
    top = sorted(agg.items(), key=lambda kv: kv[1]["impressions"], reverse=True)[:top_n]

    out: list[Row] = []
    for label, m in top:
        dim = f"geo:{label}"
        out.append(Row(PLATFORM, "cost_usd",    today, round(m["cost_usd"], 2), dim))
        out.append(Row(PLATFORM, "impressions", today, m["impressions"],         dim))
        out.append(Row(PLATFORM, "clicks",      today, m["clicks"],              dim))
        out.append(Row(PLATFORM, "conversions", today, round(m["conversions"], 2), dim))
    return out


def main(days: int = LOOKBACK_DAYS_DEFAULT) -> int:
    with run_logger(PLATFORM) as state:
        client = get_client()
        cid = get_customer_id()
        rows = list(gen_campaign_rows(client, cid, days))
        # Aggregate to platform-level (dimension=None) for headline tiles
        agg: dict[tuple[str, dt.date], float] = {}
        for r in rows:
            if r.metric in ("cost_usd", "impressions", "clicks", "conversions",
                            "conv_value_usd"):
                key = (r.metric, r.date)
                agg[key] = agg.get(key, 0) + float(r.value or 0)
        agg_rows = [
            Row(PLATFORM, metric, d, v, dimension=None)
            for (metric, d), v in agg.items()
        ]
        all_rows = rows + agg_rows

        # Search terms — additive, fault-isolated so a GAQL failure here does
        # not block the rest of the gads ingest.
        search_term_rows: list[Row] = []
        search_term_err: str | None = None
        try:
            search_term_rows = gen_search_term_rows(client, cid,
                                                    days=SEARCH_TERMS_LOOKBACK_DAYS)
            all_rows += search_term_rows
        except Exception as e:  # noqa: BLE001 — intentional broad catch
            search_term_err = f"{type(e).__name__}: {e}"
            print(f"gads: search-terms pull failed (continuing): {search_term_err}",
                  file=sys.stderr)

        # Recommendations — fault-isolated.
        rec_rows: list[Row] = []
        rec_err: str | None = None
        try:
            rec_rows = gen_recommendation_rows(client, cid)
            all_rows += rec_rows
        except Exception as e:  # noqa: BLE001
            rec_err = f"{type(e).__name__}: {e}"
            print(f"gads: recommendations pull failed (continuing): {rec_err}",
                  file=sys.stderr)

        # Change history (7d rolling) — fault-isolated.
        change_rows: list[Row] = []
        change_err: str | None = None
        try:
            change_rows = gen_change_history_rows(client, cid,
                                                  days=CHANGE_HISTORY_LOOKBACK_DAYS)
            all_rows += change_rows
        except Exception as e:  # noqa: BLE001
            change_err = f"{type(e).__name__}: {e}"
            print(f"gads: change-history pull failed (continuing): {change_err}",
                  file=sys.stderr)

        # Geo (14d rolling, top 20 by impressions) — fault-isolated.
        geo_rows: list[Row] = []
        geo_err: str | None = None
        try:
            geo_rows = gen_geo_rows(client, cid, days=GEO_LOOKBACK_DAYS,
                                    top_n=GEO_TOP_N)
            all_rows += geo_rows
        except Exception as e:  # noqa: BLE001
            geo_err = f"{type(e).__name__}: {e}"
            print(f"gads: geo pull failed (continuing): {geo_err}",
                  file=sys.stderr)

        conn = neon_conn()
        try:
            n = write_rows(conn, all_rows)
            state["rows_written"] = n
            state["meta"] = {
                "days": days,
                "campaign_rows": len(rows),
                "agg_rows": len(agg_rows),
                "search_term_rows": len(search_term_rows),
                "search_term_days": SEARCH_TERMS_LOOKBACK_DAYS,
                "search_term_error": search_term_err,
                "recommendation_rows": len(rec_rows),
                "recommendation_error": rec_err,
                "change_history_rows": len(change_rows),
                "change_history_days": CHANGE_HISTORY_LOOKBACK_DAYS,
                "change_history_error": change_err,
                "geo_rows": len(geo_rows),
                "geo_days": GEO_LOOKBACK_DAYS,
                "geo_top_n": GEO_TOP_N,
                "geo_error": geo_err,
            }
            print(f"gads: wrote {n} rows ({days}d, {len(agg_rows)} platform-level, "
                  f"{len(search_term_rows)} search-term, {len(rec_rows)} recs, "
                  f"{len(change_rows)} changes, {len(geo_rows)} geo)")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else LOOKBACK_DAYS_DEFAULT
    sys.exit(main(days))
