"""CallRail v3 pullers — read-only.

Uses server-side aggregation endpoints (`/calls/summary`, `/calls/timeseries`)
where available — much cheaper than downloading raw calls and aggregating in
Python, and required for windows larger than ~5k calls.

Field selections on the raw `/calls` endpoint are biased toward what the
marketing dashboard will surface. CallRail returns ~90 fields per call; this
is the working set. Add to `_CALL_FIELDS` if the dashboard grows.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from . import client as cr


# ─── date helper ──────────────────────────────────────────────────────────────

def _date_window(days: int | None, since: str | None,
                 until: str | None = None) -> tuple[str, str]:
    end = date.fromisoformat(until) if until else date.today()
    if since:
        start = date.fromisoformat(since)
    else:
        start = end - timedelta(days=days or 30)
    return start.isoformat(), end.isoformat()


def _date_params(days: int | None, since: str | None,
                 until: str | None = None) -> dict:
    start, finish = _date_window(days, since, until)
    return {"start_date": start, "end_date": finish}


def _filter_params(direction: str | None = None,
                   lead_status: str | None = None,
                   answer_status: str | None = None,
                   device: str | None = None,
                   tracker_id: str | None = None,
                   company_id: str | None = None,
                   tags: list[str] | None = None,
                   first_time_callers: bool | None = None) -> dict:
    """Build the common filter param dict. Caller drops any None values."""
    p: dict = {}
    if direction:
        p["direction"] = direction
    if lead_status:
        p["lead_status"] = lead_status
    if answer_status:
        p["answer_status"] = answer_status
    if device:
        p["device"] = device
    if tracker_id:
        # /calls accepts tracker_id; /summary and /timeseries want tracker_ids[]
        p["tracker_id"] = tracker_id
    if company_id:
        p["company_id"] = company_id
    if tags:
        # CallRail accepts repeated tags[]= params; requests handles list values.
        p["tags[]"] = tags
    if first_time_callers is not None:
        p["first_time_callers"] = "true" if first_time_callers else "false"
    return p


# ─── pull functions: discovery ───────────────────────────────────────────────

def pull_accounts() -> list[dict]:
    """List CallRail accounts visible to the key (usually just one)."""
    body = cr.get("a.json", {"per_page": 50})
    return [
        {
            "id": a.get("id"),
            "name": a.get("name"),
            "outbound_recording_enabled": a.get("outbound_recording_enabled"),
            "hipaa_account": a.get("hipaa_account"),
            "numeric_id": a.get("numeric_id"),
        }
        for a in (body.get("accounts") or [])
    ]


def pull_companies(account_id: str) -> list[dict]:
    """List companies (business entities owning trackers) in the account."""
    rows = []
    for c in cr.paginate(f"a/{account_id}/companies.json", list_key="companies"):
        rows.append({
            "id": c.get("id"),
            "name": c.get("name"),
            "status": c.get("status"),
            "time_zone": c.get("time_zone"),
            "created_at": c.get("created_at"),
            "callscribe_enabled": c.get("callscribe_enabled"),
        })
    return rows


def pull_trackers(account_id: str) -> list[dict]:
    """List all tracking numbers (active + disabled)."""
    rows = []
    for t in cr.paginate(f"a/{account_id}/trackers.json", list_key="trackers"):
        swap = t.get("swap_targets")
        rows.append({
            "id": t.get("id"),
            "name": t.get("name"),
            "type": t.get("type"),
            "tracking_number": t.get("tracking_number"),
            "destination_number": t.get("destination_number"),
            "status": t.get("status"),
            "swap_targets": ", ".join(swap) if isinstance(swap, list) else swap,
            "source": (t.get("source") or {}).get("name") if isinstance(t.get("source"), dict) else None,
            "company_name": t.get("company_name"),
        })
    return rows


def pull_users(account_id: str) -> list[dict]:
    """List users with access to the account."""
    rows = []
    for u in cr.paginate(f"a/{account_id}/users.json", list_key="users"):
        rows.append({
            "id": u.get("id"),
            "name": u.get("name"),
            "email": u.get("email"),
            "role": u.get("role"),
            "accepted": u.get("accepted"),
        })
    return rows


def pull_tags(account_id: str) -> list[dict]:
    """List tags (labels applied to calls/forms)."""
    rows = []
    for t in cr.paginate(f"a/{account_id}/tags.json", list_key="tags"):
        rows.append({
            "id": t.get("id"),
            "name": t.get("name"),
            "tag_level": t.get("tag_level"),
            "color": t.get("color"),
            "company_id": t.get("company_id"),
        })
    return rows


# ─── pull functions: raw calls ───────────────────────────────────────────────

# Working field set for raw /calls.json. Stays comprehensive enough to power
# any dashboard tile without a second round-trip. Expand if the dashboard needs
# more.
_CALL_FIELDS = [
    # basic
    "id", "direction", "start_time", "created_at", "duration",
    "answered", "call_type", "voicemail",
    # customer
    "customer_name", "customer_phone_number",
    "customer_city", "customer_state", "customer_country",
    # routing
    "tracking_phone_number", "business_phone_number", "source_name",
    "agent_email", "company_id", "company_name", "tracker_id",
    # attribution
    "source", "medium", "campaign", "keywords",
    "referrer_domain", "referring_url",
    "landing_page_url", "last_requested_url",
    # UTMs
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    # ad click IDs
    "gclid", "fbclid", "msclkid", "ga",
    # milestones (first_touch / lead_created / qualified / last_touch)
    "milestones",
    # recording + transcript
    "recording", "recording_duration", "recording_player",
    "transcription", "call_highlights", "call_summary",
    # conversation intelligence (premium)
    "sentiment", "speaker_percent", "keywords_spotted",
    # lead mgmt — note: lead_score_explanation not allowed via `fields=`
    "lead_status", "lead_score",
    "value", "note", "tags",
    "person_id", "good_lead_call_id", "good_lead_call_time",
    # session / device
    "device_type", "session_uuid",
    "first_call", "prior_calls", "total_calls",
    # visitor behavior — `integration_data` not allowed via `fields=` selector
    "keypad_entries", "zip_code", "custom",
    # spam flag (used by the SF intake spam gate)
    "spam",
    # timeline drill-in
    "timeline_url",
]


def pull_calls(account_id: str, days: int | None, since: str | None,
               until: str | None = None,
               direction: str | None = None,
               lead_status: str | None = None,
               answer_status: str | None = None,
               device: str | None = None,
               tracker_id: str | None = None,
               company_id: str | None = None,
               tags: list[str] | None = None) -> list[dict]:
    """Pull all calls in [since, until], paginated, with optional filters.

    Rows preserve `_CALL_FIELDS`. Sort: newest first.
    """
    params = {
        **_date_params(days, since, until),
        **_filter_params(direction=direction, lead_status=lead_status,
                         answer_status=answer_status, device=device,
                         tracker_id=tracker_id, company_id=company_id, tags=tags),
        "fields": ",".join(_CALL_FIELDS),
        "sort": "start_time",
        "order": "desc",
    }
    rows = []
    for c in cr.paginate(f"a/{account_id}/calls.json", list_key="calls", params=params):
        rows.append({k: c.get(k) for k in _CALL_FIELDS})
    return rows


# ─── pull functions: server-side aggregations ────────────────────────────────

def pull_summary(account_id: str, days: int | None, since: str | None,
                 **filters) -> list[dict]:
    """Server-side rollup — total/answered/missed/first-time/avg-duration/leads.

    Hits /calls/summary.json (no group_by) for the headline tile. Much cheaper
    than downloading raw calls.
    """
    params = {
        **_date_params(days, since),
        **_filter_params(**filters),
    }
    body = cr.get(f"a/{account_id}/calls/summary.json", params)
    tot = body.get("total_results") or {}
    start, end = _date_window(days, since)
    return [{
        "window": f"{start} → {end}",
        "total_calls": tot.get("total_calls", 0),
        "answered_calls": tot.get("answered_calls", 0),
        "missed_calls": tot.get("missed_calls", 0),
        "first_time_callers": tot.get("first_time_callers", 0),
        "leads": tot.get("leads", 0),
        "average_duration_seconds": tot.get("average_duration", 0),
        "formatted_average_duration": tot.get("formatted_average_duration"),
        "answered_pct": _pct(tot.get("answered_calls"), tot.get("total_calls")),
        "leads_pct": _pct(tot.get("leads"), tot.get("total_calls")),
    }]


_GROUP_BY_VALUES = ("source", "keywords", "campaign", "referrer",
                    "landing_page", "company", "company_id")


def pull_grouped(account_id: str, group_by: str,
                 days: int | None, since: str | None,
                 **filters) -> list[dict]:
    """Server-side rollup grouped by source/keywords/campaign/referrer/landing_page/company.

    Single endpoint feeds all the by-X views. Each row carries the group key
    plus the same metrics as /summary.
    """
    if group_by not in _GROUP_BY_VALUES:
        raise ValueError(f"group_by must be one of {_GROUP_BY_VALUES}, got {group_by!r}")
    params = {
        **_date_params(days, since),
        **_filter_params(**filters),
        "group_by": group_by,
    }
    body = cr.get(f"a/{account_id}/calls/summary.json", params)
    rows = []
    for r in body.get("grouped_results") or []:
        rows.append({
            group_by: r.get("key") or "(none)",
            "total_calls": r.get("total_calls", 0),
            "answered_calls": r.get("answered_calls", 0),
            "missed_calls": r.get("missed_calls", 0),
            "first_time_callers": r.get("first_time_callers", 0),
            "leads": r.get("leads", 0),
            "average_duration_seconds": r.get("average_duration", 0),
            "answered_pct": _pct(r.get("answered_calls"), r.get("total_calls")),
            "leads_pct": _pct(r.get("leads"), r.get("total_calls")),
        })
    rows.sort(key=lambda x: -x["total_calls"])
    return rows


def pull_by_number(account_id: str, days: int | None, since: str | None,
                   **filters) -> list[dict]:
    """Calls grouped by tracking number (which DNI number was dialed).

    The /summary endpoint does not support group_by=tracking_number, so this
    aggregates client-side over raw calls. Cheap at DBH scale (low-thousands
    of calls/month).
    """
    calls = pull_calls(account_id, days, since, **filters)
    by: dict[str, dict] = defaultdict(
        lambda: {"calls": 0, "answered": 0, "missed": 0, "spam": 0,
                 "first_time": 0, "leads": 0, "duration_sum": 0}
    )
    for c in calls:
        key = c.get("tracking_phone_number") or "(unknown)"
        b = by[key]
        b["calls"] += 1
        if c.get("answered"):
            b["answered"] += 1
        else:
            b["missed"] += 1
        if c.get("spam"):
            b["spam"] += 1
        if c.get("first_call"):
            b["first_time"] += 1
        if (c.get("lead_status") or "") in ("good_lead", "previously_marked_good_lead"):
            b["leads"] += 1
        b["duration_sum"] += int(c.get("duration") or 0)
    rows = []
    for num, b in by.items():
        n = b["calls"]
        rows.append({
            "tracking_number": num,
            "calls": n,
            "answered": b["answered"],
            "missed": b["missed"],
            "spam": b["spam"],
            "first_time_callers": b["first_time"],
            "leads": b["leads"],
            "answered_pct": _pct(b["answered"], n),
            "spam_pct": _pct(b["spam"], n),
            "average_duration_seconds": round(b["duration_sum"] / n, 1) if n else 0.0,
        })
    rows.sort(key=lambda r: -r["calls"])
    return rows


def pull_timeseries(account_id: str, days: int | None, since: str | None,
                    interval: str = "day", **filters) -> list[dict]:
    """Time-series — daily/weekly/monthly call totals from /calls/timeseries.

    Used by WoW/MoM/YoY trend tiles. Response is capped at 200 data points by
    CallRail — pick an interval appropriate for the window.

    fields: requesting all of these in one call keeps the response small but
    rich enough for trend tiles.
    """
    if interval not in ("hour", "day", "week", "month", "year"):
        raise ValueError(f"interval must be hour|day|week|month|year, got {interval!r}")
    params = {
        **_date_params(days, since),
        **_filter_params(**filters),
        "interval": interval,
        "fields": "total_calls,answered_calls,missed_calls,first_time_callers,leads,average_duration",
    }
    body = cr.get(f"a/{account_id}/calls/timeseries.json", params)
    rows = []
    for d in body.get("data") or []:
        rows.append({
            "date": d.get("date"),
            "total_calls": d.get("total_calls", 0),
            "answered_calls": d.get("answered_calls", 0),
            "missed_calls": d.get("missed_calls", 0),
            "first_time_callers": d.get("first_time_callers", 0),
            "leads": d.get("leads", 0),
            "average_duration_seconds": d.get("average_duration", 0),
        })
    return rows


# ─── pull functions: form submissions ────────────────────────────────────────

# Subset of form submission fields useful for the dashboard. CallRail returns
# more (custom form fields under `form_data`); we capture those raw in
# `form_data` so the ingester can fan them out.
_FORM_FIELDS = [
    "id", "person_id", "company_id", "company_name",
    "submitted_at", "created_at",
    "form_name", "form_url", "landing_page_url", "referrer", "referrer_domain",
    "source", "medium", "campaign", "keywords",
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "gclid", "fbclid", "msclkid", "ga",
    "customer_name", "customer_phone_number", "customer_email",
    "customer_city", "customer_state", "customer_country",
    "device_type", "session_uuid",
    "form_data", "tags", "lead_status", "value", "note",
    "milestones", "timeline_url",
]


def pull_form_submissions(account_id: str, days: int | None, since: str | None,
                          until: str | None = None,
                          **filters) -> list[dict]:
    """Pull CallRail-tracked web form submissions."""
    params = {
        **_date_params(days, since, until),
        **_filter_params(**filters),
        "fields": ",".join(_FORM_FIELDS),
    }
    rows = []
    for f in cr.paginate(f"a/{account_id}/form_submissions.json",
                         list_key="form_submissions", params=params):
        rows.append({k: f.get(k) for k in _FORM_FIELDS})
    return rows


# ─── helpers ─────────────────────────────────────────────────────────────────

def _pct(num, denom) -> float:
    n, d = int(num or 0), int(denom or 0)
    return round(100 * n / d, 1) if d else 0.0


# ─── column manifests for table rendering ────────────────────────────────────

COLUMNS = {
    "accounts": ["id", "name", "numeric_id", "outbound_recording_enabled", "hipaa_account"],
    "companies": ["id", "name", "status", "time_zone", "callscribe_enabled", "created_at"],
    "trackers": ["id", "name", "type", "tracking_number", "destination_number",
                 "status", "source", "company_name", "swap_targets"],
    "users": ["id", "name", "email", "role", "accepted"],
    "tags": ["id", "name", "tag_level", "color", "company_id"],
    "calls": ["start_time", "source", "medium", "campaign", "tracking_phone_number",
              "customer_phone_number", "customer_city", "customer_state",
              "duration", "answered", "spam", "first_call", "lead_status",
              "lead_score", "value", "gclid", "fbclid"],
    "summary": ["window", "total_calls", "answered_calls", "missed_calls",
                "first_time_callers", "leads", "answered_pct", "leads_pct",
                "formatted_average_duration"],
    "grouped": [  # generic; first column will be the group key (see cli.py)
        "total_calls", "answered_calls", "missed_calls",
        "first_time_callers", "leads", "answered_pct", "leads_pct",
        "average_duration_seconds",
    ],
    "by-number": ["tracking_number", "calls", "answered", "missed", "spam",
                  "first_time_callers", "leads", "answered_pct", "spam_pct",
                  "average_duration_seconds"],
    "timeseries": ["date", "total_calls", "answered_calls", "missed_calls",
                   "first_time_callers", "leads", "average_duration_seconds"],
    "forms": ["submitted_at", "form_name", "source", "medium", "campaign",
              "customer_name", "customer_phone_number", "customer_email",
              "landing_page_url", "lead_status", "gclid", "fbclid"],
}
