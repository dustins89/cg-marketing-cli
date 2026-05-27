"""Google Local Services Ads (LSA) API client.

Uses the existing OAuth refresh token from ~/marketing-cli/google-ads.yaml.
The token already has the `adwords` scope (LSA shares it).

The LSA API requires a separate developer token approval AND that the
authenticated user has access to a Local Services account. If you don't run
LSAs, this CLI will return empty results.

Reference: https://developers.google.com/local-services-ads/reference/rest
"""
from __future__ import annotations

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from gads.client import load_config


SCOPES = ["https://www.googleapis.com/auth/adwords"]


def _credentials() -> Credentials:
    cfg = load_config()
    missing = [k for k in ("client_id", "client_secret", "refresh_token") if not cfg.get(k)]
    if missing:
        raise RuntimeError(
            f"google-ads.yaml is missing {missing}. Run `gads auth init` first."
        )
    return Credentials(
        token=None,
        refresh_token=cfg["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        scopes=SCOPES,
    )


def get_service():
    return build("localservices", "v1", credentials=_credentials(), cache_discovery=False)


def get_account_id() -> str | None:
    """Returns the LSA customer ID (10 digits) if configured."""
    cfg = load_config()
    return cfg.get("lsa_customer_id") or cfg.get("customer_id")
