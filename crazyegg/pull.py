"""Crazy Egg read commands — heatmap (snapshot) listing + detail."""
from __future__ import annotations

import datetime as dt

from .client import request


def status() -> dict:
    """API health check. Returns {'msg': 'OK'} when up."""
    return request("GET", "/status.json", signed=False)


def authenticate() -> dict:
    """Test signing implementation. Returns {'msg': 'OK'} when creds valid."""
    return request("GET", "/authenticate.json", params={"test": "value"})


def list_snapshots() -> list[dict]:
    """List all heatmaps (snapshots) in the account."""
    resp = request("GET", "/snapshots.json")
    snaps = resp if isinstance(resp, list) else resp.get("snapshots", []) or resp.get("data", [])
    return [_snapshot_row(s) for s in snaps]


def get_snapshot(snapshot_id: str) -> dict:
    return request("GET", f"/snapshot/{snapshot_id}.json", params={"id": snapshot_id})


def _snapshot_row(s: dict) -> dict:
    return {
        "id": s.get("id") or s.get("snapshot_id"),
        "name": s.get("name"),
        "source_url": s.get("source_url"),
        "status": s.get("status"),
        "visits": s.get("visits") or s.get("current_visits"),
        "max_visits": s.get("max_visits"),
        "pct_complete": _pct(s.get("visits") or s.get("current_visits"),
                              s.get("max_visits")),
        "starts_at": _ts(s.get("starts_at")),
        "expires_at": _ts(s.get("expires_at")),
        "device": s.get("device"),
        "description": (s.get("description") or "")[:120],
        "url_matching_rules": _format_matching_rules(s.get("url_matching_rules")),
        "sampling_ratio": s.get("sampling_ratio"),
        "screenshot_url": s.get("screenshot_url"),
        "thumbnail_url": s.get("thumbnail_url"),
        "heatmap_url": s.get("heatmap_url"),
        "scrollmap_url": s.get("scrollmap_url"),
        "confetti_url": s.get("confetti_url"),
        "overlay_url": s.get("overlay_url"),
        "list_url": s.get("list_url"),
        "created_at": _ts(s.get("created_at")),
        "updated_at": _ts(s.get("updated_at")),
    }


def _pct(num, denom) -> float | None:
    if not denom:
        return None
    try:
        return round(100 * float(num or 0) / float(denom), 1)
    except (TypeError, ValueError):
        return None


def _format_matching_rules(rules) -> str | None:
    """Reduce the verbose url_matching_rules object to a one-line summary."""
    if rules is None:
        return None
    if isinstance(rules, str):
        return rules[:160]
    if isinstance(rules, dict):
        bits = [f"u={rules.get('u')}"]
        if rules.get("o"):
            bits.append(f"o={rules['o']}")
        if rules.get("d"):
            bits.append(f"d={','.join(rules['d'])}")
        return " ".join(bits)
    return str(rules)[:160]


def list_snapshots_filtered(status: str | None = None,
                           device: str | None = None) -> list[dict]:
    """Snapshots with optional client-side filters by status / device."""
    rows = list_snapshots()
    if status:
        rows = [r for r in rows if (r.get("status") or "").lower() == status.lower()]
    if device:
        rows = [r for r in rows if (r.get("device") or "").lower() == device.lower()]
    return rows


def snapshot_summary() -> list[dict]:
    """Group snapshots by status + device — one row per combination.

    Useful for "how many heatmaps are stale" / "how many ran out of visits" tiles.
    """
    from collections import defaultdict
    rows = list_snapshots()
    by: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"count": 0, "visits_sum": 0, "max_visits_sum": 0}
    )
    for r in rows:
        key = (r.get("status") or "unknown", r.get("device") or "unknown")
        b = by[key]
        b["count"] += 1
        b["visits_sum"] += int(r.get("visits") or 0)
        b["max_visits_sum"] += int(r.get("max_visits") or 0)
    out = []
    for (status, device), b in by.items():
        out.append({
            "status": status,
            "device": device,
            "count": b["count"],
            "visits_sum": b["visits_sum"],
            "max_visits_sum": b["max_visits_sum"],
            "avg_pct_complete": _pct(b["visits_sum"], b["max_visits_sum"]),
        })
    out.sort(key=lambda r: (-r["count"], r["status"], r["device"]))
    return out


def _ts(value) -> str | None:
    if not value:
        return None
    try:
        return dt.datetime.fromtimestamp(int(value), tz=dt.timezone.utc).isoformat()
    except (TypeError, ValueError):
        return str(value)


COLUMNS = {
    "snapshots": ["id", "name", "source_url", "status", "visits", "max_visits",
                  "pct_complete", "starts_at", "expires_at", "device"],
    "snapshots-full": ["id", "name", "source_url", "status", "visits", "max_visits",
                       "pct_complete", "device", "sampling_ratio",
                       "starts_at", "expires_at", "url_matching_rules"],
    "summary": ["status", "device", "count", "visits_sum", "max_visits_sum",
                "avg_pct_complete"],
}
