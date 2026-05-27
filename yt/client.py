"""YouTube Data + Analytics API clients.

We expose two services:
  - "data"      → YouTube Data API v3 (channels, videos, playlists, search)
  - "analytics" → YouTube Analytics API v2 (watch time, retention, demographics)

Reuses OAuth refresh token from ~/marketing-cli/google-ads.yaml. The token
must have these scopes (full read+write+delete on YouTube Data; readonly on
YT Analytics — no write scope exists):
  - https://www.googleapis.com/auth/youtube
  - https://www.googleapis.com/auth/youtube.force-ssl
  - https://www.googleapis.com/auth/yt-analytics.readonly
"""
from __future__ import annotations

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from gads.client import load_config


SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
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


def get_service(api: str = "data"):
    """Build a YouTube service.

    api ∈ {"data", "analytics"}
    """
    if api == "data":
        return build("youtube", "v3", credentials=_credentials(), cache_discovery=False)
    if api == "analytics":
        return build("youtubeAnalytics", "v2", credentials=_credentials(), cache_discovery=False)
    raise ValueError(f"Unknown YouTube API '{api}'. Choose: data, analytics")


def get_channel_id() -> str | None:
    """Returns the configured channel ID (UC... format) if set in yaml."""
    return load_config().get("youtube_channel_id")
