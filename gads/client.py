"""Google Ads client factory + config helpers.

google-ads.yaml lives at the project root (next to this package).
Loaded by GoogleAdsClient.load_from_storage(), which the SDK uses natively.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from google.ads.googleads.client import GoogleAdsClient


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "google-ads.yaml"


def config_path() -> Path:
    return CONFIG_PATH


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"{CONFIG_PATH} not found. Copy google-ads.yaml.example to "
            f"google-ads.yaml and fill in your credentials, then run `gads auth init`."
        )
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f) or {}


def save_config(cfg: dict) -> None:
    with CONFIG_PATH.open("w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    os.chmod(CONFIG_PATH, 0o600)


def get_client() -> GoogleAdsClient:
    """Return a configured GoogleAdsClient. Strips fields the SDK doesn't accept."""
    cfg = load_config()
    sdk_keys = {
        "developer_token",
        "client_id",
        "client_secret",
        "refresh_token",
        "login_customer_id",
        "use_proto_plus",
        "linked_customer_id",
        "json_key_file_path",
        "impersonated_email",
    }
    sdk_cfg = {k: v for k, v in cfg.items() if k in sdk_keys and v is not None}
    return GoogleAdsClient.load_from_dict(sdk_cfg)


def get_customer_id() -> str:
    cfg = load_config()
    cid = cfg.get("customer_id")
    if not cid:
        raise ValueError(
            "customer_id missing from google-ads.yaml. Add the 10-digit ID (no dashes)."
        )
    return str(cid).replace("-", "")
