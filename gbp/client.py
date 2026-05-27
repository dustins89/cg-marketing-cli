"""Google Business Profile API client factories.

After Google split the legacy "Google My Business" v4 API into multiple
focused APIs in 2022, the modern surface is several REST APIs sharing a
single OAuth scope. We expose them as named services:

  - "account"     → mybusinessaccountmanagement.googleapis.com (list accounts)
  - "info"        → mybusinessbusinessinformation.googleapis.com (locations, attrs)
  - "performance" → businessprofileperformance.googleapis.com (daily metrics)
  - "qa"          → mybusinessqanda.googleapis.com (questions/answers)

Reuses OAuth refresh token from ~/marketing-cli/google-ads.yaml. The token
must have been minted with `https://www.googleapis.com/auth/business.manage`
in its scope list — re-run `gads auth init` after upgrading the SCOPES list
in gads/auth.py.

Reviews/posts/media still live on the legacy v4 API and require additional
allowlisting from Google; not exposed here yet.
"""
from __future__ import annotations

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build_from_document

from gads.client import load_config


SCOPES = ["https://www.googleapis.com/auth/business.manage"]

DISCOVERY_URLS = {
    "account": "https://mybusinessaccountmanagement.googleapis.com/$discovery/rest?version=v1",
    "info": "https://mybusinessbusinessinformation.googleapis.com/$discovery/rest?version=v1",
    "performance": "https://businessprofileperformance.googleapis.com/$discovery/rest?version=v1",
    "qa": "https://mybusinessqanda.googleapis.com/$discovery/rest?version=v1",
    "verifications": "https://mybusinessverifications.googleapis.com/$discovery/rest?version=v1",
}

# Legacy v4 API base — used for Reviews / Local Posts / Media via raw REST
# (no public discovery doc; Google gates these behind allowlisting).
LEGACY_V4_BASE = "https://mybusiness.googleapis.com/v4"


def access_token() -> str:
    """Mint a fresh access token from the configured refresh token.
    Used for direct REST calls to legacy v4 endpoints (reviews/posts/media)."""
    from google.auth.transport.requests import Request
    creds = _credentials()
    creds.refresh(Request())
    return creds.token


def legacy_get(path: str, params: dict | None = None) -> dict:
    """GET against the legacy v4 API. `path` is relative (no /v4/ prefix).

    Raises RuntimeError with a clear message if the API isn't allowlisted
    (Google returns 403 PERMISSION_DENIED with project_disabled or similar).
    """
    url = f"{LEGACY_V4_BASE}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {access_token()}",
               "Accept": "application/json"}
    resp = requests.get(url, headers=headers, params=params or {}, timeout=30)
    if resp.status_code == 403:
        raise RuntimeError(
            "GBP legacy v4 returned 403. Reviews/Posts/Media require allowlist "
            "approval — request access via the Google Cloud project's API quota "
            "page or https://support.google.com/business/contact/api_default."
        )
    resp.raise_for_status()
    return resp.json()


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


def get_service(api: str):
    """Build a service for one of the GBP sub-APIs.

    `api` ∈ {"account", "info", "performance", "qa"}. The discovery doc is
    fetched at runtime since these APIs aren't in the cached googleapiclient
    discovery index.
    """
    if api not in DISCOVERY_URLS:
        raise ValueError(f"Unknown GBP API '{api}'. Choose from: {list(DISCOVERY_URLS)}")
    resp = requests.get(DISCOVERY_URLS[api], timeout=10)
    resp.raise_for_status()
    return build_from_document(resp.text, credentials=_credentials())


def get_account_id() -> str | None:
    """Returns 'accounts/123456789' if configured."""
    return load_config().get("gbp_account_id")


def get_location_id() -> str | None:
    """Returns 'locations/123456789' if configured."""
    return load_config().get("gbp_location_id")
