"""Meta Marketing API + Pixel pullers.

Read-only diagnostics + perf data. Mutations live in apply.py (Phase 2).

SDK reference: https://github.com/facebook/facebook-python-business-sdk
Marketing API insights fields: https://developers.facebook.com/docs/marketing-api/insights/parameters/v23.0
Breakdowns: https://developers.facebook.com/docs/marketing-api/insights/breakdowns
"""
from __future__ import annotations

from datetime import date, timedelta


def _date_window(days: int | None, since: str | None) -> tuple[str, str]:
    end = date.today()
    if since:
        start = date.fromisoformat(since)
    else:
        start = end - timedelta(days=days or 30)
    return start.isoformat(), end.isoformat()


# Standard insight fields reused across campaign/adset/ad pulls.
_INSIGHT_FIELDS = [
    "spend", "impressions", "clicks", "reach", "frequency",
    "ctr", "cpc", "cpm", "cpp",
    "actions", "action_values",
    "unique_actions", "unique_clicks", "unique_ctr",
    "video_p25_watched_actions", "video_p50_watched_actions",
    "video_p75_watched_actions", "video_p100_watched_actions",
    "inline_link_clicks", "inline_link_click_ctr",
    "outbound_clicks", "outbound_clicks_ctr",
    "purchase_roas", "website_purchase_roas",
    "attribution_setting",
]


def _extract_actions(ins) -> dict:
    """Pull lead/purchase/page_engagement counts out of the actions list."""
    actions = {a["action_type"]: float(a.get("value", 0)) for a in ins.get("actions", []) or []}
    return {
        "leads": actions.get("lead", 0),
        "purchases": actions.get("purchase", 0),
        "page_engagement": actions.get("page_engagement", 0),
        "link_clicks": actions.get("link_click", 0),
        "landing_page_views": actions.get("landing_page_view", 0),
    }


def _insight_row(ins: dict, extra: dict | None = None) -> dict:
    """Common insight row shape — works for campaign/adset/ad/breakdown rows."""
    r = {
        "spend_usd": float(ins.get("spend", 0) or 0),
        "impressions": int(ins.get("impressions", 0) or 0),
        "reach": int(ins.get("reach", 0) or 0),
        "frequency": round(float(ins.get("frequency", 0) or 0), 2),
        "clicks": int(ins.get("clicks", 0) or 0),
        "ctr": round(float(ins.get("ctr", 0) or 0), 4),
        "cpc": round(float(ins.get("cpc", 0) or 0), 2),
        "cpm": round(float(ins.get("cpm", 0) or 0), 2),
        "inline_link_clicks": int(ins.get("inline_link_clicks", 0) or 0),
        "outbound_clicks": int((ins.get("outbound_clicks") or [{}])[0].get("value", 0) or 0)
                          if isinstance(ins.get("outbound_clicks"), list) else 0,
        "attribution_setting": ins.get("attribution_setting"),
        **_extract_actions(ins),
    }
    if extra:
        r.update(extra)
    return r


def whoami() -> dict:
    """Verify the access token works and return basic identity info."""
    from facebook_business.adobjects.user import User
    me = User(fbid="me").api_get(fields=["id", "name", "email"])
    return {"id": me.get("id"), "name": me.get("name"), "email": me.get("email")}


def list_ad_accounts() -> list[dict]:
    """List ad accounts the access token can see."""
    from facebook_business.adobjects.user import User
    accts = User(fbid="me").get_ad_accounts(fields=["id", "name", "account_status", "currency", "timezone_name"])
    return [
        {
            "id": a.get("id"),
            "name": a.get("name"),
            "status": a.get("account_status"),
            "currency": a.get("currency"),
            "timezone": a.get("timezone_name"),
        }
        for a in accts
    ]


def pull_campaigns(ad_account_id: str, days: int | None, since: str | None) -> list[dict]:
    from facebook_business.adobjects.adaccount import AdAccount
    start, end = _date_window(days, since)
    insights_params = {
        "time_range": {"since": start, "until": end},
        "level": "campaign",
        "fields": ["campaign_id", "campaign_name", *_INSIGHT_FIELDS],
    }
    rows = []
    for ins in AdAccount(ad_account_id).get_insights(params=insights_params):
        rows.append(_insight_row(ins, {
            "campaign_id": ins.get("campaign_id"),
            "name": ins.get("campaign_name"),
        }))
    return rows


def pull_adsets(ad_account_id: str, days: int | None, since: str | None) -> list[dict]:
    """Adset-level insights — required for budget pacing + audience-overlap analysis."""
    from facebook_business.adobjects.adaccount import AdAccount
    start, end = _date_window(days, since)
    insights_params = {
        "time_range": {"since": start, "until": end},
        "level": "adset",
        "fields": ["campaign_id", "campaign_name", "adset_id", "adset_name",
                   *_INSIGHT_FIELDS],
    }
    rows = []
    for ins in AdAccount(ad_account_id).get_insights(params=insights_params):
        rows.append(_insight_row(ins, {
            "adset_id": ins.get("adset_id"),
            "adset_name": ins.get("adset_name"),
            "campaign_id": ins.get("campaign_id"),
            "campaign_name": ins.get("campaign_name"),
        }))
    return rows


def pull_ads(ad_account_id: str, days: int | None, since: str | None) -> list[dict]:
    """Ad-level insights — required for creative fatigue (frequency/CPC drift/CTR decay)."""
    from facebook_business.adobjects.adaccount import AdAccount
    start, end = _date_window(days, since)
    insights_params = {
        "time_range": {"since": start, "until": end},
        "level": "ad",
        "fields": ["campaign_id", "campaign_name", "adset_id", "adset_name",
                   "ad_id", "ad_name", *_INSIGHT_FIELDS],
    }
    rows = []
    for ins in AdAccount(ad_account_id).get_insights(params=insights_params):
        rows.append(_insight_row(ins, {
            "ad_id": ins.get("ad_id"),
            "ad_name": ins.get("ad_name"),
            "adset_id": ins.get("adset_id"),
            "adset_name": ins.get("adset_name"),
            "campaign_id": ins.get("campaign_id"),
            "campaign_name": ins.get("campaign_name"),
        }))
    return rows


# Valid breakdown values per Meta docs.
VALID_BREAKDOWNS = {
    "age", "gender", "age_gender", "country", "region", "dma",
    "impression_device", "publisher_platform", "platform_position",
    "device_platform", "product_id",
    "hourly_stats_aggregated_by_advertiser_time_zone",
}


def pull_breakdown(ad_account_id: str, breakdown: str, days: int | None,
                   since: str | None, level: str = "account") -> list[dict]:
    """Generic breakdown puller. `breakdown` is one of VALID_BREAKDOWNS.

    Use level='account' (default) to roll the whole account across the breakdown;
    pass level='campaign'/'adset'/'ad' to keep the entity-id dimensions too.
    """
    if breakdown not in VALID_BREAKDOWNS:
        raise ValueError(f"breakdown must be one of {sorted(VALID_BREAKDOWNS)}, got {breakdown!r}")
    from facebook_business.adobjects.adaccount import AdAccount
    start, end = _date_window(days, since)
    params = {
        "time_range": {"since": start, "until": end},
        "level": level,
        "breakdowns": breakdown,
        "fields": _INSIGHT_FIELDS,
    }
    if level in ("campaign", "adset", "ad"):
        params["fields"] = [f"{level}_id", f"{level}_name", *params["fields"]]
    rows = []
    for ins in AdAccount(ad_account_id).get_insights(params=params):
        extra = {breakdown: ins.get(breakdown)}
        if level in ("campaign", "adset", "ad"):
            extra[f"{level}_id"] = ins.get(f"{level}_id")
            extra[f"{level}_name"] = ins.get(f"{level}_name")
        rows.append(_insight_row(ins, extra))
    return rows


def pull_time_series(ad_account_id: str, days: int | None, since: str | None,
                     level: str = "account", time_increment: int = 1) -> list[dict]:
    """Daily (or weekly/monthly) granularity insights for trend tiles.

    time_increment: 1 = daily (default), 7 = weekly, 'monthly' = monthly,
    'all_days' = single row over the window.
    """
    from facebook_business.adobjects.adaccount import AdAccount
    start, end = _date_window(days, since)
    params = {
        "time_range": {"since": start, "until": end},
        "level": level,
        "time_increment": time_increment,
        "fields": _INSIGHT_FIELDS,
    }
    rows = []
    for ins in AdAccount(ad_account_id).get_insights(params=params):
        rows.append(_insight_row(ins, {
            "date_start": ins.get("date_start"),
            "date_stop": ins.get("date_stop"),
        }))
    return rows


def pull_account_info(ad_account_id: str) -> dict:
    """Account balance, spend cap, currency, status, attribution defaults."""
    from facebook_business.adobjects.adaccount import AdAccount
    a = AdAccount(ad_account_id).api_get(fields=[
        "id", "name", "account_status", "currency", "timezone_name",
        "balance", "spend_cap", "amount_spent",
        "business", "business_country_code",
        "disable_reason", "funding_source_details",
        "min_daily_budget", "min_campaign_group_spend_cap",
    ])
    return {
        "id": a.get("id"),
        "name": a.get("name"),
        "account_status": a.get("account_status"),
        "currency": a.get("currency"),
        "timezone": a.get("timezone_name"),
        "balance": a.get("balance"),
        "spend_cap": a.get("spend_cap"),
        "amount_spent": a.get("amount_spent"),
        "min_daily_budget": a.get("min_daily_budget"),
        "business_country_code": a.get("business_country_code"),
        "disable_reason": a.get("disable_reason"),
    }


def list_custom_audiences(ad_account_id: str) -> list[dict]:
    """Custom Audiences — size, retention, type, last refresh.

    Critical when running the nightly Customer Match sync — surfaces match rate
    and ensures the sync actually populated the audience.
    """
    from facebook_business.adobjects.adaccount import AdAccount
    fields = ["id", "name", "subtype", "description",
              "approximate_count_lower_bound", "approximate_count_upper_bound",
              "delivery_status", "operation_status",
              "data_source", "retention_days", "rule",
              "customer_file_source", "is_value_based",
              "time_created", "time_updated", "time_content_updated"]
    rows = []
    for aud in AdAccount(ad_account_id).get_custom_audiences(fields=fields):
        a = dict(aud)
        rows.append({
            "id": a.get("id"),
            "name": a.get("name"),
            "subtype": a.get("subtype"),
            "size_lower": a.get("approximate_count_lower_bound"),
            "size_upper": a.get("approximate_count_upper_bound"),
            "delivery_status": (a.get("delivery_status") or {}).get("code")
                               if isinstance(a.get("delivery_status"), dict) else a.get("delivery_status"),
            "operation_status": (a.get("operation_status") or {}).get("code")
                                if isinstance(a.get("operation_status"), dict) else a.get("operation_status"),
            "retention_days": a.get("retention_days"),
            "is_value_based": a.get("is_value_based"),
            "time_updated": a.get("time_updated"),
            "time_content_updated": a.get("time_content_updated"),
        })
    return rows


def pull_ad_creative(ad_id: str) -> dict:
    """Ad copy + CTA + preview URL — for creative diagnostics."""
    from facebook_business.adobjects.ad import Ad
    fields = ["id", "name", "status", "creative",
              "preview_shareable_link", "tracking_specs"]
    a = Ad(fbid=ad_id).api_get(fields=fields)
    creative = a.get("creative") or {}
    # creative is a CreativeSpec — expand for the fields we want.
    if isinstance(creative, dict) and creative.get("id"):
        from facebook_business.adobjects.adcreative import AdCreative
        creative = dict(AdCreative(fbid=creative["id"]).api_get(fields=[
            "id", "name", "title", "body", "call_to_action_type",
            "image_url", "video_id", "object_url", "link_url",
            "object_story_spec", "thumbnail_url",
        ]))
    return {
        "ad_id": a.get("id"),
        "ad_name": a.get("name"),
        "status": a.get("status"),
        "preview_link": a.get("preview_shareable_link"),
        "creative_id": creative.get("id"),
        "creative_name": creative.get("name"),
        "title": creative.get("title"),
        "body": creative.get("body"),
        "cta": creative.get("call_to_action_type"),
        "link_url": creative.get("link_url") or creative.get("object_url"),
        "image_url": creative.get("image_url") or creative.get("thumbnail_url"),
        "video_id": creative.get("video_id"),
    }


def list_lead_forms(page_id: str) -> list[dict]:
    """List Lead Ad forms on a Page."""
    from facebook_business.adobjects.page import Page
    rows = []
    for f in Page(fbid=page_id).get_lead_gen_forms(fields=[
        "id", "name", "status", "locale", "leads_count",
        "created_time", "page_id", "questions",
    ]):
        f = dict(f)
        rows.append({
            "id": f.get("id"),
            "name": f.get("name"),
            "status": f.get("status"),
            "leads_count": f.get("leads_count"),
            "created_time": f.get("created_time"),
            "question_count": len(f.get("questions") or []),
        })
    return rows


def pull_lead_form_leads(form_id: str, days: int | None, since: str | None) -> list[dict]:
    """Pull leads from a single Lead Ad form."""
    from facebook_business.adobjects.leadgenform import LeadgenForm
    start, _ = _date_window(days, since)
    rows = []
    for lead in LeadgenForm(fbid=form_id).get_leads(fields=[
        "id", "created_time", "field_data", "ad_id", "ad_name",
        "campaign_id", "campaign_name", "form_id",
        "platform", "is_organic",
    ], params={"filtering": [{"field": "time_created",
                              "operator": "GREATER_THAN",
                              "value": int(date.fromisoformat(start).strftime("%s"))}]}):
        d = dict(lead)
        # field_data is list of {name, values}; flatten common ones
        fields = {f["name"]: (f.get("values") or [None])[0]
                  for f in (d.get("field_data") or [])}
        rows.append({
            "id": d.get("id"),
            "created_time": d.get("created_time"),
            "ad_id": d.get("ad_id"),
            "ad_name": d.get("ad_name"),
            "campaign_name": d.get("campaign_name"),
            "platform": d.get("platform"),
            "is_organic": d.get("is_organic"),
            "full_name": fields.get("full_name") or fields.get("name"),
            "email": fields.get("email"),
            "phone": fields.get("phone_number") or fields.get("phone"),
            "city": fields.get("city"),
            "state": fields.get("state"),
        })
    return rows


def pull_pixel_event_quality(pixel_id: str, days: int | None, since: str | None) -> list[dict]:
    """CAPI / Pixel event quality — match rate, EMQ score per event_name.

    Uses the Pixel /stats endpoint with `aggregation=event_attribute_summary`
    which returns per-event match rates and Event Match Quality (EMQ) scores —
    critical signal that the CAPI fan-out is actually being attributed.
    """
    from facebook_business.adobjects.adspixel import AdsPixel
    start, end = _date_window(days, since)
    rows = []
    # event_quality aggregation: per-event EMQ scoring
    stats = AdsPixel(fbid=pixel_id).get_stats(params={
        "aggregation": "event_attribute_summary",
        "start_time": start,
        "end_time": end,
    })
    for bucket in stats:
        b = dict(bucket)
        for d in b.get("data") or []:
            rows.append({
                "event_name": d.get("value"),
                "count": int(d.get("count", 0)),
                "match_rate_approx": d.get("match_rate_approx"),
                "emq_score": d.get("event_match_quality_score"),
                "browser_count": d.get("browser_count"),
                "server_count": d.get("server_count"),
                "deduplication_rate": d.get("deduplication_rate"),
                "bucket_start": b.get("start_time"),
            })
    return rows


def pull_pixel_info(pixel_id: str) -> dict:
    from facebook_business.adobjects.adspixel import AdsPixel
    p = AdsPixel(fbid=pixel_id).api_get(fields=[
        "id", "name", "code", "creation_time", "last_fired_time",
        "data_use_setting", "first_party_cookie_status", "automatic_matching_fields",
    ])
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "creation_time": p.get("creation_time"),
        "last_fired_time": p.get("last_fired_time"),
        "data_use_setting": p.get("data_use_setting"),
        "first_party_cookie_status": p.get("first_party_cookie_status"),
        "automatic_matching_fields": p.get("automatic_matching_fields"),
    }


def pull_pixel_events(pixel_id: str, days: int | None, since: str | None) -> list[dict]:
    """Recent events received by the pixel, grouped by event_name with totals
    over the date window."""
    from facebook_business.adobjects.adspixel import AdsPixel
    start, end = _date_window(days, since)
    stats = AdsPixel(fbid=pixel_id).get_stats(params={
        "aggregation": "event",
        "start_time": start,
        "end_time": end,
    })
    # Response is hourly buckets, each with a `data` list of {value, count}.
    # Flatten + group by event_name (= value field).
    totals: dict[str, int] = {}
    last_seen: dict[str, str] = {}
    for bucket in stats:
        bucket = dict(bucket)
        for d in bucket.get("data", []) or []:
            name = d.get("value")
            count = int(d.get("count", 0))
            if not name:
                continue
            totals[name] = totals.get(name, 0) + count
            last_seen[name] = max(last_seen.get(name, ""), bucket.get("start_time", ""))
    return [
        {"event_name": name, "count": totals[name], "last_seen": last_seen.get(name)}
        for name in sorted(totals, key=lambda n: -totals[n])
    ]


_INSIGHT_COLS = ["spend_usd", "impressions", "reach", "frequency", "clicks",
                 "ctr", "cpc", "cpm", "leads", "purchases", "link_clicks",
                 "landing_page_views", "outbound_clicks", "page_engagement"]

COLUMNS = {
    "ad-accounts": ["id", "name", "status", "currency", "timezone"],
    "account-info": ["id", "name", "account_status", "currency", "balance",
                     "spend_cap", "amount_spent", "min_daily_budget",
                     "business_country_code", "disable_reason"],
    "campaigns": ["campaign_id", "name", *_INSIGHT_COLS],
    "adsets": ["adset_id", "adset_name", "campaign_name", *_INSIGHT_COLS],
    "ads": ["ad_id", "ad_name", "adset_name", "campaign_name", *_INSIGHT_COLS],
    "time-series": ["date_start", "date_stop", *_INSIGHT_COLS],
    "custom-audiences": ["id", "name", "subtype", "size_lower", "size_upper",
                         "delivery_status", "operation_status", "retention_days",
                         "is_value_based", "time_updated", "time_content_updated"],
    "lead-forms": ["id", "name", "status", "leads_count", "question_count", "created_time"],
    "lead-form-leads": ["created_time", "full_name", "email", "phone", "city",
                        "state", "campaign_name", "ad_name", "platform", "is_organic"],
    "creative": ["ad_id", "ad_name", "status", "creative_id", "creative_name",
                 "title", "body", "cta", "link_url", "image_url", "preview_link"],
    "pixel-events": ["event_name", "count", "last_seen"],
    "pixel-event-quality": ["event_name", "count", "match_rate_approx", "emq_score",
                            "browser_count", "server_count", "deduplication_rate",
                            "bucket_start"],
    # Breakdown columns are built dynamically (breakdown name + insight cols).
}


def breakdown_columns(breakdown: str, level: str = "account") -> list[str]:
    """Build column list for a breakdown view."""
    cols = [breakdown]
    if level in ("campaign", "adset", "ad"):
        cols.append(f"{level}_name")
    cols.extend(_INSIGHT_COLS)
    return cols
