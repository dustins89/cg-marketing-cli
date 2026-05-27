"""Calendly v2 API client — booked phone consults for DBH.

Requires `calendly_api_key` (Personal Access Token, generated at
https://calendly.com/integrations/api_webhooks) in google-ads.yaml.

Optional: `calendly_organization_uri` — auto-discovered from /users/me if absent.

Docs: https://developer.calendly.com/api-docs
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Iterator

import requests

from gads.client import load_config


BASE = "https://api.calendly.com"


def _headers() -> dict[str, str]:
    cfg = load_config()
    token = cfg.get("calendly_api_key")
    if not token:
        raise RuntimeError(
            "calendly_api_key missing from google-ads.yaml. Generate a "
            "Personal Access Token at https://calendly.com/integrations/api_webhooks."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _get(path: str, params: dict[str, Any] | None = None) -> dict:
    r = requests.get(f"{BASE}{path}", headers=_headers(), params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def me() -> dict:
    """Current authenticated user — needed to find organization_uri."""
    return _get("/users/me").get("resource", {})


def organization_uri() -> str:
    cfg = load_config()
    if cfg.get("calendly_organization_uri"):
        return cfg["calendly_organization_uri"]
    return me().get("current_organization", "")


def scheduled_events(
    *,
    min_start_time: dt.datetime,
    max_start_time: dt.datetime,
    status: str | None = None,
    count: int = 100,
) -> Iterator[dict]:
    """Paginate over scheduled_events for the org in a time window.

    status: 'active' or 'canceled' (None = both)
    """
    org = organization_uri()
    params: dict[str, Any] = {
        "organization": org,
        "min_start_time": min_start_time.isoformat().replace("+00:00", "Z"),
        "max_start_time": max_start_time.isoformat().replace("+00:00", "Z"),
        "count": min(100, count),
        "sort": "start_time:asc",
    }
    if status:
        params["status"] = status
    next_page: str | None = None
    while True:
        if next_page:
            r = requests.get(next_page, headers=_headers(), timeout=30)
            r.raise_for_status()
            data = r.json()
        else:
            data = _get("/scheduled_events", params=params)
        for ev in data.get("collection", []):
            yield ev
        next_page = (data.get("pagination") or {}).get("next_page")
        if not next_page:
            break


def event_types() -> list[dict]:
    org = organization_uri()
    data = _get("/event_types", params={"organization": org, "active": "true", "count": 100})
    return data.get("collection", [])
