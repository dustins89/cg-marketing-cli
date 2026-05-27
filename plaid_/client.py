"""Plaid API client — bank aggregation for the /finances dashboard.

Requires in google-ads.yaml:
  plaid_client_id          — Plaid client ID
  plaid_secret_production  — production secret (live banks)
  plaid_secret_sandbox     — sandbox secret (fake data for testing)
  plaid_env                — 'production' | 'sandbox'

Docs: https://plaid.com/docs/api
This is a thin requests-based wrapper — no plaid-python SDK dependency, so
the ingester stays light and the wire format stays explicit.

Naming note: the local module is `plaid_/` (trailing underscore) to avoid
clashing with the official `plaid-python` package namespace in case anyone
later wants to install it for advanced features.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

import requests

from gads.client import load_config


HOSTS = {
    "sandbox":     "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production":  "https://production.plaid.com",
}

# Default API version pinned. Update when migrating to a newer Plaid version.
PLAID_VERSION = "2020-09-14"


def _creds() -> tuple[str, str, str]:
    """Return (client_id, secret, env). Picks the right secret based on env."""
    cfg = load_config()
    cid = cfg.get("plaid_client_id")
    env = (cfg.get("plaid_env") or "production").lower()
    secret_key = "plaid_secret_sandbox" if env == "sandbox" else "plaid_secret_production"
    secret = cfg.get(secret_key) or cfg.get("plaid_secret")  # legacy fallback
    if not cid or not secret:
        raise RuntimeError(
            f"plaid_client_id and/or {secret_key} missing from google-ads.yaml. "
            "Get them at https://dashboard.plaid.com/team/keys."
        )
    return cid, secret, env


def _post(path: str, body: dict[str, Any]) -> dict:
    """POST to Plaid with the client_id/secret automatically injected."""
    cid, secret, env = _creds()
    host = HOSTS.get(env, HOSTS["production"])
    payload = {**body, "client_id": cid, "secret": secret}
    r = requests.post(
        f"{host}{path}",
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Plaid-Version": PLAID_VERSION,
        },
        timeout=30,
    )
    if not r.ok:
        # Surface Plaid error details — they include error_code + error_message
        try:
            err = r.json()
        except Exception:
            err = {"raw": r.text[:500]}
        raise RuntimeError(f"Plaid {path} {r.status_code}: {json.dumps(err)[:400]}")
    return r.json()


# ─── Link token (browser flow) ─────────────────────────────────────────────

def create_link_token(*, user_id: str = "dbh-singleuser",
                      products: list[str] | None = None,
                      country_codes: list[str] | None = None,
                      redirect_uri: str | None = None,
                      webhook: str | None = None,
                      access_token: str | None = None) -> dict:
    """Mint a link_token for a Plaid Link session.

    Pass `access_token` to re-authenticate an existing item (for update mode
    when consent expires).
    """
    body: dict[str, Any] = {
        "user": {"client_user_id": user_id},
        "client_name": "DBH Marketing Dashboard",
        "products": products or ["transactions"],
        "country_codes": country_codes or ["US"],
        "language": "en",
    }
    if redirect_uri:
        body["redirect_uri"] = redirect_uri
    if webhook:
        body["webhook"] = webhook
    if access_token:
        # Update mode — for refreshing consent on an existing item
        body["access_token"] = access_token
        body.pop("products", None)
    return _post("/link/token/create", body)


def exchange_public_token(public_token: str) -> dict:
    """Trade a Link public_token for a long-lived access_token + item_id."""
    return _post("/item/public_token/exchange", {"public_token": public_token})


# ─── Items / institutions ──────────────────────────────────────────────────

def get_item(access_token: str) -> dict:
    return _post("/item/get", {"access_token": access_token})


def get_institution(institution_id: str) -> dict:
    return _post("/institutions/get_by_id", {
        "institution_id": institution_id,
        "country_codes": ["US"],
    })


def remove_item(access_token: str) -> dict:
    return _post("/item/remove", {"access_token": access_token})


# ─── Accounts + Balances ──────────────────────────────────────────────────

def accounts_get(access_token: str) -> dict:
    return _post("/accounts/get", {"access_token": access_token})


def accounts_balance_get(access_token: str) -> dict:
    """Forces a balance refresh from the FI (rate-limited; use sparingly)."""
    return _post("/accounts/balance/get", {"access_token": access_token})


# ─── Transactions (sync endpoint, preferred) ──────────────────────────────

def transactions_sync(access_token: str, cursor: str | None = None,
                      count: int = 500) -> dict:
    """Incremental transaction sync.

    Returns {added, modified, removed, next_cursor, has_more}. Loop until
    has_more is false, passing the next_cursor back in.
    """
    body: dict[str, Any] = {"access_token": access_token, "count": count}
    if cursor:
        body["cursor"] = cursor
    return _post("/transactions/sync", body)


# ─── Webhook signature verification ────────────────────────────────────────

def webhook_jwt_key(key_id: str) -> dict:
    """Fetch a JWT verification key for incoming webhook signatures."""
    return _post("/webhook_verification_key/get", {"key_id": key_id})
