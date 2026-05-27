"""Ingest Plaid bank-aggregation data into Neon.

For each active row in `plaid_items`:
  1. Sync transactions via /transactions/sync (cursor pagination, loops until
     has_more=false). Upserts into finance_transactions, deletes removed ones,
     persists next_cursor + last_synced_at on the item.
  2. Pull a fresh balance snapshot via /accounts/balance/get and upsert into
     finance_balances (PK = account_id, today). Also refreshes account
     metadata (name, mask, subtype) in case it drifted.

After all items finish, writes three summary rows into metric_snapshots so
common dashboard widgets can read Plaid totals:
  - net_worth_usd            = assets - liabilities
  - total_assets_usd         = sum(depository + investment + other current)
  - total_liabilities_usd    = sum(credit + loan current)
   (using today's snapshot rows in finance_balances)

Errors are scoped per-item. A failed item flips plaid_items.status to
'error' (or 'login_required' if Plaid returned ITEM_LOGIN_REQUIRED) and
records error_code + error_message so the dashboard can prompt for a Link
update-mode re-auth. The run continues to the next item.

First-sync semantics: pass cursor=NULL on the first call; Plaid replies with
a full historical batch (typically 24mo) + a next_cursor.

Plaid /transactions/sync is cheap and idempotent — safe to run hourly.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import traceback

from plaid_ import client as plaid_client

from ingest.core import Row, neon_conn, run_logger, write_rows

PLATFORM = "plaid"

# Account-type buckets for net-worth rollups
ASSET_TYPES = {"depository", "investment", "other"}
LIABILITY_TYPES = {"credit", "loan"}


def _amount(txn: dict, key: str) -> float | None:
    v = txn.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _category(txn: dict) -> tuple[str | None, str | None]:
    """Return (primary, detailed). Prefer personal_finance_category;
    fall back to legacy `category` array (first element only)."""
    pfc = txn.get("personal_finance_category") or {}
    primary = pfc.get("primary")
    detailed = pfc.get("detailed")
    if not primary:
        legacy = txn.get("category") or []
        if legacy:
            primary = legacy[0]
    return primary, detailed


def _parse_date(s: str | None) -> dt.date | None:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return None


# ─── Transaction sync ──────────────────────────────────────────────────────

def _sync_transactions(conn, item: dict) -> dict:
    """Pull all pending changes for one item; upsert/delete in finance_transactions.

    Returns counters {added, modified, removed, pages, next_cursor}.
    Raises on Plaid error so the caller can mark the item.
    """
    access_token = item["access_token"]
    cursor = item.get("cursor")  # None on first sync

    added_n = modified_n = removed_n = pages = 0
    next_cursor = cursor

    while True:
        resp = plaid_client.transactions_sync(access_token, cursor=cursor)
        pages += 1

        added = resp.get("added") or []
        modified = resp.get("modified") or []
        removed = resp.get("removed") or []
        has_more = bool(resp.get("has_more"))
        next_cursor = resp.get("next_cursor") or next_cursor

        upserts = added + modified
        if upserts:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO finance_transactions
                      (transaction_id, account_id, posted_date, authorized_date,
                       amount, iso_currency, merchant_name, name,
                       category_primary, category_detailed,
                       payment_channel, pending, raw, updated_at)
                    VALUES
                      (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
                    ON CONFLICT (transaction_id) DO UPDATE SET
                      account_id        = EXCLUDED.account_id,
                      posted_date       = EXCLUDED.posted_date,
                      authorized_date   = EXCLUDED.authorized_date,
                      amount            = EXCLUDED.amount,
                      iso_currency      = EXCLUDED.iso_currency,
                      merchant_name     = EXCLUDED.merchant_name,
                      name              = EXCLUDED.name,
                      category_primary  = EXCLUDED.category_primary,
                      category_detailed = EXCLUDED.category_detailed,
                      payment_channel   = EXCLUDED.payment_channel,
                      pending           = EXCLUDED.pending,
                      raw               = EXCLUDED.raw,
                      updated_at        = now()
                    """,
                    [
                        (
                            t.get("transaction_id"),
                            t.get("account_id"),
                            _parse_date(t.get("date")),
                            _parse_date(t.get("authorized_date")),
                            _amount(t, "amount") or 0.0,
                            t.get("iso_currency_code") or t.get("unofficial_currency_code") or "USD",
                            t.get("merchant_name"),
                            t.get("name"),
                            _category(t)[0],
                            _category(t)[1],
                            t.get("payment_channel"),
                            bool(t.get("pending", False)),
                            json.dumps(t),
                        )
                        for t in upserts
                        if t.get("transaction_id") and t.get("account_id")
                    ],
                )
            conn.commit()

        if removed:
            with conn.cursor() as cur:
                cur.executemany(
                    "DELETE FROM finance_transactions WHERE transaction_id = %s",
                    [(r.get("transaction_id"),) for r in removed if r.get("transaction_id")],
                )
            conn.commit()

        added_n += len(added)
        modified_n += len(modified)
        removed_n += len(removed)
        cursor = next_cursor

        if not has_more:
            break

    return {
        "added": added_n,
        "modified": modified_n,
        "removed": removed_n,
        "pages": pages,
        "next_cursor": next_cursor,
    }


# ─── Balance snapshot ──────────────────────────────────────────────────────

def _snapshot_balances(conn, item: dict, as_of: dt.date) -> int:
    """Fetch live balances for an item; upsert accounts metadata + today's
    balance snapshot. Returns # accounts touched."""
    resp = plaid_client.accounts_balance_get(item["access_token"])
    accounts = resp.get("accounts") or []
    item_id = (resp.get("item") or {}).get("item_id") or item["item_id"]

    if not accounts:
        return 0

    with conn.cursor() as cur:
        # Refresh account metadata first (FK target for balances)
        cur.executemany(
            """
            INSERT INTO finance_accounts
              (account_id, item_id, name, official_name, mask, type, subtype,
               iso_currency, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (account_id) DO UPDATE SET
              item_id       = EXCLUDED.item_id,
              name          = EXCLUDED.name,
              official_name = EXCLUDED.official_name,
              mask          = EXCLUDED.mask,
              type          = EXCLUDED.type,
              subtype       = EXCLUDED.subtype,
              iso_currency  = EXCLUDED.iso_currency,
              updated_at    = now()
            """,
            [
                (
                    a.get("account_id"),
                    item_id,
                    a.get("name"),
                    a.get("official_name"),
                    a.get("mask"),
                    a.get("type"),
                    a.get("subtype"),
                    a.get("balances", {}).get("iso_currency_code") or "USD",
                )
                for a in accounts
                if a.get("account_id")
            ],
        )

        # Today's balance snapshot
        cur.executemany(
            """
            INSERT INTO finance_balances
              (account_id, as_of_date, current, available, iso_currency, ingested_at)
            VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (account_id, as_of_date) DO UPDATE SET
              current      = EXCLUDED.current,
              available    = EXCLUDED.available,
              iso_currency = EXCLUDED.iso_currency,
              ingested_at  = now()
            """,
            [
                (
                    a.get("account_id"),
                    as_of,
                    (a.get("balances") or {}).get("current"),
                    (a.get("balances") or {}).get("available"),
                    (a.get("balances") or {}).get("iso_currency_code") or "USD",
                )
                for a in accounts
                if a.get("account_id")
            ],
        )
    conn.commit()
    return len(accounts)


# ─── Net-worth rollup ──────────────────────────────────────────────────────

def _rollup_networth(conn, as_of: dt.date) -> dict[str, float]:
    """Read today's balances joined to accounts; return
    {assets, liabilities, net_worth}. Excludes hidden + closed accounts."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.type AS type, COALESCE(SUM(b.current), 0) AS total
              FROM finance_balances b
              JOIN finance_accounts a ON a.account_id = b.account_id
             WHERE b.as_of_date = %s
               AND COALESCE(a.hidden, false) = false
               AND COALESCE(a.is_closed, false) = false
             GROUP BY a.type
            """,
            (as_of,),
        )
        by_type = {r["type"]: float(r["total"] or 0.0) for r in cur.fetchall()}

    assets = sum(v for k, v in by_type.items() if k in ASSET_TYPES)
    liabilities = sum(v for k, v in by_type.items() if k in LIABILITY_TYPES)
    return {
        "total_assets_usd": assets,
        "total_liabilities_usd": liabilities,
        "net_worth_usd": assets - liabilities,
    }


# ─── Per-item dispatch ─────────────────────────────────────────────────────

def _mark_item_error(conn, item_id: str, err_text: str) -> str:
    """Parse Plaid error JSON if present; set plaid_items.status accordingly.
    Returns the chosen status."""
    error_code = None
    error_message = err_text[-1000:]
    # plaid_client raises RuntimeError('Plaid /path 400: {"error_code":"...",...}')
    try:
        if "{" in err_text:
            payload = json.loads(err_text[err_text.index("{"):].rstrip(". "))
            error_code = payload.get("error_code")
            error_message = payload.get("error_message") or error_message
    except Exception:
        pass

    status = "login_required" if error_code == "ITEM_LOGIN_REQUIRED" else "error"
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE plaid_items
               SET status = %s,
                   error_code = %s,
                   error_message = %s,
                   updated_at = now()
             WHERE item_id = %s
            """,
            (status, error_code, error_message, item_id),
        )
    conn.commit()
    return status


def _process_item(conn, item: dict, as_of: dt.date) -> dict:
    """Sync transactions + balances for one item. Returns a result summary."""
    result = {
        "item_id": item["item_id"],
        "institution": item.get("institution_name"),
        "added": 0, "modified": 0, "removed": 0, "pages": 0,
        "accounts": 0, "status": "ok",
    }

    txn_stats = _sync_transactions(conn, item)
    result.update({k: txn_stats[k] for k in ("added", "modified", "removed", "pages")})

    n_accts = _snapshot_balances(conn, item, as_of)
    result["accounts"] = n_accts

    # Persist cursor + last_synced_at, clear any prior error
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE plaid_items
               SET cursor = %s,
                   last_synced_at = now(),
                   status = 'active',
                   error_code = NULL,
                   error_message = NULL,
                   updated_at = now()
             WHERE item_id = %s
            """,
            (txn_stats["next_cursor"], item["item_id"]),
        )
    conn.commit()

    return result


# ─── Entrypoint ────────────────────────────────────────────────────────────

def main() -> int:
    with run_logger(PLATFORM) as state:
        as_of = dt.date.today()
        conn = neon_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT item_id, access_token, institution_name, cursor, status
                      FROM plaid_items
                     WHERE status = 'active'
                     ORDER BY id
                    """
                )
                items = cur.fetchall()

            print(f"plaid: processing {len(items)} active items")

            per_item: list[dict] = []
            ok = err = 0
            for item in items:
                try:
                    summary = _process_item(conn, item, as_of)
                    per_item.append(summary)
                    ok += 1
                    print(
                        f"plaid: {item['item_id']} "
                        f"({item.get('institution_name') or '?'}) "
                        f"added={summary['added']} modified={summary['modified']} "
                        f"removed={summary['removed']} accts={summary['accounts']}"
                    )
                except Exception as e:
                    err += 1
                    print(
                        f"plaid: item {item['item_id']} failed: {e}",
                        file=sys.stderr,
                    )
                    traceback.print_exc()
                    try:
                        status = _mark_item_error(conn, item["item_id"], str(e))
                        per_item.append({
                            "item_id": item["item_id"],
                            "status": status,
                            "error": str(e)[-500:],
                        })
                    except Exception as ee:
                        print(f"plaid: failed to mark error: {ee}", file=sys.stderr)

            # Net-worth rollup → metric_snapshots (only if at least one item succeeded)
            rollup_rows: list[Row] = []
            if ok > 0:
                totals = _rollup_networth(conn, as_of)
                for metric, value in totals.items():
                    rollup_rows.append(Row(
                        platform=PLATFORM,
                        metric=metric,
                        date=as_of,
                        value=value,
                        dimension=None,
                    ))
                n = write_rows(conn, rollup_rows)
                state["rows_written"] = n
                print(
                    f"plaid: net_worth=${totals['net_worth_usd']:,.2f} "
                    f"(assets=${totals['total_assets_usd']:,.2f}, "
                    f"liab=${totals['total_liabilities_usd']:,.2f})"
                )

            state["meta"] = {
                "items_total": len(items),
                "items_ok": ok,
                "items_failed": err,
                "per_item": per_item,
            }
            if err > 0 and ok == 0:
                # Total failure — flag the run
                state["status"] = "failed"
                state["error"] = f"all {err} item(s) failed"
                return 1
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
