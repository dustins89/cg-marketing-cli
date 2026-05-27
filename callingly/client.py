"""Callingly v1 API client — speed-to-lead call tracking for DBH.

Requires `callingly_api_key` in google-ads.yaml. Generate at
Settings → API Keys in the Callingly dashboard.

Docs: https://help.callingly.com/article/38-callingly-api-documentation

Key endpoints (verified against docs 2026-05-22):
  GET /v1/leads?start=YYYY-MM-DD&end=YYYY-MM-DD&phone_number=...
    - No pagination — single response for the date range
    - Returns leads with nested `calls` array
  GET /v1/calls?start=YYYY-MM-DD&end=YYYY-MM-DD&team_id=...&limit=10&page=1
    - Paginated with `limit` and `page`
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Iterator

import requests

from gads.client import load_config


BASE = "https://api.callingly.com/v1"


def _headers() -> dict[str, str]:
    cfg = load_config()
    token = cfg.get("callingly_api_key")
    if not token:
        raise RuntimeError(
            "callingly_api_key missing from google-ads.yaml. Generate one at "
            "Callingly → Settings → API Keys."
        )
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    r = requests.get(f"{BASE}{path}", headers=_headers(), params=params or {}, timeout=60)
    r.raise_for_status()
    return r.json()


def _items(data: Any) -> list[dict]:
    """Normalize either a bare list or {data: [...]} / {leads: [...]} shape."""
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("data", "leads", "calls", "results"):
            items = data.get(key)
            if isinstance(items, list):
                return [x for x in items if isinstance(x, dict)]
    return []


def leads(*, since: dt.datetime, until: dt.datetime) -> Iterator[dict]:
    """Pull leads created between `since` and `until` (inclusive dates).

    Per Callingly docs, /v1/leads uses `start=YYYY-MM-DD&end=YYYY-MM-DD` and
    returns the full set in one response (no pagination). Each lead includes
    a nested `calls` array.
    """
    params = {
        "start": since.date().isoformat(),
        "end":   until.date().isoformat(),
    }
    data = _get("/leads", params=params)
    yield from _items(data)


def calls(*, since: dt.datetime, until: dt.datetime,
          per_page: int = 100) -> Iterator[dict]:
    """Pull individual call events paginated. Use when you need per-call
    fidelity rather than per-lead rollups (e.g. agent attribution per attempt,
    talk time, transcripts)."""
    page = 1
    while page <= 500:  # 50k call safety cap
        data = _get("/calls", params={
            "start": since.date().isoformat(),
            "end":   until.date().isoformat(),
            "limit": per_page,
            "page":  page,
        })
        items = _items(data)
        if not items:
            return
        for c in items:
            yield c
        if len(items) < per_page:
            return
        page += 1


def agents() -> list[dict]:
    """List call agents. Used to attribute calls per rep.

    Callingly's /agents endpoint may not be public — falls back gracefully
    by returning empty list if the endpoint isn't available.
    """
    try:
        data = _get("/agents")
        return _items(data)
    except Exception:
        return []
