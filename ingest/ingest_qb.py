"""Ingest QuickBooks Online financials into Neon.

Pulls per-month for the last 25 months (enough for YoY comparisons + one
buffer month). Writes one row per (metric, month-end date) with platform='qb',
dimension=NULL (these are headline P&L lines, not per-channel breakdowns).

Metrics written:
  revenue            — Total Income
  cogs               — Total Cost of Goods Sold
  gross_profit       — Gross Profit
  operating_expense  — Total Expenses (full opex incl. marketing)
  marketing_expense  — Sum of accounts matching MARKETING_ACCOUNT_HINTS
  net_income         — Net Income
  cash               — Sum of bank + cash equivalents (from Balance Sheet)

If QB's row labels don't match expected names, the run logs which rows it
saw so the hints can be tuned.
"""
from __future__ import annotations

import datetime as dt
import sys
from dataclasses import dataclass

from qb.client import (
    balance_sheet,
    column_dates,
    profit_and_loss,
    walk_rows,
)

from ingest.core import Row, neon_conn, run_logger, write_rows

PLATFORM = "qb"

# How far back to pull. 25 months supports YoY (need T-12) + a buffer.
MONTHS_BACK = 25

# Summary rows we extract by exact label match. QB's actual labels — verified
# against DBH's P&L PDF May 2026 — use "Total for X" rather than "Total X".
# Aliases included so this also works against books that use the older naming.
SUMMARY_TO_METRIC: dict[str, str] = {
    # Revenue
    "Total for Income": "revenue",
    "Total Income": "revenue",
    # COGS
    "Total for Cost of Goods Sold": "cogs",
    "Total Cost of Goods Sold": "cogs",
    # Gross profit — same in both naming schemes
    "Gross Profit": "gross_profit",
    # Total operating expense (incl. marketing — it's a child rollup)
    "Total for Expenses": "operating_expense",
    "Total Expenses": "operating_expense",
    # Marketing umbrella account (preferred — far more accurate than hint-matching)
    "Total for Advertising & Marketing": "marketing_expense",
    "Total Advertising & Marketing": "marketing_expense",
    # Net income (bottom line, after Other Income)
    "Net Income": "net_income",
}

# Balance Sheet summary rows we extract by exact label match.
# Verified against DBH's actual Balance Sheet PDF May 2026.
# Equity intentionally omitted — QB's equity figure is book-cost basis (real
# estate at purchase price, not market) so it understates true net worth and
# the user explicitly asked not to track it.
BS_SUMMARY_TO_METRIC: dict[str, str] = {
    # Liquid cash position (sum of all bank accounts)
    "Total for Bank Accounts": "cash",
    "Total Bank Accounts": "cash",
    # Overall balance sheet rollups. QB API returns these in ALL CAPS even
    # though the UI shows them in Title Case — match both.
    "Total for Assets": "total_assets",
    "Total Assets": "total_assets",
    "TOTAL ASSETS": "total_assets",
    "Total for Liabilities": "total_liabilities",
    "Total Liabilities": "total_liabilities",
    "TOTAL LIABILITIES": "total_liabilities",
    # Debt breakdown
    "Total for Credit Cards": "credit_card_debt",
    "Total Credit Cards": "credit_card_debt",
    "Total for Building Loans": "building_loans",
    "Total Building Loans": "building_loans",
}


@dataclass
class MonthVals:
    date: dt.date
    # P&L (period)
    revenue: float = 0.0
    cogs: float = 0.0
    gross_profit: float = 0.0
    operating_expense: float = 0.0
    marketing_expense: float = 0.0
    net_income: float = 0.0
    # Balance sheet (point-in-time, month-end)
    cash: float = 0.0
    total_assets: float = 0.0
    total_liabilities: float = 0.0
    credit_card_debt: float = 0.0
    building_loans: float = 0.0


def _row_label(r: dict) -> str:
    cd = r.get("ColData") or []
    return (cd[0].get("value") if cd else "") or ""


def _col_values(r: dict) -> list[float]:
    cd = r.get("ColData") or []
    out: list[float] = []
    # Skip first cell (label) — value columns follow
    for c in cd[1:]:
        v = c.get("value")
        try:
            out.append(float(v) if v not in (None, "") else 0.0)
        except (ValueError, TypeError):
            out.append(0.0)
    return out


def _last_day(d: dt.date) -> dt.date:
    nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return nxt - dt.timedelta(days=1)


def _parse_pl(report: dict) -> tuple[list[MonthVals], list[str]]:
    """Walk a P&L report (one column per month) and return per-month values."""
    dates = column_dates(report)
    # First "column" entry is the row-label column — drop it
    value_dates = dates[1:]

    months = [MonthVals(date=_last_day(d) if d else dt.date.min) for d in value_dates]

    seen_summaries: list[str] = []
    for r in walk_rows(report):
        label = _row_label(r).strip()
        if not label:
            continue
        seen_summaries.append(label)
        field = SUMMARY_TO_METRIC.get(label)
        if field:
            vals = _col_values(r)
            for i, v in enumerate(vals):
                if i < len(months):
                    setattr(months[i], field, v)

    return months, seen_summaries


def _parse_balance_sheet(report: dict) -> dict[dt.date, dict[str, float]]:
    """Walk a Balance Sheet (monthly columns) and pull every metric in
    BS_SUMMARY_TO_METRIC by exact label match. Returns date → metric → value."""
    dates = column_dates(report)
    value_dates = dates[1:]
    month_ends = [_last_day(d) if d else None for d in value_dates]

    result: dict[dt.date, dict[str, float]] = {d: {} for d in month_ends if d}
    for r in walk_rows(report):
        label = _row_label(r).strip()
        if not label:
            continue
        metric = BS_SUMMARY_TO_METRIC.get(label)
        if not metric:
            continue
        vals = _col_values(r)
        for i, v in enumerate(vals):
            if i < len(month_ends) and month_ends[i] is not None:
                result[month_ends[i]][metric] = v
    return result


def main() -> int:
    with run_logger(PLATFORM) as state:
        today = dt.date.today()
        # Start MONTHS_BACK months ago, first of month
        start = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
        for _ in range(MONTHS_BACK - 1):
            start = (start - dt.timedelta(days=1)).replace(day=1)
        end = today

        print(f"qb: pulling P&L {start} → {end}")
        try:
            pl = profit_and_loss(start, end, summarize_column_by="Month")
            bs = balance_sheet(end, start_date=start, summarize_column_by="Month")
        except Exception as e:
            print(f"qb: report fetch failed: {e}", file=sys.stderr)
            state["status"] = "failed"
            state["error"] = str(e)[-500:]
            return 1

        months, seen_summaries = _parse_pl(pl)
        bs_by_month = _parse_balance_sheet(bs)

        # Derive any missing values from siblings. QB *should* return them
        # explicitly, but if account names drift these formulas keep the
        # dashboard honest.
        for m in months:
            if m.gross_profit == 0 and (m.revenue or m.cogs):
                m.gross_profit = m.revenue - m.cogs
            if m.net_income == 0 and (m.revenue or m.operating_expense or m.cogs):
                # Approximation: revenue - cogs - opex. Doesn't include Other
                # Income (interest earned etc.) but that's a small line for DBH.
                m.net_income = m.revenue - m.cogs - m.operating_expense

        rows: list[Row] = []
        for m in months:
            if m.date == dt.date.min:
                continue
            # P&L (period-based)
            rows.append(Row(PLATFORM, "revenue", m.date, m.revenue))
            rows.append(Row(PLATFORM, "cogs", m.date, m.cogs))
            rows.append(Row(PLATFORM, "gross_profit", m.date, m.gross_profit))
            rows.append(Row(PLATFORM, "operating_expense", m.date, m.operating_expense))
            rows.append(Row(PLATFORM, "marketing_expense", m.date, m.marketing_expense))
            rows.append(Row(PLATFORM, "net_income", m.date, m.net_income))
            # Balance sheet (point-in-time, month-end). Only write if we found
            # the row in BS — avoids zeroing out values when QB labels drift.
            bs = bs_by_month.get(m.date, {})
            for bs_metric in ("cash", "total_assets", "total_liabilities",
                              "credit_card_debt", "building_loans"):
                if bs_metric in bs:
                    rows.append(Row(PLATFORM, bs_metric, m.date, bs[bs_metric]))

        conn = neon_conn()
        try:
            n = write_rows(conn, rows)
            state["rows_written"] = n
            state["meta"] = {
                "months": len([m for m in months if m.date != dt.date.min]),
                "seen_summary_rows": seen_summaries[:20],  # truncate noisy meta
                "bs_months": len(bs_by_month),
            }
            print(f"qb: wrote {n} rows across {len(months)} months")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
