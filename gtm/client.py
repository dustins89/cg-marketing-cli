"""Google Tag Manager API v2 client factory.

Reuses the OAuth refresh token from ~/marketing-cli/google-ads.yaml. The token
must have the full GTM scope set (read+write+publish+delete + account/user mgmt)
— see `gads/auth.py`.
"""
from __future__ import annotations

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from gads.client import load_config


SCOPES = [
    "https://www.googleapis.com/auth/tagmanager.edit.containers",
    "https://www.googleapis.com/auth/tagmanager.edit.containerversions",
    "https://www.googleapis.com/auth/tagmanager.publish",
    "https://www.googleapis.com/auth/tagmanager.delete.containers",
    "https://www.googleapis.com/auth/tagmanager.manage.accounts",
    "https://www.googleapis.com/auth/tagmanager.manage.users",
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


def get_service():
    """Returns a googleapiclient tagmanager v2 service object."""
    return build("tagmanager", "v2", credentials=_credentials(), cache_discovery=False)


def get_account_id() -> str:
    cfg = load_config()
    aid = cfg.get("gtm_account_id")
    if not aid:
        raise RuntimeError(
            "gtm_account_id missing from google-ads.yaml. Run `gtm accounts` "
            "to list accounts you have access to, then add the numeric ID."
        )
    return str(aid)


def get_container_id() -> str:
    cfg = load_config()
    cid = cfg.get("gtm_container_id")
    if not cid:
        raise RuntimeError(
            "gtm_container_id missing from google-ads.yaml. Run `gtm containers` "
            "to list containers in your account, then add the numeric ID."
        )
    return str(cid)


def container_path(account_id: str, container_id: str) -> str:
    return f"accounts/{account_id}/containers/{container_id}"


def workspace_path(account_id: str, container_id: str, workspace_id: str) -> str:
    return f"{container_path(account_id, container_id)}/workspaces/{workspace_id}"
