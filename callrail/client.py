"""CallRail v3 API client.

Auth: API key (long-lived). Stored in ~/marketing-cli/google-ads.yaml under
`callrail_api_key`. Mint or rotate at CallRail → Settings → Integrations → API.

Docs: https://apidocs.callrail.com/
Auth header format: Authorization: Token token="<KEY>"
"""
from __future__ import annotations

from typing import Iterator

import requests

from gads.client import load_config


BASE_URL = "https://api.callrail.com/v3"
DEFAULT_PER_PAGE = 250  # CallRail max
TIMEOUT_SECONDS = 30


def _api_key() -> str:
    cfg = load_config()
    key = cfg.get("callrail_api_key")
    if not key:
        raise RuntimeError(
            "callrail_api_key missing from google-ads.yaml. "
            "Create a key at CallRail → Settings → Integrations → API, "
            "then add `callrail_api_key: \"<KEY>\"` to ~/marketing-cli/google-ads.yaml."
        )
    return str(key)


def _headers() -> dict:
    return {
        "Authorization": f'Token token="{_api_key()}"',
        "Accept": "application/json",
    }


def _raise_for(resp: requests.Response) -> None:
    if resp.ok:
        return
    if resp.status_code == 401:
        raise RuntimeError(
            "CallRail 401 Unauthorized — callrail_api_key in google-ads.yaml "
            "is missing, invalid, or revoked."
        )
    if resp.status_code == 403:
        raise RuntimeError(
            "CallRail 403 Forbidden — key works but lacks permission for "
            f"{resp.url}. Check the key's account scope in CallRail."
        )
    if resp.status_code == 429:
        raise RuntimeError(
            "CallRail 429 rate-limited. Wait a minute and retry, or lower "
            "the date window."
        )
    raise RuntimeError(
        f"CallRail {resp.status_code} on {resp.url}: {resp.text[:300]}"
    )


def get(path: str, params: dict | None = None) -> dict:
    """Single GET. `path` is relative, e.g. 'a.json' or f'a/{aid}/calls.json'."""
    url = f"{BASE_URL}/{path.lstrip('/')}"
    resp = requests.get(url, headers=_headers(), params=params or {}, timeout=TIMEOUT_SECONDS)
    _raise_for(resp)
    return resp.json()


def paginate(path: str, list_key: str, params: dict | None = None) -> Iterator[dict]:
    """Yield items across all pages of a CallRail list endpoint.

    `list_key` is the JSON key that holds the rows (e.g. 'calls', 'trackers',
    'accounts'). CallRail returns top-level pagination fields alongside the list.
    """
    p = dict(params or {})
    p.setdefault("per_page", DEFAULT_PER_PAGE)
    p.setdefault("page", 1)
    while True:
        body = get(path, p)
        for item in body.get(list_key, []) or []:
            yield item
        total_pages = int(body.get("total_pages") or 1)
        if p["page"] >= total_pages:
            return
        p["page"] += 1


def resolve_account_id(override: str | None = None) -> str:
    """Resolve the CallRail account id to use.

    Order: explicit override → `callrail_account_id` in yaml → first account
    returned by GET /v3/a.json (works for single-account setups like DBH).
    """
    if override:
        return str(override)
    cfg = load_config()
    if cfg.get("callrail_account_id"):
        return str(cfg["callrail_account_id"])
    body = get("a.json", {"per_page": 50})
    accts = body.get("accounts") or []
    if not accts:
        raise RuntimeError(
            "CallRail returned zero accounts for this key. Verify the key is "
            "attached to the right CallRail company."
        )
    return str(accts[0]["id"])
