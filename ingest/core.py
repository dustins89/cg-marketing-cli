"""Shared helpers for all ingesters.

- `neon_conn()`     → psycopg connection from DATABASE_URL env
- `write_rows()`    → bulk UPSERT into metric_snapshots
- `run_logger(...)` → context manager that records start/finish/status in ingestion_runs
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import sys
import traceback
from dataclasses import dataclass, field
from typing import Iterable, Iterator

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError as e:
    raise SystemExit(
        "psycopg required. From ~/marketing-cli: "
        "`pip install -r ingest/requirements.txt`"
    ) from e


DEFAULT_ACCOUNT_ID = "dbh"


def neon_conn() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL env not set. Add to ~/marketing-cli/.env or "
                         "to GH Actions secrets.")
    return psycopg.connect(url, row_factory=dict_row, autocommit=False)


@dataclass
class Row:
    platform: str
    metric: str
    date: dt.date
    value: float | int | None
    dimension: str | None = None
    account_id: str = DEFAULT_ACCOUNT_ID
    raw: dict | None = None


def write_rows(conn: psycopg.Connection, rows: Iterable[Row]) -> int:
    """Bulk UPSERT rows into metric_snapshots. Returns count written."""
    rows = list(rows)
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO metric_snapshots
              (platform, account_id, metric, dimension, date, value, raw, ingested_at)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s::jsonb, now())
            ON CONFLICT (platform, account_id, metric, dimension, date) DO UPDATE
              SET value = EXCLUDED.value,
                  raw   = EXCLUDED.raw,
                  ingested_at = now()
            """,
            [
                (r.platform, r.account_id, r.metric, r.dimension, r.date,
                 r.value, json.dumps(r.raw) if r.raw is not None else None)
                for r in rows
            ],
        )
    conn.commit()
    return len(rows)


@contextlib.contextmanager
def run_logger(platform: str, trigger: str = "cron") -> Iterator[dict]:
    """Context manager — opens an ingestion_runs row, sets status on exit.

    Yields a dict that the caller can populate (e.g. {'rows_written': N})
    before the context exits.
    """
    state = {"rows_written": 0, "status": "ok", "error": None, "meta": {}}
    conn = neon_conn()
    run_id: int | None = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_runs (platform, trigger)
                VALUES (%s, %s) RETURNING id
                """,
                (platform, trigger),
            )
            run_id = cur.fetchone()["id"]
        conn.commit()
    except Exception as e:
        print(f"[run_logger] failed to open run: {e}", file=sys.stderr)
        # Continue without DB logging — better than failing the ingest

    try:
        yield state
    except Exception:
        state["status"] = "failed"
        state["error"] = traceback.format_exc()[-1500:]
        raise
    finally:
        if run_id is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE ingestion_runs
                           SET finished_at = now(),
                               status = %s,
                               rows_written = %s,
                               error = %s,
                               meta = %s::jsonb
                         WHERE id = %s
                        """,
                        (state["status"], state["rows_written"], state["error"],
                         json.dumps(state["meta"]), run_id),
                    )
                conn.commit()
            except Exception as e:
                print(f"[run_logger] failed to close run: {e}", file=sys.stderr)
        conn.close()
