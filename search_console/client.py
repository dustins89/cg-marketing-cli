"""Search Console (Webmasters v3) client factory.

Reuses the OAuth refresh token from ~/marketing-cli/google-ads.yaml. The token
must have been minted with `https://www.googleapis.com/auth/webmasters` (full —
needed for sitemap submit/delete) in its scope list — see `gads/auth.py`.
"""
from __future__ import annotations

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from gads.client import load_config


SCOPES = ["https://www.googleapis.com/auth/webmasters"]


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
    """Returns a googleapiclient webmasters v3 service object."""
    return build("webmasters", "v3", credentials=_credentials(), cache_discovery=False)


def get_site_url() -> str:
    cfg = load_config()
    url = cfg.get("search_console_site_url")
    if not url:
        raise RuntimeError(
            "search_console_site_url missing from google-ads.yaml. Add the "
            "verified property string from Search Console — e.g. "
            "'sc-domain:YOUR_DOMAIN' or 'https://www.your-domain.com/'."
        )
    return str(url)
