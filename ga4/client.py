"""GA4 Data API client factory.

Reuses the OAuth refresh token from ~/marketing-cli/google-ads.yaml. The token
must have `analytics.edit` (subsumes readonly) and optionally `analytics.manage.users`
for property user-permission edits — see `gads/auth.py`.
"""
from __future__ import annotations

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from gads.client import load_config


SCOPES = [
    # Data API requires `.readonly` explicitly — `.edit` does NOT subsume it.
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/analytics.edit",
    "https://www.googleapis.com/auth/analytics.manage.users",
]


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


def get_client() -> BetaAnalyticsDataClient:
    return BetaAnalyticsDataClient(credentials=_credentials())


def get_admin_service():
    """GA4 Admin API service (for keyEvents, conversions, etc.)."""
    return build("analyticsadmin", "v1beta", credentials=_credentials(), cache_discovery=False)


def get_property_id() -> str:
    cfg = load_config()
    pid = cfg.get("ga4_property_id")
    if not pid:
        raise RuntimeError(
            "ga4_property_id missing from google-ads.yaml. Add the numeric "
            "Property ID from GA4 → Admin → Property Settings."
        )
    return str(pid)
