"""Search Console pullers — webmasters.searchanalytics().query() calls + sitemaps + URL inspection.

Reference:
- Search Analytics: https://developers.google.com/webmaster-tools/v1/searchanalytics/query
- URL Inspection:   https://developers.google.com/webmaster-tools/v1/urlinspection/index
- Sitemaps:         https://developers.google.com/webmaster-tools/v1/sitemaps

Data freshness lags ~3 days for `dataState=final` (default); pass `dataState='all'`
to get fresh-but-unfinalized data for "what happened yesterday" tiles.
"""
from __future__ import annotations

from datetime import date, timedelta


SC_DATA_LAG_DAYS = 3
ROW_LIMIT_MAX = 25000  # Search Console hard cap per query.
PAGE_LIMIT = 25000     # Page size used when paginating.

# Valid `type` parameter values (the Search Console search-type segmentation).
VALID_TYPES = {"web", "image", "video", "news", "discover", "googleNews"}

# Valid `dataState` values.
VALID_DATA_STATES = {"final", "all"}


def _date_window(days: int | None, since: str | None,
                 data_state: str = "final") -> tuple[str, str]:
    """For dataState=final, end-of-window backs off 3 days for the SC lag.
    For dataState=all, end is today (allows fresh data)."""
    if data_state == "all":
        end = date.today()
    else:
        end = date.today() - timedelta(days=SC_DATA_LAG_DAYS)
    if since:
        start = date.fromisoformat(since)
    else:
        start = end - timedelta(days=days or 30)
    return start.isoformat(), end.isoformat()


def _query(service, site_url: str, dimensions: list[str],
           days: int | None, since: str | None, limit: int,
           search_type: str = "web", data_state: str = "final",
           dimension_filter_groups: list | None = None,
           paginate: bool = False) -> list[dict]:
    """Core query builder for the Search Analytics API.

    Pass `paginate=True` to walk through results past the per-call rowLimit cap.
    """
    if search_type not in VALID_TYPES:
        raise ValueError(f"type must be one of {sorted(VALID_TYPES)}")
    if data_state not in VALID_DATA_STATES:
        raise ValueError(f"dataState must be one of {sorted(VALID_DATA_STATES)}")

    start, end = _date_window(days, since, data_state=data_state)
    base_body = {
        "startDate": start,
        "endDate": end,
        "dimensions": dimensions,
        "type": search_type,
        "dataState": data_state,
    }
    if dimension_filter_groups:
        base_body["dimensionFilterGroups"] = dimension_filter_groups

    rows: list[dict] = []
    if paginate:
        start_row = 0
        per_page = min(PAGE_LIMIT, limit) if limit else PAGE_LIMIT
        while True:
            body = dict(base_body, rowLimit=per_page, startRow=start_row)
            resp = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
            batch = resp.get("rows", [])
            rows.extend(_format_rows(batch, dimensions))
            if len(batch) < per_page:
                break
            start_row += per_page
            if limit and len(rows) >= limit:
                rows = rows[:limit]
                break
    else:
        body = dict(base_body, rowLimit=min(limit or 1000, ROW_LIMIT_MAX))
        resp = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        rows = _format_rows(resp.get("rows", []), dimensions)
    return rows


def _format_rows(api_rows: list, dimensions: list[str]) -> list[dict]:
    out = []
    for r in api_rows:
        row = {}
        for i, d in enumerate(dimensions):
            row[d] = r["keys"][i]
        row["clicks"] = int(r.get("clicks", 0))
        row["impressions"] = int(r.get("impressions", 0))
        row["ctr"] = round(float(r.get("ctr", 0.0)), 4)
        row["position"] = round(float(r.get("position", 0.0)), 2)
        out.append(row)
    return out


# ─── single-dimension pullers (back-compat for existing CLI calls) ───────────

def pull_queries(service, site_url, days, since, limit,
                search_type="web", data_state="final"):
    return _query(service, site_url, ["query"], days, since, limit,
                  search_type=search_type, data_state=data_state, paginate=True)


def pull_pages(service, site_url, days, since, limit,
              search_type="web", data_state="final"):
    return _query(service, site_url, ["page"], days, since, limit,
                  search_type=search_type, data_state=data_state, paginate=True)


def pull_query_page(service, site_url, days, since, limit,
                   search_type="web", data_state="final"):
    return _query(service, site_url, ["query", "page"], days, since, limit,
                  search_type=search_type, data_state=data_state, paginate=True)


def pull_countries(service, site_url, days, since, limit,
                  search_type="web", data_state="final"):
    return _query(service, site_url, ["country"], days, since, limit,
                  search_type=search_type, data_state=data_state)


def pull_devices(service, site_url, days, since, limit,
                search_type="web", data_state="final"):
    return _query(service, site_url, ["device"], days, since, limit,
                  search_type=search_type, data_state=data_state)


# ─── new dimensions ──────────────────────────────────────────────────────────

def pull_search_appearance(service, site_url, days, since, limit,
                          search_type="web", data_state="final"):
    """searchAppearance dimension — Rich result / AMP / Web Light / etc.

    Often more actionable than raw query lists: tells you which Google SERP
    feature surfaces are driving impressions.

    NOTE: searchAppearance must be the ONLY dimension in the query per docs.
    """
    return _query(service, site_url, ["searchAppearance"], days, since, limit,
                  search_type=search_type, data_state=data_state)


def pull_timeseries(service, site_url, days, since, limit,
                   search_type="web", data_state="final",
                   group: str = "date"):
    """Time-series view — `date` only, or `date` + one other dim (e.g. device, country).

    Used for WoW/MoM/YoY trend tiles per page or per query.
    """
    if group == "date":
        dims = ["date"]
    else:
        dims = ["date", group]
    return _query(service, site_url, dims, days, since, limit,
                  search_type=search_type, data_state=data_state, paginate=True)


def pull_filtered(service, site_url, dimensions: list[str], filters: list[dict],
                 days, since, limit, search_type="web", data_state="final"):
    """Generic filtered query — pass raw dimensionFilterGroups for custom slicing.

    Example filters:
        [{"groupType": "and", "filters": [{"dimension": "query",
                                            "operator": "contains",
                                            "expression": "cash"}]}]
    """
    return _query(service, site_url, dimensions, days, since, limit,
                  search_type=search_type, data_state=data_state,
                  dimension_filter_groups=filters, paginate=True)


# ─── URL Inspection API ──────────────────────────────────────────────────────

def inspect_url(service, site_url: str, inspection_url: str,
               language_code: str = "en-US") -> dict:
    """Indexation status + mobile-friendliness + rich-results status for a URL.

    Returns the inspection result with index status, last crawl, indexed URL,
    and any AMP/mobile/rich-result diagnostics.
    """
    body = {
        "inspectionUrl": inspection_url,
        "siteUrl": site_url,
        "languageCode": language_code,
    }
    resp = service.urlInspection().index().inspect(body=body).execute()
    result = resp.get("inspectionResult") or {}
    idx = result.get("indexStatusResult") or {}
    mobile = result.get("mobileUsabilityResult") or {}
    rich = result.get("richResultsResult") or {}
    amp = result.get("ampResult") or {}
    return {
        "inspection_url": inspection_url,
        "verdict": idx.get("verdict"),
        "coverage_state": idx.get("coverageState"),
        "indexing_state": idx.get("indexingState"),
        "robots_txt_state": idx.get("robotsTxtState"),
        "page_fetch_state": idx.get("pageFetchState"),
        "last_crawl_time": idx.get("lastCrawlTime"),
        "crawled_as": idx.get("crawledAs"),
        "google_canonical": idx.get("googleCanonical"),
        "user_canonical": idx.get("userCanonical"),
        "referring_urls": idx.get("referringUrls") or [],
        "sitemap": idx.get("sitemap") or [],
        "mobile_verdict": mobile.get("verdict"),
        "mobile_issues": mobile.get("issues") or [],
        "rich_verdict": rich.get("verdict"),
        "rich_detected_items": [
            {"type": item.get("richResultType"),
             "items_count": len(item.get("items") or [])}
            for item in (rich.get("detectedItems") or [])
        ],
        "amp_verdict": amp.get("verdict"),
        "amp_indexing_state": amp.get("ampIndexStatusVerdict"),
    }


# ─── Sitemaps API ────────────────────────────────────────────────────────────

def pull_sitemaps(service, site_url: str) -> list[dict]:
    """Sitemaps for the property — last submitted, last downloaded, errors."""
    resp = service.sitemaps().list(siteUrl=site_url).execute()
    rows = []
    for s in resp.get("sitemap", []):
        contents = s.get("contents") or []
        rows.append({
            "path": s.get("path"),
            "type": s.get("type"),
            "is_pending": s.get("isPending"),
            "is_sitemaps_index": s.get("isSitemapsIndex"),
            "last_submitted": s.get("lastSubmitted"),
            "last_downloaded": s.get("lastDownloaded"),
            "errors": int(s.get("errors", 0) or 0),
            "warnings": int(s.get("warnings", 0) or 0),
            "submitted_urls": sum(int(c.get("submitted", 0) or 0) for c in contents),
            "indexed_urls": sum(int(c.get("indexed", 0) or 0) for c in contents),
        })
    return rows


def pull_sitemap_detail(service, site_url: str, feedpath: str) -> dict:
    """Single-sitemap detail (errors per content type, last download, etc)."""
    resp = service.sitemaps().get(siteUrl=site_url, feedpath=feedpath).execute()
    return resp


# ─── columns ─────────────────────────────────────────────────────────────────

COLUMNS = {
    "queries": ["query", "clicks", "impressions", "ctr", "position"],
    "pages": ["page", "clicks", "impressions", "ctr", "position"],
    "query-page": ["query", "page", "clicks", "impressions", "ctr", "position"],
    "countries": ["country", "clicks", "impressions", "ctr", "position"],
    "devices": ["device", "clicks", "impressions", "ctr", "position"],
    "search-appearance": ["searchAppearance", "clicks", "impressions", "ctr", "position"],
    "timeseries": ["date", "clicks", "impressions", "ctr", "position"],
    "timeseries-device": ["date", "device", "clicks", "impressions", "ctr", "position"],
    "timeseries-country": ["date", "country", "clicks", "impressions", "ctr", "position"],
    "sitemaps": ["path", "type", "is_pending", "last_submitted", "last_downloaded",
                 "errors", "warnings", "submitted_urls", "indexed_urls"],
    "inspect": [  # dict, not list — used by cli to pretty-print
        "inspection_url", "verdict", "coverage_state", "indexing_state",
        "page_fetch_state", "last_crawl_time", "google_canonical",
        "user_canonical", "mobile_verdict", "rich_verdict", "amp_verdict",
    ],
}
