"""Ingest PageSpeed Insights (PSI) Core Web Vitals + scores into Neon.

For each tracked landing page × {mobile, desktop} strategy, run a PSI audit
and write per-metric rows to metric_snapshots with:
  platform = 'psi'
  dimension = 'url:<url>|strategy:<mobile|desktop>'

Metrics written per (url, strategy):
  performance_score, accessibility_score, best_practices_score, seo_score,
  lcp_ms, fid_ms, cls, tbt_ms, fcp_ms, page_weight_kb, third_party_request_count

PSI free tier: 25k queries/day, 1 qps anonymous. With ~9 URLs × 2 strategies = 18
calls/run, nightly is comfortably under quota. An API key in google-ads.yaml
(psi_api_key) is supported but not required.
"""
from __future__ import annotations

import datetime as dt
import sys
import time

from psi.client import run_pagespeed
from psi.pull import parse_psi

from ingest.core import Row, run_logger, write_rows, neon_conn

PLATFORM = "psi"

# Critical landing pages — mix of homepage, sell-page, location LPs, funnel pages.
# Sourced from MASTER_PSI_DEEP_AUDIT_2026-05-16.md (6 of 10 had mobile LCP > 7s).
URLS = [
    "https://your-domain.com/",
    "https://your-domain.com/sell-your-house-fast/",
    "https://your-domain.com/sell-your-house-fast-in-<your-city>-<your-state>/",
    "https://your-domain.com/our-company/",
    "https://your-domain.com/how-it-works/",
    "https://your-domain.com/book-call/",
    "https://your-domain.com/thank-you-call-booked/",
    "https://your-domain.com/how-we-buy-houses/",
    "https://your-domain.com/reviews/",
]

STRATEGIES = ["mobile", "desktop"]

# (psi_api_strategy, dim_token, parsed_dict_value)
def _strategy_param(s: str) -> str:
    return "MOBILE" if s == "mobile" else "DESKTOP"


def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> int:
    with run_logger(PLATFORM) as state:
        today = dt.date.today()
        rows: list[Row] = []
        ok = 0
        failed: list[str] = []

        for url in URLS:
            for strat in STRATEGIES:
                dim = f"url:{url}|strategy:{strat}"
                try:
                    raw = run_pagespeed(url, strategy=_strategy_param(strat))
                    parsed = parse_psi(raw, url, strat)
                except Exception as e:
                    print(f"psi {url} ({strat}) failed: {e}", file=sys.stderr)
                    failed.append(f"{url}|{strat}")
                    # Respect rate limit even after failure
                    time.sleep(1.2)
                    continue

                # Category scores (0-100)
                rows.append(Row(PLATFORM, "performance_score", today,
                                _safe_float(parsed.get("performance")), dim))
                rows.append(Row(PLATFORM, "accessibility_score", today,
                                _safe_float(parsed.get("accessibility")), dim))
                rows.append(Row(PLATFORM, "best_practices_score", today,
                                _safe_float(parsed.get("best_practices")), dim))
                rows.append(Row(PLATFORM, "seo_score", today,
                                _safe_float(parsed.get("seo")), dim))

                # Core Web Vitals — prefer field (real-user) data when present,
                # fall back to lab (sandbox).
                lcp = parsed.get("field_lcp_ms") or parsed.get("lab_lcp_ms")
                fid = parsed.get("field_fid_ms") or parsed.get("lab_max_potential_fid_ms")
                cls = parsed.get("field_cls")
                if cls is None:
                    cls = parsed.get("lab_cls")
                fcp = parsed.get("field_fcp_ms") or parsed.get("lab_fcp_ms")

                rows.append(Row(PLATFORM, "lcp_ms", today, _safe_float(lcp), dim))
                rows.append(Row(PLATFORM, "fid_ms", today, _safe_float(fid), dim))
                rows.append(Row(PLATFORM, "cls",    today, _safe_float(cls), dim))
                rows.append(Row(PLATFORM, "tbt_ms", today, _safe_float(parsed.get("lab_tbt_ms")), dim))
                rows.append(Row(PLATFORM, "fcp_ms", today, _safe_float(fcp), dim))

                # Bundle size + 3p request count
                rows.append(Row(PLATFORM, "page_weight_kb", today,
                                _safe_float(parsed.get("total_byte_weight_kb")), dim))

                # Count third-party requests from network-requests audit
                tp_count = _third_party_count(raw, url)
                rows.append(Row(PLATFORM, "third_party_request_count", today,
                                _safe_float(tp_count), dim))

                ok += 1
                print(f"  psi {url} ({strat}): perf={parsed.get('performance')} "
                      f"lcp={lcp}ms cls={cls}")

                # PSI anonymous = 1 qps; with a key it's higher but stay polite
                time.sleep(1.2)

        conn = neon_conn()
        try:
            n = write_rows(conn, rows)
            state["rows_written"] = n
            state["meta"] = {
                "urls": len(URLS),
                "strategies": STRATEGIES,
                "audits_ok": ok,
                "audits_failed": failed,
            }
            print(f"psi: wrote {n} rows ({ok}/{len(URLS)*len(STRATEGIES)} audits ok)")
        finally:
            conn.close()
    return 0


def _third_party_count(raw: dict, page_url: str) -> int:
    """Count network-requests whose host differs from the page host."""
    try:
        from urllib.parse import urlparse
        page_host = urlparse(page_url).netloc.lower()
        lr = raw.get("lighthouseResult") or {}
        audits = lr.get("audits") or {}
        nr = audits.get("network-requests") or {}
        items = (nr.get("details") or {}).get("items") or []
        n = 0
        for it in items:
            req_host = urlparse((it.get("url") or "")).netloc.lower()
            if req_host and req_host != page_host:
                n += 1
        return n
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
