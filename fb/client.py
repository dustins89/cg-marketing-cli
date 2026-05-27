"""Meta (Facebook) Marketing API client factory.

Auth: System User access token (long-lived, doesn't expire). Stored in
~/marketing-cli/google-ads.yaml under `fb_access_token`. See FACEBOOK_HANDOFF.md
Phase 0c for how to mint one.

API version is pinned via `fb_api_version` in the yaml — Meta deprecates
~quarterly, intentional updates only.
"""
from __future__ import annotations

from gads.client import load_config


def _config() -> dict:
    cfg = load_config()
    required = ("fb_access_token", "fb_app_id", "fb_app_secret")
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        raise RuntimeError(
            f"google-ads.yaml is missing {missing}. See ~/marketing-cli/FACEBOOK_HANDOFF.md "
            f"Phase 0 for how to gather these."
        )
    return cfg


def init_api():
    """Initialize the facebook_business SDK with credentials from yaml.
    Call before any FB SDK operation."""
    try:
        from facebook_business.api import FacebookAdsApi
    except ImportError as e:
        raise RuntimeError(
            "facebook-business is required. Run `pip install -e .` from ~/marketing-cli."
        ) from e

    cfg = _config()
    api_version = cfg.get("fb_api_version", "v23.0")
    FacebookAdsApi.init(
        app_id=cfg["fb_app_id"],
        app_secret=cfg["fb_app_secret"],
        access_token=cfg["fb_access_token"],
        api_version=api_version,
    )
    return FacebookAdsApi.get_default_api()


def get_ad_account_id() -> str:
    cfg = _config()
    aid = cfg.get("fb_ad_account_id")
    if not aid:
        raise RuntimeError(
            "fb_ad_account_id missing from google-ads.yaml. Format is 'act_NNNNNNNNNN' "
            "(keep the 'act_' prefix). See FACEBOOK_HANDOFF.md Phase 0a."
        )
    aid = str(aid)
    if not aid.startswith("act_"):
        aid = f"act_{aid}"
    return aid


def get_pixel_id() -> str:
    cfg = _config()
    pid = cfg.get("fb_pixel_id")
    if not pid:
        raise RuntimeError(
            "fb_pixel_id missing from google-ads.yaml. Find it in Business Manager → "
            "Data Sources, or read it from GTM tag #24."
        )
    return str(pid)


def get_business_id() -> str:
    cfg = _config()
    bid = cfg.get("fb_business_id")
    if not bid:
        raise RuntimeError(
            "fb_business_id missing from google-ads.yaml. Find it in Business Settings → URL "
            "(business_id=NNN)."
        )
    return str(bid)
