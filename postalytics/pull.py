"""Postalytics read commands — campaigns, per-campaign stats, events, audit.

Quirk to know: `GET /campaigns` (list) returns every campaign with ALL stat
fields zeroed. Only `GET /campaigns/{drop_id}` returns real numbers. So the
audit pulls each live campaign individually after the list call.
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable

from .client import request


# Postalytics enum decoders (observed via API responses; not in public docs)
STATUS_NAMES = {
    1: "Draft",
    2: "Pending",
    3: "Active",
    4: "Paused",
    5: "Stopped",
    6: "Completed",
}

CAMPAIGN_TYPE_NAMES = {
    1: "One-Shot",
    2: "Drip",
    3: "Triggered Drip",
}

CREATIVE_TYPE_NAMES = {
    1: "Postcard 6x9",
    6: "Postcard 6x11",
}


def list_campaigns() -> list[dict]:
    """List every campaign in the account.

    NOTE: stat fields (delivered/in_transit/returned/etc.) are zeroed in this
    response. Hit `get_campaign(drop_id)` for actual numbers.
    """
    rows = request("GET", "/campaigns") or []
    return [_campaign_row(c, with_stats=False) for c in rows]


def get_campaign(drop_id: int | str) -> dict | None:
    """Detail for a single campaign — INCLUDES real stat fields.

    The path param is the drop_id (NOT campaign_id). Returns the first row of
    the response array or None.
    """
    rows = request("GET", f"/campaigns/{drop_id}") or []
    if not rows:
        return None
    return _campaign_row(rows[0], with_stats=True)


def list_campaigns_with_stats(only_live: bool = False) -> list[dict]:
    """List endpoint + per-row stats backfill.

    Issues N+1 API calls — one for the list, then one per campaign. Costs ~1s
    per campaign serially. Use `only_live=True` to skip dead campaigns and cut
    the call count.
    """
    rows = list_campaigns()
    if only_live:
        rows = [r for r in rows if r.get("is_live_mode") == 1]
    out = []
    for r in rows:
        drop_id = r.get("drop_id")
        detail = get_campaign(drop_id) if drop_id else None
        out.append({**r, **(detail or {})})
    return out


def get_events(drop_id: int | str, *, page: int = 1, page_size: int = 100) -> list[dict]:
    """Page of events for a campaign.

    `dataid` in the event response is the per-contact id you'd use to look up
    a single recipient's events via `/campaigns/{drop_id}/events/{dataid}`.
    """
    resp = request("GET", f"/campaigns/{drop_id}/events",
                   params={"PageNumber": page, "PageSize": page_size}) or []
    return [_event_row(e) for e in resp]


def get_events_since(drop_id: int | str, since: dt.date,
                     max_pages: int = 50) -> list[dict]:
    """Walk pages newest→oldest until we cross `since` or hit `max_pages`.

    The events endpoint does NOT support a server-side date filter, so we
    paginate and filter client-side. Most-recent events come back first.
    """
    out = []
    for page in range(1, max_pages + 1):
        batch = get_events(drop_id, page=page, page_size=100)
        if not batch:
            break
        for e in batch:
            ed = _parse_event_date(e.get("event_date"))
            if ed is not None and ed.date() < since:
                return out
            out.append(e)
        if len(batch) < 100:
            break
    return out


def audit(only_live: bool = True) -> dict:
    """Account-level rollup — what the deep audit doc consumes.

    Returns:
      - campaigns: enriched list (live or all) with real stats
      - totals: summed delivery / in-flight / response counts
      - rates: derived delivery_rate, scan_rate, conversion_rate
      - flags: list of human-readable issues found
    """
    campaigns = list_campaigns_with_stats(only_live=only_live)
    totals = {
        "audience": 0,
        "delivered": 0,
        "processed_for_delivery": 0,
        "in_transit": 0,
        "in_local_area": 0,
        "returned": 0,
        "unique_visitors": 0,
        "pageviews": 0,
        "unique_pageviews": 0,
        "conversions": 0,
    }
    for c in campaigns:
        for k in totals:
            totals[k] += _int(c.get(k))
    rates = _derive_rates(totals)
    flags = _build_flags(campaigns, totals, rates)
    return {
        "generated_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(),
        "scope": "live" if only_live else "all",
        "campaigns": campaigns,
        "totals": totals,
        "rates": rates,
        "flags": flags,
    }


# ─── helpers ──────────────────────────────────────────────────────────────────

def _campaign_row(c: dict, *, with_stats: bool) -> dict:
    row = {
        "campaign_id": c.get("campaign_id"),
        "drop_id": c.get("drop_id"),
        "name": c.get("name"),
        "audience": c.get("audience"),
        "endpoint": c.get("endpoint"),
        "is_live_mode": c.get("is_live_mode"),
        "status_code": c.get("status"),
        "status": STATUS_NAMES.get(c.get("status"), c.get("status")),
        "campaign_type_code": c.get("campaign_type"),
        "campaign_type": CAMPAIGN_TYPE_NAMES.get(
            c.get("campaign_type"), c.get("campaign_type")),
        "creative_type_code": c.get("creative_type"),
        "creative_type": CREATIVE_TYPE_NAMES.get(
            c.get("creative_type"), c.get("creative_type")),
        "send_date": c.get("send_date"),
        "created_date": c.get("created_date"),
    }
    if with_stats:
        row.update({
            "delivered": c.get("delivered"),
            "processed_for_delivery": c.get("processed_for_delivery"),
            "in_transit": c.get("in_transit"),
            "in_local_area": c.get("in_local_area"),
            "returned": c.get("returned"),
            "unique_visitors": c.get("unique_visitors"),
            "pageviews": c.get("pageviews"),
            "unique_pageviews": c.get("unique_pageviews"),
            "conversions": c.get("conversions"),
        })
    return row


def _event_row(e: dict) -> dict:
    return {
        "dataid": e.get("dataid"),
        "event_date": e.get("event_date"),
        "event_name": e.get("event_name"),
        "first_name": e.get("first_name"),
        "last_name": e.get("last_name"),
        "address": e.get("address"),
        "city": e.get("city"),
        "state": e.get("state"),
        "zip": e.get("zip"),
        "metadata": e.get("metadata"),
    }


def _parse_event_date(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    # Format: "5/27/2026 8:49:11 AM"
    try:
        return dt.datetime.strptime(s.strip(), "%m/%d/%Y %I:%M:%S %p")
    except ValueError:
        try:
            return dt.datetime.strptime(s.strip(), "%m/%d/%Y %H:%M:%S")
        except ValueError:
            return None


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _pct(num, denom) -> float | None:
    if not denom:
        return None
    try:
        return round(100 * float(num or 0) / float(denom), 2)
    except (TypeError, ValueError):
        return None


def _derive_rates(t: dict) -> dict:
    in_flight = t["processed_for_delivery"] + t["in_transit"] + t["in_local_area"]
    accounted = t["delivered"] + in_flight + t["returned"]
    return {
        "in_flight_count": in_flight,
        "delivery_rate_pct": _pct(t["delivered"], accounted),
        "return_rate_pct": _pct(t["returned"], accounted),
        "in_flight_rate_pct": _pct(in_flight, accounted),
        "scan_rate_pct": _pct(t["unique_visitors"], t["delivered"]),
        "conversion_rate_pct": _pct(t["conversions"], t["delivered"]),
        "pageviews_per_visitor": _pct(t["pageviews"], t["unique_visitors"] or 1),
    }


def _build_flags(campaigns: Iterable[dict], totals: dict, rates: dict) -> list[str]:
    flags = []
    if totals["conversions"] == 0 and totals["delivered"] > 0:
        flags.append(
            f"NO CONVERSIONS tracked across {totals['delivered']} delivered "
            "pieces — pURL conversion tracking is not wired up. Without it, "
            "ROI is unmeasurable."
        )
    if rates.get("scan_rate_pct") is not None and rates["scan_rate_pct"] < 2:
        flags.append(
            f"Scan rate {rates['scan_rate_pct']}% is below the 2% direct-mail "
            "QR-code benchmark — postcard creative or CTA may be weak."
        )
    live_active = [c for c in campaigns if c.get("is_live_mode") == 1
                   and c.get("status_code") == 3]
    if len(live_active) > 1:
        flags.append(
            f"{len(live_active)} live+active campaigns running concurrently — "
            f"verify each is intentional: " +
            ", ".join(f"#{c['drop_id']} {c['name']!r}" for c in live_active)
        )
    if totals["returned"] > 0:
        return_rate = rates.get("return_rate_pct") or 0
        if return_rate > 5:
            flags.append(
                f"Return rate {return_rate}% is high — clean the address list "
                "or layer in BatchData address-correction before sending."
            )
    return flags


COLUMNS = {
    "campaigns": ["drop_id", "name", "status", "campaign_type", "creative_type",
                  "is_live_mode", "audience", "endpoint", "send_date"],
    "campaigns-with-stats": ["drop_id", "name", "is_live_mode", "audience",
                             "delivered", "in_transit", "returned",
                             "unique_visitors", "conversions"],
    "events": ["event_date", "event_name", "first_name", "last_name",
               "address", "city", "state", "zip", "dataid"],
    "totals": ["audience", "delivered", "processed_for_delivery", "in_transit",
               "in_local_area", "returned", "unique_visitors", "pageviews",
               "conversions"],
    "rates": ["delivery_rate_pct", "return_rate_pct", "in_flight_rate_pct",
              "scan_rate_pct", "conversion_rate_pct", "pageviews_per_visitor"],
}
