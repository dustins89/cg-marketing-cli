"""Postalytics REST API v1 client.

Auth: HTTP Basic with the API key as the username, empty password.
Header: Authorization: Basic base64(apikey + ":")

Credentials live in ~/marketing-cli/google-ads.yaml under `postalytics_api_key`.

Base URL: https://api.postalytics.com/api/v1

The v1 send + read API is available on every Postalytics plan that exposes
the API key (Pro and up as of 2026-05). The webhooks API is gated to higher
tiers — this client does NOT use webhooks; it polls instead.
"""
from __future__ import annotations

import base64
from typing import Any

import requests

from gads.client import load_config


BASE_URL = "https://api.postalytics.com/api/v1"


def _api_key() -> str:
    cfg = load_config()
    key = cfg.get("postalytics_api_key")
    if not key:
        raise RuntimeError(
            "postalytics_api_key missing from google-ads.yaml. "
            "Get it from Postalytics dashboard → Account → API."
        )
    return str(key)


def _auth_header(key: str) -> str:
    return "Basic " + base64.b64encode(f"{key}:".encode("utf-8")).decode("ascii")


def request(method: str, path: str, *, params: dict | None = None,
            json_body: dict | None = None) -> Any:
    """Make an authenticated Postalytics API call. Returns parsed JSON.

    Path is appended to BASE_URL (include leading slash).
    """
    url = f"{BASE_URL}{path}"
    headers = {
        "Authorization": _auth_header(_api_key()),
        "Accept": "application/json",
    }
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    resp = requests.request(
        method, url, params=params, json=json_body, headers=headers, timeout=30
    )
    resp.raise_for_status()
    # Some endpoints return empty bodies on success
    if not resp.content:
        return {}
    return resp.json()
