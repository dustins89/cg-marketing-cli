"""Crazy Egg API v2 client.

Auth scheme: HMAC-SHA256. For each non-status request:
    1. Concat each param as f"{name}{value}"
    2. Sort the resulting strings alphabetically
    3. Concat them into one string
    4. HMAC-SHA256 with the API secret as the key, hex digest
    5. Send as `signed=<digest>` query param

Credentials live in ~/marketing-cli/google-ads.yaml under
`crazyegg_api_key` + `crazyegg_api_secret`.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any

import requests

from gads.client import load_config


BASE_URL = "https://app.crazyegg.com/api/v2"


def _credentials() -> tuple[str, str]:
    cfg = load_config()
    key = cfg.get("crazyegg_api_key")
    secret = cfg.get("crazyegg_api_secret")
    if not key or not secret:
        raise RuntimeError(
            "crazyegg_api_key / crazyegg_api_secret missing from google-ads.yaml. "
            "Get them from Crazy Egg → Site Settings → API Keys."
        )
    return str(key), str(secret)


def _sign(params: dict[str, Any], secret: str) -> str:
    """Build the HMAC-SHA256 signature per Crazy Egg's scheme."""
    parts = sorted(f"{k}{v}" for k, v in params.items())
    content = "".join(parts).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), content, hashlib.sha256).hexdigest()


def _signed_params(params: dict[str, Any] | None = None) -> dict[str, Any]:
    key, secret = _credentials()
    p = dict(params or {})
    p["api_key"] = key
    p["signed"] = _sign(p, secret)
    return p


def request(method: str, path: str, *, params: dict | None = None,
            data: dict | None = None, signed: bool = True) -> dict:
    """Make an authenticated Crazy Egg API call. Returns parsed JSON.

    For POST/PUT, form fields are signed alongside query params (Crazy Egg signs
    every request variable regardless of where it lives).
    """
    url = f"{BASE_URL}{path}"
    if not signed:
        resp = requests.request(method, url, params=params, data=data, timeout=30)
    else:
        # All variables (query + form) participate in the signature.
        all_params = dict(params or {})
        all_params.update(data or {})
        signed_all = _signed_params(all_params)
        if method.upper() in ("GET", "DELETE"):
            resp = requests.request(method, url, params=signed_all, timeout=30)
        else:
            resp = requests.request(method, url, data=signed_all, timeout=30)
    resp.raise_for_status()
    return resp.json()
