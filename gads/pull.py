"""Read commands — GAQL queries returning lists of dicts.

Each puller takes the configured GoogleAdsClient + customer_id + a date window
and returns rows the CLI passes to format.emit().
"""
from __future__ import annotations

from datetime import date, timedelta

from .format import micros_to_dollars


def _date_window(days: int | None, since: str | None) -> tuple[str, str]:
    """Return (start, end) date strings for the BETWEEN clause."""
    end = date.today()
    if since:
        start = date.fromisoformat(since)
    else:
        start = end - timedelta(days=days or 30)
    return start.isoformat(), end.isoformat()


def _search(client, customer_id: str, query: str):
    ga_service = client.get_service("GoogleAdsService")
    return ga_service.search(customer_id=customer_id, query=query)


def pull_campaigns(client, customer_id: str, days: int | None, since: str | None) -> list[dict]:
    """Campaign perf + impression-share columns (audit-depth-v2 requirement)."""
    start, end = _date_window(days, since)
    query = f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign.advertising_channel_type,
          campaign_budget.amount_micros,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value,
          metrics.average_cpc,
          metrics.ctr,
          metrics.search_impression_share,
          metrics.search_top_impression_share,
          metrics.search_absolute_top_impression_share,
          metrics.search_budget_lost_impression_share,
          metrics.search_rank_lost_impression_share
        FROM campaign
        WHERE segments.date BETWEEN '{start}' AND '{end}'
        ORDER BY metrics.cost_micros DESC
    """
    rows = []
    for r in _search(client, customer_id, query):
        spend = micros_to_dollars(r.metrics.cost_micros)
        conv = float(r.metrics.conversions)
        rows.append({
            "campaign_id": str(r.campaign.id),
            "name": r.campaign.name,
            "status": r.campaign.status.name,
            "channel": r.campaign.advertising_channel_type.name,
            "daily_budget_usd": micros_to_dollars(r.campaign_budget.amount_micros),
            "impressions": int(r.metrics.impressions),
            "clicks": int(r.metrics.clicks),
            "spend_usd": spend,
            "conversions": round(conv, 2),
            "conv_value_usd": round(float(r.metrics.conversions_value), 2),
            "avg_cpc_usd": micros_to_dollars(r.metrics.average_cpc),
            "ctr": round(float(r.metrics.ctr), 4),
            "cpa_usd": round(spend / conv, 2) if conv else None,
            "roas": round(float(r.metrics.conversions_value) / spend, 2) if spend else None,
            "search_is": _pct_or_none(r.metrics.search_impression_share),
            "top_is": _pct_or_none(r.metrics.search_top_impression_share),
            "abs_top_is": _pct_or_none(r.metrics.search_absolute_top_impression_share),
            "budget_lost_is": _pct_or_none(r.metrics.search_budget_lost_impression_share),
            "rank_lost_is": _pct_or_none(r.metrics.search_rank_lost_impression_share),
        })
    return rows


def _pct_or_none(v):
    """Google Ads IS metrics return 0.9 for 90% (or -1 for 'not enough data')."""
    try:
        f = float(v)
        if f < 0:
            return None
        return round(f * 100, 1)
    except (TypeError, ValueError):
        return None


def pull_adgroups(client, customer_id: str, days: int | None, since: str | None) -> list[dict]:
    start, end = _date_window(days, since)
    query = f"""
        SELECT
          ad_group.id,
          ad_group.name,
          ad_group.status,
          campaign.id,
          campaign.name,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM ad_group
        WHERE segments.date BETWEEN '{start}' AND '{end}'
        ORDER BY metrics.cost_micros DESC
    """
    rows = []
    for r in _search(client, customer_id, query):
        spend = micros_to_dollars(r.metrics.cost_micros)
        conv = float(r.metrics.conversions)
        rows.append({
            "ad_group_id": str(r.ad_group.id),
            "ad_group_name": r.ad_group.name,
            "status": r.ad_group.status.name,
            "campaign_id": str(r.campaign.id),
            "campaign_name": r.campaign.name,
            "impressions": int(r.metrics.impressions),
            "clicks": int(r.metrics.clicks),
            "spend_usd": spend,
            "conversions": round(conv, 2),
            "conv_value_usd": round(float(r.metrics.conversions_value), 2),
            "cpa_usd": round(spend / conv, 2) if conv else None,
        })
    return rows


def pull_keywords(client, customer_id: str, days: int | None, since: str | None) -> list[dict]:
    start, end = _date_window(days, since)
    query = f"""
        SELECT
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.keyword.match_type,
          ad_group_criterion.status,
          ad_group_criterion.quality_info.quality_score,
          ad_group.id,
          ad_group.name,
          campaign.id,
          campaign.name,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions
        FROM keyword_view
        WHERE segments.date BETWEEN '{start}' AND '{end}'
        ORDER BY metrics.cost_micros DESC
    """
    rows = []
    for r in _search(client, customer_id, query):
        spend = micros_to_dollars(r.metrics.cost_micros)
        conv = float(r.metrics.conversions)
        rows.append({
            "criterion_id": str(r.ad_group_criterion.criterion_id),
            "keyword": r.ad_group_criterion.keyword.text,
            "match_type": r.ad_group_criterion.keyword.match_type.name,
            "status": r.ad_group_criterion.status.name,
            "quality_score": int(r.ad_group_criterion.quality_info.quality_score)
                if r.ad_group_criterion.quality_info.quality_score else None,
            "ad_group_id": str(r.ad_group.id),
            "ad_group_name": r.ad_group.name,
            "campaign_id": str(r.campaign.id),
            "campaign_name": r.campaign.name,
            "impressions": int(r.metrics.impressions),
            "clicks": int(r.metrics.clicks),
            "spend_usd": spend,
            "conversions": round(conv, 2),
            "cpa_usd": round(spend / conv, 2) if conv else None,
        })
    return rows


def pull_search_terms(client, customer_id: str, days: int | None, since: str | None) -> list[dict]:
    start, end = _date_window(days, since)
    query = f"""
        SELECT
          search_term_view.search_term,
          search_term_view.status,
          campaign.id,
          campaign.name,
          ad_group.id,
          ad_group.name,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM search_term_view
        WHERE segments.date BETWEEN '{start}' AND '{end}'
        ORDER BY metrics.cost_micros DESC
    """
    rows = []
    for r in _search(client, customer_id, query):
        spend = micros_to_dollars(r.metrics.cost_micros)
        conv = float(r.metrics.conversions)
        rows.append({
            "search_term": r.search_term_view.search_term,
            "status": r.search_term_view.status.name,
            "campaign_id": str(r.campaign.id),
            "campaign_name": r.campaign.name,
            "ad_group_id": str(r.ad_group.id),
            "ad_group_name": r.ad_group.name,
            "impressions": int(r.metrics.impressions),
            "clicks": int(r.metrics.clicks),
            "spend_usd": spend,
            "conversions": round(conv, 2),
            "conv_value_usd": round(float(r.metrics.conversions_value), 2),
            "cpa_usd": round(spend / conv, 2) if conv else None,
        })
    return rows


def pull_negatives(client, customer_id: str) -> list[dict]:
    """Existing negative keywords at campaign + ad-group level."""
    rows = []

    campaign_q = """
        SELECT
          campaign_criterion.criterion_id,
          campaign_criterion.keyword.text,
          campaign_criterion.keyword.match_type,
          campaign.id,
          campaign.name
        FROM campaign_criterion
        WHERE campaign_criterion.type = 'KEYWORD'
          AND campaign_criterion.negative = TRUE
    """
    for r in _search(client, customer_id, campaign_q):
        rows.append({
            "scope": "campaign",
            "criterion_id": str(r.campaign_criterion.criterion_id),
            "text": r.campaign_criterion.keyword.text,
            "match_type": r.campaign_criterion.keyword.match_type.name,
            "campaign_id": str(r.campaign.id),
            "campaign_name": r.campaign.name,
            "ad_group_id": None,
            "ad_group_name": None,
        })

    adgroup_q = """
        SELECT
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.keyword.match_type,
          ad_group.id,
          ad_group.name,
          campaign.id,
          campaign.name
        FROM ad_group_criterion
        WHERE ad_group_criterion.type = 'KEYWORD'
          AND ad_group_criterion.negative = TRUE
    """
    for r in _search(client, customer_id, adgroup_q):
        rows.append({
            "scope": "ad_group",
            "criterion_id": str(r.ad_group_criterion.criterion_id),
            "text": r.ad_group_criterion.keyword.text,
            "match_type": r.ad_group_criterion.keyword.match_type.name,
            "campaign_id": str(r.campaign.id),
            "campaign_name": r.campaign.name,
            "ad_group_id": str(r.ad_group.id),
            "ad_group_name": r.ad_group.name,
        })
    return rows


def pull_ads(client, customer_id: str, days: int | None, since: str | None) -> list[dict]:
    start, end = _date_window(days, since)
    query = f"""
        SELECT
          ad_group_ad.ad.id,
          ad_group_ad.ad.type,
          ad_group_ad.status,
          ad_group_ad.ad.final_urls,
          ad_group_ad.ad.responsive_search_ad.headlines,
          ad_group_ad.ad.responsive_search_ad.descriptions,
          ad_group.id,
          ad_group.name,
          campaign.id,
          campaign.name,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.ctr
        FROM ad_group_ad
        WHERE segments.date BETWEEN '{start}' AND '{end}'
        ORDER BY metrics.cost_micros DESC
    """
    rows = []
    for r in _search(client, customer_id, query):
        ad = r.ad_group_ad.ad
        spend = micros_to_dollars(r.metrics.cost_micros)
        conv = float(r.metrics.conversions)
        headlines = [h.text for h in ad.responsive_search_ad.headlines] if ad.responsive_search_ad else []
        descriptions = [d.text for d in ad.responsive_search_ad.descriptions] if ad.responsive_search_ad else []
        rows.append({
            "ad_id": str(ad.id),
            "ad_type": ad.type_.name,
            "status": r.ad_group_ad.status.name,
            "final_urls": list(ad.final_urls),
            "headlines": headlines,
            "descriptions": descriptions,
            "ad_group_id": str(r.ad_group.id),
            "ad_group_name": r.ad_group.name,
            "campaign_id": str(r.campaign.id),
            "campaign_name": r.campaign.name,
            "impressions": int(r.metrics.impressions),
            "clicks": int(r.metrics.clicks),
            "spend_usd": spend,
            "conversions": round(conv, 2),
            "ctr": round(float(r.metrics.ctr), 4),
            "cpa_usd": round(spend / conv, 2) if conv else None,
        })
    return rows


def pull_conversions(client, customer_id: str, days: int | None, since: str | None) -> list[dict]:
    start, end = _date_window(days, since)
    query = f"""
        SELECT
          segments.conversion_action,
          segments.conversion_action_name,
          metrics.conversions,
          metrics.conversions_value
        FROM customer
        WHERE segments.date BETWEEN '{start}' AND '{end}'
    """
    rows = []
    for r in _search(client, customer_id, query):
        conv = float(r.metrics.conversions)
        rows.append({
            "conversion_action": r.segments.conversion_action,
            "conversion_action_name": r.segments.conversion_action_name,
            "conversions": round(conv, 2),
            "conv_value_usd": round(float(r.metrics.conversions_value), 2),
        })
    return rows


# ─── geo / demographics / device segments ─────────────────────────────────────

def pull_geo(client, customer_id: str, days: int | None, since: str | None) -> list[dict]:
    """Geographic performance — country/region/city. Critical for "which markets cost more"."""
    start, end = _date_window(days, since)
    query = f"""
        SELECT
          campaign.name,
          geographic_view.country_criterion_id,
          geographic_view.location_type,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM geographic_view
        WHERE segments.date BETWEEN '{start}' AND '{end}'
        ORDER BY metrics.cost_micros DESC
    """
    rows = []
    for r in _search(client, customer_id, query):
        spend = micros_to_dollars(r.metrics.cost_micros)
        conv = float(r.metrics.conversions)
        rows.append({
            "campaign_name": r.campaign.name,
            "country_criterion_id": str(r.geographic_view.country_criterion_id),
            "location_type": r.geographic_view.location_type.name,
            "impressions": int(r.metrics.impressions),
            "clicks": int(r.metrics.clicks),
            "spend_usd": spend,
            "conversions": round(conv, 2),
            "conv_value_usd": round(float(r.metrics.conversions_value), 2),
            "cpa_usd": round(spend / conv, 2) if conv else None,
        })
    return rows


def pull_age(client, customer_id: str, days: int | None, since: str | None) -> list[dict]:
    """Age-range performance."""
    start, end = _date_window(days, since)
    query = f"""
        SELECT
          campaign.name,
          ad_group.name,
          ad_group_criterion.age_range.type,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions
        FROM age_range_view
        WHERE segments.date BETWEEN '{start}' AND '{end}'
        ORDER BY metrics.cost_micros DESC
    """
    rows = []
    for r in _search(client, customer_id, query):
        spend = micros_to_dollars(r.metrics.cost_micros)
        conv = float(r.metrics.conversions)
        rows.append({
            "campaign_name": r.campaign.name,
            "ad_group_name": r.ad_group.name,
            "age_range": r.ad_group_criterion.age_range.type_.name,
            "impressions": int(r.metrics.impressions),
            "clicks": int(r.metrics.clicks),
            "spend_usd": spend,
            "conversions": round(conv, 2),
            "cpa_usd": round(spend / conv, 2) if conv else None,
        })
    return rows


def pull_gender(client, customer_id: str, days: int | None, since: str | None) -> list[dict]:
    """Gender performance."""
    start, end = _date_window(days, since)
    query = f"""
        SELECT
          campaign.name,
          ad_group.name,
          ad_group_criterion.gender.type,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions
        FROM gender_view
        WHERE segments.date BETWEEN '{start}' AND '{end}'
        ORDER BY metrics.cost_micros DESC
    """
    rows = []
    for r in _search(client, customer_id, query):
        spend = micros_to_dollars(r.metrics.cost_micros)
        conv = float(r.metrics.conversions)
        rows.append({
            "campaign_name": r.campaign.name,
            "ad_group_name": r.ad_group.name,
            "gender": r.ad_group_criterion.gender.type_.name,
            "impressions": int(r.metrics.impressions),
            "clicks": int(r.metrics.clicks),
            "spend_usd": spend,
            "conversions": round(conv, 2),
            "cpa_usd": round(spend / conv, 2) if conv else None,
        })
    return rows


def pull_device(client, customer_id: str, days: int | None, since: str | None) -> list[dict]:
    """Performance segmented by device (mobile/desktop/tablet)."""
    start, end = _date_window(days, since)
    query = f"""
        SELECT
          campaign.name,
          segments.device,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions
        FROM campaign
        WHERE segments.date BETWEEN '{start}' AND '{end}'
        ORDER BY metrics.cost_micros DESC
    """
    rows = []
    for r in _search(client, customer_id, query):
        spend = micros_to_dollars(r.metrics.cost_micros)
        conv = float(r.metrics.conversions)
        rows.append({
            "campaign_name": r.campaign.name,
            "device": r.segments.device.name,
            "impressions": int(r.metrics.impressions),
            "clicks": int(r.metrics.clicks),
            "spend_usd": spend,
            "conversions": round(conv, 2),
            "cpa_usd": round(spend / conv, 2) if conv else None,
        })
    return rows


# ─── audiences (Customer Match lists + remarketing) ───────────────────────────

def pull_user_lists(client, customer_id: str) -> list[dict]:
    """Customer Match + remarketing lists — size, match rate, eligibility.

    Mirrors what the nightly Customer Match sync writes.
    """
    query = """
        SELECT
          user_list.id,
          user_list.name,
          user_list.description,
          user_list.size_for_display,
          user_list.size_for_search,
          user_list.match_rate_percentage,
          user_list.eligible_for_search,
          user_list.eligible_for_display,
          user_list.type,
          user_list.membership_status,
          user_list.crm_based_user_list.upload_key_type
        FROM user_list
    """
    rows = []
    for r in _search(client, customer_id, query):
        ul = r.user_list
        rows.append({
            "user_list_id": str(ul.id),
            "name": ul.name,
            "type": ul.type_.name,
            "membership_status": ul.membership_status.name,
            "size_display": int(ul.size_for_display) if ul.size_for_display else None,
            "size_search": int(ul.size_for_search) if ul.size_for_search else None,
            "match_rate_pct": float(ul.match_rate_percentage)
                              if ul.match_rate_percentage else None,
            "eligible_search": bool(ul.eligible_for_search),
            "eligible_display": bool(ul.eligible_for_display),
            "upload_key_type": ul.crm_based_user_list.upload_key_type.name
                               if ul.crm_based_user_list else None,
        })
    return rows


# ─── recommendations + change history ─────────────────────────────────────────

def pull_recommendations(client, customer_id: str) -> list[dict]:
    """Pending Google Ads recommendations (the things Google nags about in UI)."""
    query = """
        SELECT
          recommendation.resource_name,
          recommendation.type,
          recommendation.dismissed,
          recommendation.impact.base_metrics.impressions,
          recommendation.impact.base_metrics.clicks,
          recommendation.impact.base_metrics.cost_micros,
          recommendation.impact.potential_metrics.impressions,
          recommendation.impact.potential_metrics.clicks,
          recommendation.impact.potential_metrics.cost_micros,
          campaign.id,
          campaign.name
        FROM recommendation
    """
    rows = []
    for r in _search(client, customer_id, query):
        rec = r.recommendation
        rows.append({
            "type": rec.type_.name,
            "dismissed": bool(rec.dismissed),
            "campaign_name": r.campaign.name if r.campaign else None,
            "base_impressions": int(rec.impact.base_metrics.impressions or 0),
            "potential_impressions": int(rec.impact.potential_metrics.impressions or 0),
            "base_cost_usd": micros_to_dollars(rec.impact.base_metrics.cost_micros),
            "potential_cost_usd": micros_to_dollars(rec.impact.potential_metrics.cost_micros),
            "resource": rec.resource_name,
        })
    return rows


def pull_change_history(client, customer_id: str, days: int | None,
                       since: str | None) -> list[dict]:
    """Audit log of changes made to the Google Ads account.

    Limitation: only last 90 days are available via change_event; older changes
    use change_status (status-only, no field-level deltas).
    """
    start, end = _date_window(days, since)
    query = f"""
        SELECT
          change_event.change_date_time,
          change_event.change_resource_type,
          change_event.client_type,
          change_event.user_email,
          change_event.changed_fields,
          change_event.resource_change_operation,
          campaign.id,
          campaign.name,
          ad_group.id,
          ad_group.name
        FROM change_event
        WHERE change_event.change_date_time >= '{start} 00:00:00'
          AND change_event.change_date_time <= '{end} 23:59:59'
        ORDER BY change_event.change_date_time DESC
        LIMIT 1000
    """
    rows = []
    for r in _search(client, customer_id, query):
        ev = r.change_event
        rows.append({
            "changed_at": str(ev.change_date_time),
            "operation": ev.resource_change_operation.name,
            "resource_type": ev.change_resource_type.name,
            "user_email": ev.user_email,
            "client_type": ev.client_type.name,
            "changed_fields": str(ev.changed_fields) if ev.changed_fields else None,
            "campaign_name": r.campaign.name if r.campaign else None,
            "ad_group_name": r.ad_group.name if r.ad_group else None,
        })
    return rows


# ─── asset reports (Performance Max + RSA ad strength) ────────────────────────

def pull_ad_strength(client, customer_id: str, days: int | None,
                     since: str | None) -> list[dict]:
    """RSA ad_strength + per-ad performance — flags weak/poor RSAs."""
    start, end = _date_window(days, since)
    query = f"""
        SELECT
          ad_group_ad.ad.id,
          ad_group_ad.ad.name,
          ad_group_ad.ad.type,
          ad_group_ad.status,
          ad_group_ad.ad_strength,
          ad_group_ad.policy_summary.approval_status,
          ad_group.name,
          campaign.name,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.ctr
        FROM ad_group_ad
        WHERE ad_group_ad.ad.type IN ('RESPONSIVE_SEARCH_AD', 'RESPONSIVE_DISPLAY_AD')
          AND segments.date BETWEEN '{start}' AND '{end}'
        ORDER BY ad_group_ad.ad_strength
    """
    rows = []
    for r in _search(client, customer_id, query):
        spend = micros_to_dollars(r.metrics.cost_micros)
        rows.append({
            "ad_id": str(r.ad_group_ad.ad.id),
            "ad_name": r.ad_group_ad.ad.name,
            "ad_type": r.ad_group_ad.ad.type_.name,
            "ad_strength": r.ad_group_ad.ad_strength.name,
            "approval_status": r.ad_group_ad.policy_summary.approval_status.name,
            "status": r.ad_group_ad.status.name,
            "campaign_name": r.campaign.name,
            "ad_group_name": r.ad_group.name,
            "impressions": int(r.metrics.impressions),
            "clicks": int(r.metrics.clicks),
            "spend_usd": spend,
            "ctr": round(float(r.metrics.ctr), 4),
        })
    return rows


def pull_assets(client, customer_id: str, days: int | None,
                since: str | None) -> list[dict]:
    """Asset-level performance for Performance Max + RSAs (headlines, descriptions, images).

    Surfaces which creative elements are pulling weight — the "asset_performance_label"
    is Google's GOOD/LOW/BEST rating per asset.
    """
    start, end = _date_window(days, since)
    query = f"""
        SELECT
          asset.id,
          asset.name,
          asset.type,
          asset.text_asset.text,
          asset.image_asset.full_size.url,
          ad_group_ad_asset_view.performance_label,
          ad_group_ad_asset_view.field_type,
          campaign.name,
          ad_group.name,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions
        FROM ad_group_ad_asset_view
        WHERE segments.date BETWEEN '{start}' AND '{end}'
        ORDER BY metrics.impressions DESC
    """
    rows = []
    for r in _search(client, customer_id, query):
        spend = micros_to_dollars(r.metrics.cost_micros)
        rows.append({
            "asset_id": str(r.asset.id),
            "asset_type": r.asset.type_.name,
            "field_type": r.ad_group_ad_asset_view.field_type.name,
            "performance_label": r.ad_group_ad_asset_view.performance_label.name,
            "text": r.asset.text_asset.text if r.asset.text_asset else None,
            "image_url": r.asset.image_asset.full_size.url
                         if r.asset.image_asset else None,
            "campaign_name": r.campaign.name,
            "ad_group_name": r.ad_group.name,
            "impressions": int(r.metrics.impressions),
            "clicks": int(r.metrics.clicks),
            "spend_usd": spend,
            "conversions": round(float(r.metrics.conversions), 2),
        })
    return rows


def pull_asset_groups(client, customer_id: str, days: int | None,
                     since: str | None) -> list[dict]:
    """Asset Group (Performance Max) performance + status."""
    start, end = _date_window(days, since)
    query = f"""
        SELECT
          asset_group.id,
          asset_group.name,
          asset_group.status,
          asset_group.primary_status,
          asset_group.ad_strength,
          campaign.name,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM asset_group
        WHERE segments.date BETWEEN '{start}' AND '{end}'
        ORDER BY metrics.cost_micros DESC
    """
    rows = []
    for r in _search(client, customer_id, query):
        spend = micros_to_dollars(r.metrics.cost_micros)
        conv = float(r.metrics.conversions)
        rows.append({
            "asset_group_id": str(r.asset_group.id),
            "name": r.asset_group.name,
            "status": r.asset_group.status.name,
            "primary_status": r.asset_group.primary_status.name,
            "ad_strength": r.asset_group.ad_strength.name,
            "campaign_name": r.campaign.name,
            "impressions": int(r.metrics.impressions),
            "clicks": int(r.metrics.clicks),
            "spend_usd": spend,
            "conversions": round(conv, 2),
            "conv_value_usd": round(float(r.metrics.conversions_value), 2),
            "cpa_usd": round(spend / conv, 2) if conv else None,
        })
    return rows


# ─── quality-score history (time-series) ──────────────────────────────────────

def pull_keyword_qs_history(client, customer_id: str, days: int | None,
                            since: str | None) -> list[dict]:
    """Daily Quality Score per keyword — trends, drops, and recoveries."""
    start, end = _date_window(days, since)
    query = f"""
        SELECT
          segments.date,
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.quality_info.quality_score,
          ad_group_criterion.quality_info.creative_quality_score,
          ad_group_criterion.quality_info.post_click_quality_score,
          ad_group_criterion.quality_info.search_predicted_ctr,
          campaign.name,
          ad_group.name
        FROM keyword_view
        WHERE segments.date BETWEEN '{start}' AND '{end}'
        ORDER BY segments.date, ad_group_criterion.criterion_id
    """
    rows = []
    for r in _search(client, customer_id, query):
        qi = r.ad_group_criterion.quality_info
        rows.append({
            "date": r.segments.date,
            "criterion_id": str(r.ad_group_criterion.criterion_id),
            "keyword": r.ad_group_criterion.keyword.text,
            "quality_score": int(qi.quality_score) if qi.quality_score else None,
            "creative_qs": qi.creative_quality_score.name if qi.creative_quality_score else None,
            "post_click_qs": qi.post_click_quality_score.name if qi.post_click_quality_score else None,
            "predicted_ctr_qs": qi.search_predicted_ctr.name if qi.search_predicted_ctr else None,
            "campaign_name": r.campaign.name,
            "ad_group_name": r.ad_group.name,
        })
    return rows


# ─── conversion action detail (attribution + lookback windows) ────────────────

def pull_conversion_actions(client, customer_id: str) -> list[dict]:
    """Conversion action config — lookback windows, attribution model, status.

    Surfaces the OCI window decisions (90d cash-conversion cycle, etc).
    """
    query = """
        SELECT
          conversion_action.id,
          conversion_action.name,
          conversion_action.status,
          conversion_action.type,
          conversion_action.category,
          conversion_action.primary_for_goal,
          conversion_action.counting_type,
          conversion_action.click_through_lookback_window_days,
          conversion_action.view_through_lookback_window_days,
          conversion_action.attribution_model_settings.attribution_model,
          conversion_action.attribution_model_settings.data_driven_model_status,
          conversion_action.value_settings.default_value,
          conversion_action.value_settings.default_currency_code
        FROM conversion_action
    """
    rows = []
    for r in _search(client, customer_id, query):
        ca = r.conversion_action
        ams = ca.attribution_model_settings
        rows.append({
            "id": str(ca.id),
            "name": ca.name,
            "status": ca.status.name,
            "type": ca.type_.name,
            "category": ca.category.name,
            "primary_for_goal": bool(ca.primary_for_goal),
            "counting_type": ca.counting_type.name,
            "click_window_days": int(ca.click_through_lookback_window_days)
                                 if ca.click_through_lookback_window_days else None,
            "view_window_days": int(ca.view_through_lookback_window_days)
                                if ca.view_through_lookback_window_days else None,
            "attribution_model": ams.attribution_model.name,
            "dda_status": ams.data_driven_model_status.name,
            "default_value": float(ca.value_settings.default_value)
                             if ca.value_settings.default_value else None,
            "currency": ca.value_settings.default_currency_code,
        })
    return rows


# ─── budget pacing ────────────────────────────────────────────────────────────

def pull_budget_pacing(client, customer_id: str, days: int | None,
                      since: str | None) -> list[dict]:
    """Daily budget vs MTD spend — surfaces "on pace / over / under" per campaign."""
    start, end = _date_window(days, since)
    query = f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign_budget.amount_micros,
          campaign_budget.period,
          campaign_budget.delivery_method,
          metrics.cost_micros,
          metrics.conversions
        FROM campaign
        WHERE segments.date BETWEEN '{start}' AND '{end}'
          AND campaign.status = 'ENABLED'
        ORDER BY metrics.cost_micros DESC
    """
    from datetime import date as _date
    today = _date.today()
    days_into_month = today.day
    rows = []
    for r in _search(client, customer_id, query):
        daily_budget = micros_to_dollars(r.campaign_budget.amount_micros)
        spend_window = micros_to_dollars(r.metrics.cost_micros)
        # Pace: daily budget * days_into_month is target MTD spend.
        pace_target = daily_budget * days_into_month if daily_budget else None
        pace_pct = (round(100 * spend_window / pace_target, 1)
                   if pace_target else None)
        rows.append({
            "campaign_id": str(r.campaign.id),
            "name": r.campaign.name,
            "status": r.campaign.status.name,
            "daily_budget_usd": daily_budget,
            "delivery_method": r.campaign_budget.delivery_method.name,
            "spend_window_usd": spend_window,
            "pace_target_usd": round(pace_target, 2) if pace_target else None,
            "pace_pct": pace_pct,
            "conversions": round(float(r.metrics.conversions), 2),
        })
    return rows


COLUMNS = {
    "campaigns": ["campaign_id", "name", "status", "channel", "daily_budget_usd",
                  "impressions", "clicks", "spend_usd", "conversions",
                  "conv_value_usd", "avg_cpc_usd", "ctr", "cpa_usd", "roas",
                  "search_is", "top_is", "abs_top_is",
                  "budget_lost_is", "rank_lost_is"],
    "adgroups": ["ad_group_id", "ad_group_name", "status", "campaign_name",
                 "impressions", "clicks", "spend_usd", "conversions", "cpa_usd"],
    "keywords": ["criterion_id", "keyword", "match_type", "status", "quality_score",
                 "ad_group_name", "campaign_name", "impressions", "clicks",
                 "spend_usd", "conversions", "cpa_usd"],
    "search_terms": ["search_term", "status", "campaign_name", "ad_group_name",
                     "impressions", "clicks", "spend_usd", "conversions", "cpa_usd"],
    "negatives": ["scope", "text", "match_type", "campaign_name", "ad_group_name", "criterion_id"],
    "ads": ["ad_id", "ad_type", "status", "campaign_name", "ad_group_name",
            "impressions", "clicks", "spend_usd", "conversions", "ctr", "cpa_usd"],
    "conversions": ["conversion_action_name", "conversions", "conv_value_usd"],
    "geo": ["campaign_name", "country_criterion_id", "location_type",
            "impressions", "clicks", "spend_usd", "conversions", "cpa_usd"],
    "age": ["campaign_name", "ad_group_name", "age_range",
            "impressions", "clicks", "spend_usd", "conversions", "cpa_usd"],
    "gender": ["campaign_name", "ad_group_name", "gender",
               "impressions", "clicks", "spend_usd", "conversions", "cpa_usd"],
    "device": ["campaign_name", "device", "impressions", "clicks",
               "spend_usd", "conversions", "cpa_usd"],
    "user-lists": ["user_list_id", "name", "type", "membership_status",
                   "size_display", "size_search", "match_rate_pct",
                   "eligible_search", "eligible_display", "upload_key_type"],
    "recommendations": ["type", "dismissed", "campaign_name",
                        "base_impressions", "potential_impressions",
                        "base_cost_usd", "potential_cost_usd"],
    "change-history": ["changed_at", "operation", "resource_type", "user_email",
                       "client_type", "campaign_name", "ad_group_name",
                       "changed_fields"],
    "ad-strength": ["ad_id", "ad_name", "ad_type", "ad_strength", "approval_status",
                    "status", "campaign_name", "ad_group_name",
                    "impressions", "clicks", "spend_usd", "ctr"],
    "assets": ["asset_type", "field_type", "performance_label", "text",
               "campaign_name", "ad_group_name", "impressions", "clicks",
               "spend_usd", "conversions"],
    "asset-groups": ["asset_group_id", "name", "status", "primary_status",
                     "ad_strength", "campaign_name", "impressions", "clicks",
                     "spend_usd", "conversions", "conv_value_usd", "cpa_usd"],
    "qs-history": ["date", "keyword", "quality_score", "creative_qs",
                   "post_click_qs", "predicted_ctr_qs",
                   "campaign_name", "ad_group_name"],
    "conversion-actions": ["id", "name", "status", "type", "category",
                           "primary_for_goal", "counting_type",
                           "click_window_days", "view_window_days",
                           "attribution_model", "dda_status",
                           "default_value", "currency"],
    "budget-pacing": ["name", "status", "daily_budget_usd", "delivery_method",
                      "spend_window_usd", "pace_target_usd", "pace_pct",
                      "conversions"],
}
