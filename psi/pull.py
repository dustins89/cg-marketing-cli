"""PSI puller — extract Core Web Vitals + category scores + full Lighthouse audits.

Reference: https://developers.google.com/speed/docs/insights/rest/v5/pagespeedapi/runpagespeed
"""
from __future__ import annotations

from typing import Any


# Lighthouse category IDs that can be requested.
ALL_CATEGORIES = ["performance", "accessibility", "best-practices", "seo", "pwa"]


def _audit_value(audits: dict, key: str) -> Any:
    a = audits.get(key) or {}
    return a.get("displayValue") or a.get("numericValue")


def _audit_numeric(audits: dict, key: str) -> float | None:
    a = audits.get(key) or {}
    v = a.get("numericValue")
    return float(v) if v is not None else None


def parse_psi(raw: dict, url: str, strategy: str) -> dict:
    """Flatten one PSI response into a single row of key metrics.

    Lab data (Lighthouse) — what PSI ran in a sandbox now:
      lab_lcp_ms, lab_fcp_ms, lab_tbt_ms, lab_cls, lab_si_ms, lab_tti_ms
    Field data (CrUX) — real users last 28 days:
      field_lcp_ms, field_fcp_ms, field_inp_ms, field_cls, field_ttfb_ms

    Plus all 5 category scores 0-100 (perf/a11y/bp/seo/pwa).
    """
    lr = raw.get("lighthouseResult") or {}
    audits = lr.get("audits") or {}
    cats = lr.get("categories") or {}

    def cat_score(name):
        c = cats.get(name) or {}
        s = c.get("score")
        return round(s * 100) if isinstance(s, (int, float)) else None

    out = {
        "url": url,
        "strategy": strategy,
        "lighthouse_version": lr.get("lighthouseVersion"),
        "fetch_time": lr.get("fetchTime"),
        "user_agent": lr.get("userAgent"),
        "performance": cat_score("performance"),
        "accessibility": cat_score("accessibility"),
        "best_practices": cat_score("best-practices"),
        "seo": cat_score("seo"),
        "pwa": cat_score("pwa"),
        # Lab metrics (sandbox run)
        "lab_lcp_ms": int(_audit_numeric(audits, "largest-contentful-paint") or 0),
        "lab_fcp_ms": int(_audit_numeric(audits, "first-contentful-paint") or 0),
        "lab_tbt_ms": int(_audit_numeric(audits, "total-blocking-time") or 0),
        "lab_cls": round(_audit_numeric(audits, "cumulative-layout-shift") or 0, 3),
        "lab_si_ms": int(_audit_numeric(audits, "speed-index") or 0),
        "lab_tti_ms": int(_audit_numeric(audits, "interactive") or 0),
        # New CWV signals
        "lab_max_potential_fid_ms": int(_audit_numeric(audits, "max-potential-fid") or 0),
        "server_response_time_ms": int(_audit_numeric(audits, "server-response-time") or 0),
        # Bundle / resource summary
        "total_byte_weight_kb": int((_audit_numeric(audits, "total-byte-weight") or 0) / 1024),
        "dom_size": int(_audit_numeric(audits, "dom-size") or 0),
        "num_requests": _count_requests(audits),
        # JS / CSS coverage
        "unused_js_kb": int((_audit_numeric(audits, "unused-javascript") or 0) / 1024),
        "unused_css_kb": int((_audit_numeric(audits, "unused-css-rules") or 0) / 1024),
        "render_blocking_kb": int((_audit_numeric(audits, "render-blocking-resources") or 0) / 1024),
        # Image weight
        "uses_optimized_images_kb": int((_audit_numeric(audits, "uses-optimized-images") or 0) / 1024),
        "modern_image_formats_kb": int((_audit_numeric(audits, "modern-image-formats") or 0) / 1024),
        "uses_webp_kb": int((_audit_numeric(audits, "uses-webp-images") or 0) / 1024),
        # Pass/fail counts per category
        **_category_pass_counts(lr),
    }

    # Field data (CrUX) — only populated for URLs with enough real-world traffic
    le = raw.get("loadingExperience") or {}
    metrics = le.get("metrics") or {}
    out["field_overall"] = le.get("overall_category", "")
    out["field_origin_fallback"] = le.get("origin_fallback", False)

    for psi_key, out_key in [
        ("LARGEST_CONTENTFUL_PAINT_MS", "field_lcp_ms"),
        ("FIRST_CONTENTFUL_PAINT_MS", "field_fcp_ms"),
        ("INTERACTION_TO_NEXT_PAINT", "field_inp_ms"),
        ("CUMULATIVE_LAYOUT_SHIFT_SCORE", "field_cls"),
        ("EXPERIMENTAL_TIME_TO_FIRST_BYTE", "field_ttfb_ms"),
        ("FIRST_INPUT_DELAY_MS", "field_fid_ms"),
    ]:
        m = metrics.get(psi_key)
        if m:
            v = m.get("percentile")
            if out_key == "field_cls" and v is not None:
                v = round(v / 100, 3)
            out[out_key] = v
            out[f"{out_key}_category"] = m.get("category")
        else:
            out[out_key] = None
            out[f"{out_key}_category"] = None

    # Top opportunities (audits with savings, sorted by impact)
    opps = []
    for k, a in audits.items():
        details = a.get("details") or {}
        if details.get("type") == "opportunity":
            saving = a.get("numericValue") or 0
            if saving > 200:
                opps.append((a.get("title") or k, int(saving)))
    opps.sort(key=lambda x: -x[1])
    out["top_opportunities"] = "; ".join(f"{title} ({ms}ms)" for title, ms in opps[:3])
    out["top_opportunities_count"] = len(opps)

    return out


def parse_psi_full_audits(raw: dict, url: str, strategy: str) -> list[dict]:
    """One row per individual Lighthouse audit — for the deepest possible review.

    Returns ~150 rows per PSI run (every audit Lighthouse checks). Each row
    has the audit id, title, description, score, displayValue, weight, and
    the categories it belongs to.
    """
    lr = raw.get("lighthouseResult") or {}
    audits = lr.get("audits") or {}
    cats = lr.get("categories") or {}

    # Build audit_id → list of (category, weight) pairs
    audit_to_cats: dict[str, list[tuple[str, float]]] = {}
    for cat_id, cat in cats.items():
        for ref in cat.get("auditRefs") or []:
            audit_to_cats.setdefault(ref.get("id"), []).append(
                (cat_id, ref.get("weight", 0))
            )

    rows = []
    for audit_id, a in audits.items():
        cat_refs = audit_to_cats.get(audit_id, [])
        rows.append({
            "url": url,
            "strategy": strategy,
            "audit_id": audit_id,
            "title": a.get("title"),
            "description": (a.get("description") or "")[:300],
            "score": a.get("score"),
            "scoreDisplayMode": a.get("scoreDisplayMode"),
            "displayValue": a.get("displayValue"),
            "numericValue": a.get("numericValue"),
            "numericUnit": a.get("numericUnit"),
            "categories": ",".join(c for c, _ in cat_refs),
            "weight_total": sum(w for _, w in cat_refs),
            "details_type": (a.get("details") or {}).get("type"),
            "items_count": len((a.get("details") or {}).get("items") or []),
        })
    rows.sort(key=lambda r: (r["categories"], -(r["weight_total"] or 0)))
    return rows


def parse_psi_resources(raw: dict, url: str, strategy: str) -> list[dict]:
    """Network request inventory — one row per resource Lighthouse saw."""
    lr = raw.get("lighthouseResult") or {}
    audits = lr.get("audits") or {}
    nr = audits.get("network-requests") or {}
    items = (nr.get("details") or {}).get("items") or []
    rows = []
    for it in items:
        rows.append({
            "url": url,
            "strategy": strategy,
            "request_url": it.get("url"),
            "resource_type": it.get("resourceType"),
            "mime_type": it.get("mimeType"),
            "transfer_size_kb": round((it.get("transferSize") or 0) / 1024, 1),
            "resource_size_kb": round((it.get("resourceSize") or 0) / 1024, 1),
            "status_code": it.get("statusCode"),
            "protocol": it.get("protocol"),
            "rendererStartTime_ms": int(it.get("rendererStartTime") or 0),
            "networkEndTime_ms": int(it.get("networkEndTime") or 0),
            "experimentalFromMainFrame": it.get("experimentalFromMainFrame"),
        })
    rows.sort(key=lambda r: -r["transfer_size_kb"])
    return rows


def _count_requests(audits: dict) -> int:
    nr = audits.get("network-requests") or {}
    items = (nr.get("details") or {}).get("items") or []
    return len(items)


def _category_pass_counts(lr: dict) -> dict:
    """For each category, count of audits passing / failing / NA / manual."""
    out = {}
    audits = lr.get("audits") or {}
    for cat_id, cat in (lr.get("categories") or {}).items():
        passed = failed = na = manual = 0
        for ref in cat.get("auditRefs") or []:
            aid = ref.get("id")
            a = audits.get(aid) or {}
            mode = a.get("scoreDisplayMode")
            score = a.get("score")
            if mode == "notApplicable":
                na += 1
            elif mode == "manual":
                manual += 1
            elif score is None:
                continue
            elif score >= 0.9:
                passed += 1
            else:
                failed += 1
        slug = cat_id.replace("-", "_")
        out[f"{slug}_audits_passed"] = passed
        out[f"{slug}_audits_failed"] = failed
        out[f"{slug}_audits_na"] = na
        out[f"{slug}_audits_manual"] = manual
    return out


COLUMNS = [
    "url", "strategy",
    "performance", "accessibility", "best_practices", "seo", "pwa",
    "field_overall",
    "field_lcp_ms", "field_inp_ms", "field_cls", "field_ttfb_ms", "field_fid_ms",
    "lab_lcp_ms", "lab_tbt_ms", "lab_cls", "lab_tti_ms",
    "server_response_time_ms", "total_byte_weight_kb",
    "unused_js_kb", "unused_css_kb", "render_blocking_kb",
    "performance_audits_failed", "accessibility_audits_failed",
    "best_practices_audits_failed", "seo_audits_failed",
    "top_opportunities",
]

COLUMNS_FULL_AUDITS = [
    "audit_id", "title", "score", "scoreDisplayMode", "displayValue",
    "categories", "weight_total", "details_type", "items_count",
]

COLUMNS_RESOURCES = [
    "request_url", "resource_type", "mime_type", "transfer_size_kb",
    "resource_size_kb", "status_code", "protocol", "rendererStartTime_ms",
]
