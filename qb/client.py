"""QuickBooks Online API client with DB-persisted refresh tokens.

QB rotates the refresh token on every refresh call (Intuit security model),
so storing it in a static GH secret won't work — we persist it in the
`qb_credentials` table in Neon and update after every refresh.

Static config (does not rotate) lives in google-ads.yaml:
  qb_client_id
  qb_client_secret
  qb_environment        # 'production' (default) or 'sandbox'

Mutable config (refresh_token + realm_id) lives in qb_credentials table.
Bootstrap: run `python -m qb.auth_bootstrap` once to populate it.

Refresh tokens expire after ~100 days of disuse. With nightly ingest, that's
not a concern unless the workflow is paused.
"""
from __future__ import annotations

import base64
import datetime as dt
import os
from typing import Any

import requests

from gads.client import load_config


PRODUCTION_API = "https://quickbooks.api.intuit.com"
SANDBOX_API = "https://sandbox-quickbooks.api.intuit.com"
TOKEN_ENDPOINT = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
MINOR_VERSION = 70  # current stable minor version


def _api_base() -> str:
    cfg = load_config()
    env = (cfg.get("qb_environment") or "production").lower()
    return SANDBOX_API if env == "sandbox" else PRODUCTION_API


def _static_creds() -> tuple[str, str]:
    cfg = load_config()
    cid = cfg.get("qb_client_id")
    secret = cfg.get("qb_client_secret")
    if not cid or not secret:
        raise RuntimeError(
            "qb_client_id / qb_client_secret missing from google-ads.yaml. "
            "Create a QB Online connected app at developer.intuit.com → My Apps."
        )
    return cid, secret


def _db_conn():
    """Lazy import — keeps this module importable without psycopg installed."""
    from ingest.core import neon_conn
    return neon_conn()


def ensure_table() -> None:
    """Create qb_credentials if missing. Idempotent. Run by auth_bootstrap and
    on first ingest so we don't depend on a manual `psql -f sql/0006_*.sql`."""
    with _db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS qb_credentials (
              realm_id            text PRIMARY KEY,
              refresh_token       text NOT NULL,
              access_token        text,
              access_expires_at   timestamptz,
              refresh_expires_at  timestamptz,
              updated_at          timestamptz DEFAULT now()
            )
            """
        )
        conn.commit()


def load_db_creds() -> dict[str, Any] | None:
    """Pull the singleton (realm_id, refresh_token, access_token, expires)."""
    with _db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT realm_id, refresh_token, access_token,
                   access_expires_at, refresh_expires_at
              FROM qb_credentials
             ORDER BY updated_at DESC
             LIMIT 1
            """
        )
        return cur.fetchone()


def save_db_creds(*, realm_id: str, refresh_token: str,
                  access_token: str | None = None,
                  access_expires_at: dt.datetime | None = None,
                  refresh_expires_at: dt.datetime | None = None) -> None:
    """Upsert credentials. realm_id is the natural key."""
    with _db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO qb_credentials
              (realm_id, refresh_token, access_token,
               access_expires_at, refresh_expires_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (realm_id) DO UPDATE
              SET refresh_token = EXCLUDED.refresh_token,
                  access_token = EXCLUDED.access_token,
                  access_expires_at = EXCLUDED.access_expires_at,
                  refresh_expires_at = EXCLUDED.refresh_expires_at,
                  updated_at = now()
            """,
            (realm_id, refresh_token, access_token,
             access_expires_at, refresh_expires_at),
        )
        conn.commit()


def refresh_access_token() -> tuple[str, str]:
    """Exchange refresh_token for a fresh access_token.

    Returns (access_token, realm_id). Persists the rotated refresh_token to DB.
    Raises RuntimeError if no credentials are bootstrapped yet.
    """
    creds = load_db_creds()
    if not creds:
        raise RuntimeError(
            "No QB credentials in DB. Run `python -m qb.auth_bootstrap` once "
            "to authorize and persist tokens."
        )

    client_id, client_secret = _static_creds()
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    resp = requests.post(
        TOKEN_ENDPOINT,
        headers={
            "Authorization": f"Basic {basic}",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": creds["refresh_token"],
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"QB token refresh failed: {resp.status_code} {resp.text}")

    body = resp.json()
    now = dt.datetime.now(dt.timezone.utc)
    access_expires = now + dt.timedelta(seconds=int(body["expires_in"]) - 60)
    refresh_expires = now + dt.timedelta(seconds=int(body["x_refresh_token_expires_in"]) - 60)

    save_db_creds(
        realm_id=creds["realm_id"],
        refresh_token=body["refresh_token"],
        access_token=body["access_token"],
        access_expires_at=access_expires,
        refresh_expires_at=refresh_expires,
    )
    return body["access_token"], creds["realm_id"]


def get_access_token() -> tuple[str, str]:
    """Return a valid (access_token, realm_id), refreshing if needed."""
    creds = load_db_creds()
    if not creds:
        raise RuntimeError(
            "No QB credentials in DB. Run `python -m qb.auth_bootstrap` first."
        )
    now = dt.datetime.now(dt.timezone.utc)
    exp = creds.get("access_expires_at")
    if creds.get("access_token") and exp and exp > now:
        return creds["access_token"], creds["realm_id"]
    return refresh_access_token()


# ─── Reports API ────────────────────────────────────────────────────────────

def _report(report_name: str, params: dict[str, Any]) -> dict:
    access_token, realm_id = get_access_token()
    url = f"{_api_base()}/v3/company/{realm_id}/reports/{report_name}"
    resp = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        params={**params, "minorversion": MINOR_VERSION},
        timeout=60,
    )
    if resp.status_code == 401:
        # Token might have just rotated under us — force refresh and retry once
        access_token, realm_id = refresh_access_token()
        resp = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            params={**params, "minorversion": MINOR_VERSION},
            timeout=60,
        )
    resp.raise_for_status()
    return resp.json()


def profit_and_loss(start_date: dt.date, end_date: dt.date,
                    *, summarize_column_by: str = "Month") -> dict:
    """Profit & Loss report. summarize_column_by ∈ Month / Quarter / Year / Total."""
    return _report("ProfitAndLoss", {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "summarize_column_by": summarize_column_by,
        "accounting_method": "Accrual",
    })


def balance_sheet(as_of: dt.date,
                  *, summarize_column_by: str = "Month",
                  start_date: dt.date | None = None) -> dict:
    """Balance sheet snapshot. When summarize_column_by != 'Total', a date range
    yields one column per period (we use this for monthly cash trend)."""
    params: dict[str, Any] = {
        "end_date": as_of.isoformat(),
        "summarize_column_by": summarize_column_by,
        "accounting_method": "Accrual",
    }
    if start_date:
        params["start_date"] = start_date.isoformat()
    return _report("BalanceSheet", params)


# ─── Report row walking ─────────────────────────────────────────────────────

def walk_rows(report: dict):
    """Yield every leaf-or-summary row (recursive). QB reports nest rows
    arbitrarily deep; this flattens them so callers can filter by name."""
    rows = (report.get("Rows") or {}).get("Row") or []
    yield from _walk(rows)


def _walk(rows: list[dict]):
    for r in rows:
        # If this row has nested rows, yield them — but also the Summary if present
        nested = (r.get("Rows") or {}).get("Row")
        if nested:
            yield from _walk(nested)
            if "Summary" in r:
                yield {"_type": "Summary", "group": r.get("group"),
                       "header": r.get("Header"), "ColData": r["Summary"].get("ColData", [])}
        else:
            yield {"_type": r.get("type", "Data"), "group": r.get("group"),
                   "ColData": r.get("ColData", [])}


def column_dates(report: dict) -> list[dt.date | None]:
    """Return one date per column (None for non-period columns like 'Total')."""
    cols = (report.get("Columns") or {}).get("Column") or []
    dates: list[dt.date | None] = []
    for c in cols:
        # First column is row labels — skip
        meta = {m.get("Name"): m.get("Value") for m in (c.get("MetaData") or [])}
        end = meta.get("EndDate")
        if end:
            try:
                dates.append(dt.date.fromisoformat(end))
            except ValueError:
                dates.append(None)
        else:
            dates.append(None)
    return dates
