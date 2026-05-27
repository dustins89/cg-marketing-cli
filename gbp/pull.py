"""GBP pullers — accounts, locations, performance metrics, Q&A.

Performance metrics reference:
  https://developers.google.com/my-business/reference/performance/rest/v1/locations/fetchMultiDailyMetricsTimeSeries

Available daily metrics:
  BUSINESS_IMPRESSIONS_DESKTOP_MAPS, BUSINESS_IMPRESSIONS_DESKTOP_SEARCH,
  BUSINESS_IMPRESSIONS_MOBILE_MAPS, BUSINESS_IMPRESSIONS_MOBILE_SEARCH,
  BUSINESS_CONVERSATIONS, BUSINESS_DIRECTION_REQUESTS,
  CALL_CLICKS, WEBSITE_CLICKS,
  BUSINESS_BOOKINGS, BUSINESS_FOOD_ORDERS, BUSINESS_FOOD_MENU_CLICKS
"""
from __future__ import annotations

from datetime import date, timedelta


PSI_DATA_LAG_DAYS = 2  # GBP performance metrics typically lag 1-2 days


DEFAULT_LOCATION_READ_MASK = (
    "name,languageCode,storeCode,title,phoneNumbers,categories,"
    "categories.additionalCategories,"
    "storefrontAddress,websiteUri,regularHours,specialHours,serviceArea,"
    "labels,latlng,openInfo,metadata,profile,relationshipData,moreHours,serviceItems"
)

DEFAULT_METRICS = [
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
    "BUSINESS_CONVERSATIONS",
    "BUSINESS_DIRECTION_REQUESTS",
    "CALL_CLICKS",
    "WEBSITE_CLICKS",
]


def pull_accounts(svc) -> list[dict]:
    rows = []
    page_token = None
    while True:
        params = {"pageSize": 50}
        if page_token:
            params["pageToken"] = page_token
        resp = svc.accounts().list(**params).execute()
        for a in resp.get("accounts", []):
            rows.append({
                "name": a.get("name"),
                "accountName": a.get("accountName"),
                "type": a.get("type"),
                "role": a.get("role"),
                "verificationState": a.get("verificationState"),
                "vettedState": a.get("vettedState"),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return rows


def _format_addr(addr: dict | None) -> str:
    if not addr:
        return ""
    parts = list(addr.get("addressLines") or []) + [
        addr.get("locality"),
        addr.get("administrativeArea"),
        addr.get("postalCode"),
    ]
    return ", ".join(p for p in parts if p)


def pull_locations(svc, account_name: str, read_mask: str = DEFAULT_LOCATION_READ_MASK) -> list[dict]:
    """List locations under an account. account_name = 'accounts/12345'."""
    rows = []
    page_token = None
    while True:
        params = {"parent": account_name, "readMask": read_mask, "pageSize": 100}
        if page_token:
            params["pageToken"] = page_token
        resp = svc.accounts().locations().list(**params).execute()
        for loc in resp.get("locations", []):
            primary_cat = (loc.get("categories") or {}).get("primaryCategory") or {}
            phones = loc.get("phoneNumbers") or {}
            open_info = loc.get("openInfo") or {}
            rows.append({
                "name": loc.get("name"),
                "title": loc.get("title"),
                "storeCode": loc.get("storeCode") or "",
                "primaryCategory": primary_cat.get("displayName") or "",
                "primaryPhone": phones.get("primaryPhone") or "",
                "websiteUri": loc.get("websiteUri") or "",
                "address": _format_addr(loc.get("storefrontAddress")),
                "openStatus": open_info.get("status") or "",
                "labels": ",".join(loc.get("labels") or []),
                "serviceItemsCount": len(loc.get("serviceItems") or []),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return rows


def pull_location_detail(svc, location_name: str, read_mask: str = "*") -> dict:
    """Get full location detail. location_name = 'locations/12345'."""
    return svc.locations().get(name=location_name, readMask=read_mask).execute()


def pull_performance(perf_svc, location_name: str, days: int, metrics: list[str] | None = None) -> list[dict]:
    """Daily performance metrics for a location.

    Returns one row per day with one column per metric.
    """
    metrics = metrics or DEFAULT_METRICS
    end = date.today() - timedelta(days=PSI_DATA_LAG_DAYS)
    start = end - timedelta(days=days)

    request = perf_svc.locations().fetchMultiDailyMetricsTimeSeries(
        location=location_name,
        dailyMetrics=metrics,
        **{
            "dailyRange.start_date.year": start.year,
            "dailyRange.start_date.month": start.month,
            "dailyRange.start_date.day": start.day,
            "dailyRange.end_date.year": end.year,
            "dailyRange.end_date.month": end.month,
            "dailyRange.end_date.day": end.day,
        },
    )
    resp = request.execute()

    daily: dict[str, dict] = {}
    for series in resp.get("multiDailyMetricTimeSeries", []):
        for ts in series.get("dailyMetricTimeSeries", []):
            metric = ts.get("dailyMetric")
            for v in (ts.get("timeSeries") or {}).get("datedValues", []):
                d = v.get("date") or {}
                day_key = f"{d.get('year', 0):04d}-{d.get('month', 0):02d}-{d.get('day', 0):02d}"
                row = daily.setdefault(day_key, {"date": day_key})
                row[metric] = int(v.get("value") or 0)

    rows = []
    for day in sorted(daily.keys()):
        # Ensure every metric column is present
        row = daily[day]
        for m in metrics:
            row.setdefault(m, 0)
        rows.append(row)
    return rows


def pull_qna(svc, location_name: str) -> list[dict]:
    """List Q&A for a location. location_name = 'locations/12345'."""
    rows = []
    page_token = None
    while True:
        params = {"parent": location_name, "pageSize": 100, "answersPerQuestion": 10}
        if page_token:
            params["pageToken"] = page_token
        resp = svc.locations().questions().list(**params).execute()
        for q in resp.get("questions", []):
            answers = q.get("topAnswers") or []
            rows.append({
                "name": q.get("name"),
                "text": (q.get("text") or "")[:200],
                "author": (q.get("author") or {}).get("displayName") or "",
                "createTime": q.get("createTime"),
                "totalAnswerCount": q.get("totalAnswerCount", 0),
                "topAnswer": (answers[0].get("text") if answers else "")[:200],
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return rows


def pull_categories(svc, region_code: str = "US", language: str = "en") -> list[dict]:
    """Search GBP business categories — useful for finding the right primaryCategory."""
    rows = []
    page_token = None
    while True:
        params = {
            "regionCode": region_code,
            "languageCode": language,
            "view": "BASIC",
            "pageSize": 100,
        }
        if page_token:
            params["pageToken"] = page_token
        resp = svc.categories().list(**params).execute()
        for c in resp.get("categories", []):
            rows.append({
                "name": c.get("name"),
                "displayName": c.get("displayName"),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return rows


# ─── search keywords (in businessprofileperformance API) ─────────────────────

def pull_search_keywords(perf_svc, location_name: str,
                        months_back: int = 3) -> list[dict]:
    """Search keywords that drove impressions to this profile (last N months).

    Endpoint:
      locations/{lid}/searchkeywords/impressions/monthly
    """
    from datetime import date as _date
    today = _date.today()
    # Compute start month by walking back months_back months
    y, m = today.year, today.month - months_back
    while m < 1:
        m += 12
        y -= 1
    request = perf_svc.locations().searchkeywords().impressions().monthly().list(
        parent=location_name,
        **{
            "monthlyRange.start_month.year": y,
            "monthlyRange.start_month.month": m,
            "monthlyRange.end_month.year": today.year,
            "monthlyRange.end_month.month": today.month,
        },
    )
    resp = request.execute()
    rows = []
    for kw in resp.get("searchKeywordsCounts", []):
        keyword = kw.get("searchKeyword") or ""
        for ic in kw.get("insightsValue") or []:
            mv = ic.get("value") or ic.get("threshold")
            month = ic.get("month") or {}
            rows.append({
                "keyword": keyword,
                "year": month.get("year"),
                "month": month.get("month"),
                "impressions": int(mv or 0),
                "is_threshold": "threshold" in (ic or {}),
            })
    return rows


# ─── Reviews API (legacy v4 — requires allowlist) ────────────────────────────

def pull_reviews(account_id: str, location_id: str, max_pages: int = 10) -> list[dict]:
    """List reviews for a location.

    account_id: numeric ID (NOT 'accounts/123')
    location_id: numeric ID (NOT 'locations/123')

    Returns one row per review with star rating, text, reply, timestamps.
    """
    from .client import legacy_get
    aid = _strip_prefix(account_id, "accounts/")
    lid = _strip_prefix(location_id, "locations/")
    rows = []
    page_token = None
    for _ in range(max_pages):
        params = {"pageSize": 50, "orderBy": "updateTime desc"}
        if page_token:
            params["pageToken"] = page_token
        body = legacy_get(f"accounts/{aid}/locations/{lid}/reviews", params)
        for r in body.get("reviews", []):
            reviewer = r.get("reviewer") or {}
            reply = r.get("reviewReply") or {}
            rows.append({
                "reviewId": r.get("reviewId"),
                "name": r.get("name"),
                "starRating": r.get("starRating"),
                "comment": (r.get("comment") or "")[:500],
                "reviewer_name": reviewer.get("displayName"),
                "reviewer_is_anonymous": reviewer.get("isAnonymous"),
                "createTime": r.get("createTime"),
                "updateTime": r.get("updateTime"),
                "reply_comment": (reply.get("comment") or "")[:500] if reply else None,
                "reply_updateTime": reply.get("updateTime") if reply else None,
                "has_reply": bool(reply),
            })
        page_token = body.get("nextPageToken")
        if not page_token:
            break
    return rows


# ─── Local Posts API (legacy v4 — requires allowlist) ────────────────────────

def pull_local_posts(account_id: str, location_id: str,
                    max_pages: int = 10) -> list[dict]:
    """List Local Posts (updates + events + offers + products)."""
    from .client import legacy_get
    aid = _strip_prefix(account_id, "accounts/")
    lid = _strip_prefix(location_id, "locations/")
    rows = []
    page_token = None
    for _ in range(max_pages):
        params = {"pageSize": 100}
        if page_token:
            params["pageToken"] = page_token
        body = legacy_get(f"accounts/{aid}/locations/{lid}/localPosts", params)
        for p in body.get("localPosts", []):
            cta = p.get("callToAction") or {}
            event = p.get("event") or {}
            offer = p.get("offer") or {}
            rows.append({
                "name": p.get("name"),
                "languageCode": p.get("languageCode"),
                "summary": (p.get("summary") or "")[:300],
                "state": p.get("state"),
                "topicType": p.get("topicType"),
                "cta_actionType": cta.get("actionType"),
                "cta_url": cta.get("url"),
                "media_count": len(p.get("media") or []),
                "event_title": event.get("title"),
                "offer_couponCode": offer.get("couponCode"),
                "createTime": p.get("createTime"),
                "updateTime": p.get("updateTime"),
                "searchUrl": p.get("searchUrl"),
            })
        page_token = body.get("nextPageToken")
        if not page_token:
            break
    return rows


# ─── Media API (legacy v4 — requires allowlist) ──────────────────────────────

def pull_media(account_id: str, location_id: str, max_pages: int = 20) -> list[dict]:
    """List photos / videos uploaded to the location (owner + customer)."""
    from .client import legacy_get
    aid = _strip_prefix(account_id, "accounts/")
    lid = _strip_prefix(location_id, "locations/")
    rows = []
    page_token = None
    for _ in range(max_pages):
        params = {"pageSize": 100}
        if page_token:
            params["pageToken"] = page_token
        body = legacy_get(f"accounts/{aid}/locations/{lid}/media", params)
        for m in body.get("mediaItems", []):
            insights = m.get("insights") or {}
            attribution = m.get("attribution") or {}
            rows.append({
                "name": m.get("name"),
                "mediaFormat": m.get("mediaFormat"),
                "locationAssociation_category": (m.get("locationAssociation") or {}).get("category"),
                "googleUrl": m.get("googleUrl"),
                "sourceUrl": m.get("sourceUrl"),
                "thumbnailUrl": m.get("thumbnailUrl"),
                "viewCount": int(insights.get("viewCount", 0) or 0),
                "attribution_takedown": attribution.get("takedownUrl"),
                "createTime": m.get("createTime"),
            })
        page_token = body.get("nextPageToken")
        if not page_token:
            break
    return rows


# ─── Attributes API (mybusinessbusinessinformation) ──────────────────────────

def pull_attributes(svc, location_name: str) -> list[dict]:
    """List attributes set on a location (Wheelchair accessible, Veteran-owned, etc.)."""
    resp = svc.locations().attributes().get(name=f"{location_name}/attributes").execute()
    rows = []
    for a in resp.get("attributes", []) or []:
        rows.append({
            "name": a.get("name"),
            "valueType": a.get("valueType"),
            "values": ", ".join(str(v) for v in (a.get("values") or [])),
            "uri_count": len(a.get("uriValues") or []),
        })
    return rows


# ─── Verifications API ───────────────────────────────────────────────────────

def pull_verifications(verif_svc, location_name: str) -> list[dict]:
    """Verification history for a location (state, method, expiry)."""
    resp = verif_svc.locations().verifications().list(parent=location_name).execute()
    rows = []
    for v in resp.get("verifications", []) or []:
        rows.append({
            "name": v.get("name"),
            "state": v.get("state"),
            "method": v.get("method"),
            "createTime": v.get("createTime"),
            "announcement": (v.get("announcement") or "")[:200],
        })
    return rows


def _strip_prefix(s: str, prefix: str) -> str:
    return s[len(prefix):] if s.startswith(prefix) else s


COLUMNS = {
    "accounts": ["name", "accountName", "type", "role", "verificationState"],
    "locations": [
        "name", "title", "primaryCategory", "primaryPhone",
        "websiteUri", "address", "openStatus", "labels",
    ],
    "performance": ["date"] + DEFAULT_METRICS,
    "qna": ["name", "text", "author", "createTime", "totalAnswerCount", "topAnswer"],
    "categories": ["name", "displayName"],
    "search-keywords": ["keyword", "year", "month", "impressions", "is_threshold"],
    "reviews": ["createTime", "starRating", "reviewer_name", "comment",
                "has_reply", "reply_updateTime", "reviewId"],
    "local-posts": ["createTime", "topicType", "state", "summary",
                    "cta_actionType", "cta_url", "media_count", "updateTime"],
    "media": ["createTime", "mediaFormat", "locationAssociation_category",
              "viewCount", "googleUrl"],
    "attributes": ["name", "valueType", "values", "uri_count"],
    "verifications": ["name", "state", "method", "createTime", "announcement"],
}
