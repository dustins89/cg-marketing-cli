#!/usr/bin/env python3
"""One-shot deep-audit pull for Google Ads: ad strength, asset perf,
extensions, audiences, conflicts. Writes JSON files to /tmp/gads_deep_*.json."""
import json
import os
import sys
import yaml
from datetime import date, timedelta
from pathlib import Path
from google.ads.googleads.client import GoogleAdsClient

TODAY = date.today()
START = (TODAY - timedelta(days=90)).isoformat()
END = TODAY.isoformat()

HERE = Path(__file__).resolve().parents[1]
YAML = HERE / "google-ads.yaml"
cfg = yaml.safe_load(YAML.read_text())
CUSTOMER_ID = cfg.get("login_customer_id_target") or cfg.get("customer_id") or "YOUR_CUSTOMER_ID"
LOGIN = cfg.get("login_customer_id") or "YOUR_MCC_ID"

client = GoogleAdsClient.load_from_storage(str(YAML))
ga = client.get_service("GoogleAdsService")


def search(query):
    rows = []
    stream = ga.search_stream(customer_id=str(CUSTOMER_ID), query=query)
    for batch in stream:
        for row in batch.results:
            rows.append(row)
    return rows


def micros(v):
    return round(v / 1_000_000, 2) if v else 0


def dump(name, rows):
    p = f"/tmp/gads_deep_{name}.json"
    with open(p, "w") as f:
        json.dump(rows, f, indent=2, default=str)
    print(f"[ok] {p} ({len(rows)} rows)")


# --- 1. Ad-level strength + last-90d perf for every ad ---
print("Pulling ad_strength per ad...")
ad_rows = []
for r in search(
    """
    SELECT
      ad_group_ad.ad.id,
      ad_group_ad.ad.name,
      ad_group_ad.ad_strength,
      ad_group_ad.policy_summary.approval_status,
      ad_group_ad.status,
      ad_group_ad.ad.type,
      ad_group_ad.ad.final_urls,
      ad_group_ad.ad.responsive_search_ad.path1,
      ad_group_ad.ad.responsive_search_ad.path2,
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
    WHERE segments.date BETWEEN '2026-02-15' AND '2026-05-16'
    ORDER BY metrics.cost_micros DESC
    """
):
    ad = r.ad_group_ad
    ad_rows.append(
        {
            "ad_id": str(ad.ad.id),
            "ad_strength": ad.ad_strength.name,
            "approval": ad.policy_summary.approval_status.name,
            "status": ad.status.name,
            "type": ad.ad.type_.name,
            "path1": ad.ad.responsive_search_ad.path1 or "",
            "path2": ad.ad.responsive_search_ad.path2 or "",
            "final_urls": list(ad.ad.final_urls),
            "ad_group_id": str(r.ad_group.id),
            "ad_group_name": r.ad_group.name,
            "campaign_id": str(r.campaign.id),
            "campaign_name": r.campaign.name,
            "impressions": int(r.metrics.impressions),
            "clicks": int(r.metrics.clicks),
            "spend_usd": micros(r.metrics.cost_micros),
            "conversions": round(r.metrics.conversions, 2),
            "ctr": round(r.metrics.ctr, 4),
        }
    )
dump("ads", ad_rows)


# --- 2. Asset-level performance (headline/description ratings) ---
print("Pulling per-asset performance...")
asset_rows = []
for r in search(
    """
    SELECT
      ad_group_ad_asset_view.ad_group_ad,
      ad_group_ad_asset_view.field_type,
      ad_group_ad_asset_view.performance_label,
      ad_group_ad_asset_view.policy_summary,
      asset.id,
      asset.type,
      asset.text_asset.text,
      asset.image_asset.full_size.url,
      ad_group.id,
      ad_group.name,
      campaign.id,
      campaign.name
    FROM ad_group_ad_asset_view
    """
):
    a = r.asset
    v = r.ad_group_ad_asset_view
    asset_rows.append(
        {
            "asset_id": str(a.id),
            "asset_type": a.type_.name,
            "field_type": v.field_type.name,
            "performance_label": v.performance_label.name,
            "text": a.text_asset.text or "",
            "image_url": a.image_asset.full_size.url or "",
            "ad_group_id": str(r.ad_group.id),
            "ad_group_name": r.ad_group.name,
            "campaign_name": r.campaign.name,
        }
    )
dump("assets", asset_rows)


# --- 3. Extension assets at customer level ---
print("Pulling customer-level extension assets...")
ext_rows = []
for r in search(
    """
    SELECT
      customer_asset.asset,
      customer_asset.status,
      asset.id,
      asset.type,
      asset.name,
      asset.text_asset.text,
      asset.sitelink_asset.link_text,
      asset.sitelink_asset.description1,
      asset.sitelink_asset.description2,
      asset.callout_asset.callout_text,
      asset.structured_snippet_asset.header,
      asset.structured_snippet_asset.values,
      asset.promotion_asset.promotion_target,
      asset.call_asset.country_code,
      asset.call_asset.phone_number,
      asset.image_asset.full_size.url,
      asset.image_asset.full_size.width_pixels,
      asset.image_asset.full_size.height_pixels,
      asset.lead_form_asset.business_name,
      asset.lead_form_asset.headline,
      asset.lead_form_asset.description,
      asset.lead_form_asset.call_to_action_type
    FROM customer_asset
    """
):
    a = r.asset
    ext_rows.append(
        {
            "asset_id": str(a.id),
            "asset_type": a.type_.name,
            "name": a.name or "",
            "status": r.customer_asset.status.name,
            "text": a.text_asset.text or "",
            "sitelink_text": a.sitelink_asset.link_text or "",
            "sitelink_desc1": a.sitelink_asset.description1 or "",
            "sitelink_desc2": a.sitelink_asset.description2 or "",
            "callout_text": a.callout_asset.callout_text or "",
            "ss_header": a.structured_snippet_asset.header or "",
            "ss_values": list(a.structured_snippet_asset.values),
            "promo_target": a.promotion_asset.promotion_target or "",
            "call_phone": a.call_asset.phone_number or "",
            "img_url": a.image_asset.full_size.url or "",
            "img_w": a.image_asset.full_size.width_pixels or 0,
            "img_h": a.image_asset.full_size.height_pixels or 0,
            "leadform_business": a.lead_form_asset.business_name or "",
            "leadform_headline": a.lead_form_asset.headline or "",
            "leadform_desc": a.lead_form_asset.description or "",
            "leadform_cta": a.lead_form_asset.call_to_action_type.name if a.lead_form_asset.call_to_action_type else "",
        }
    )
dump("extensions", ext_rows)


# --- 4. Keyword Quality Score per keyword ---
print("Pulling keyword QS...")
qs_rows = []
for r in search(
    """
    SELECT
      ad_group_criterion.criterion_id,
      ad_group_criterion.keyword.text,
      ad_group_criterion.keyword.match_type,
      ad_group_criterion.status,
      ad_group_criterion.quality_info.quality_score,
      ad_group_criterion.quality_info.creative_quality_score,
      ad_group_criterion.quality_info.post_click_quality_score,
      ad_group_criterion.quality_info.search_predicted_ctr,
      ad_group.id,
      ad_group.name,
      campaign.id,
      campaign.name,
      metrics.impressions,
      metrics.clicks,
      metrics.cost_micros,
      metrics.conversions
    FROM keyword_view
    WHERE segments.date BETWEEN '2026-02-15' AND '2026-05-16'
    """
):
    c = r.ad_group_criterion
    qi = c.quality_info
    qs_rows.append(
        {
            "criterion_id": str(c.criterion_id),
            "keyword": c.keyword.text,
            "match_type": c.keyword.match_type.name,
            "status": c.status.name,
            "qs": int(qi.quality_score) if qi.quality_score else 0,
            "creative_qs": qi.creative_quality_score.name,
            "lp_qs": qi.post_click_quality_score.name,
            "expected_ctr": qi.search_predicted_ctr.name,
            "ad_group_name": r.ad_group.name,
            "campaign_name": r.campaign.name,
            "impressions": int(r.metrics.impressions),
            "clicks": int(r.metrics.clicks),
            "spend_usd": micros(r.metrics.cost_micros),
            "conversions": round(r.metrics.conversions, 2),
        }
    )
dump("keyword_qs", qs_rows)


# --- 5. Audience criteria at ad-group and campaign level ---
print("Pulling audience criteria...")
aud_rows = []
for r in search(
    """
    SELECT
      ad_group_criterion.criterion_id,
      ad_group_criterion.type,
      ad_group_criterion.user_list.user_list,
      ad_group_criterion.user_interest.user_interest_category,
      ad_group_criterion.custom_audience.custom_audience,
      ad_group_criterion.status,
      ad_group.id,
      ad_group.name,
      campaign.id,
      campaign.name
    FROM ad_group_criterion
    WHERE ad_group_criterion.type IN ('USER_LIST','USER_INTEREST','CUSTOM_AUDIENCE','AUDIENCE','LIFE_EVENT')
    """
):
    c = r.ad_group_criterion
    aud_rows.append(
        {
            "criterion_id": str(c.criterion_id),
            "type": c.type_.name,
            "status": c.status.name,
            "user_list": c.user_list.user_list or "",
            "user_interest": c.user_interest.user_interest_category or "",
            "custom_audience": c.custom_audience.custom_audience or "",
            "ad_group_name": r.ad_group.name,
            "campaign_name": r.campaign.name,
        }
    )
dump("audiences", aud_rows)


# --- 6. Geo targets + bid adjustments ---
print("Pulling geo + device + ad-schedule bid adjustments...")
bid_rows = []
for r in search(
    """
    SELECT
      campaign_criterion.criterion_id,
      campaign_criterion.type,
      campaign_criterion.status,
      campaign_criterion.negative,
      campaign_criterion.bid_modifier,
      campaign_criterion.location.geo_target_constant,
      campaign_criterion.device.type,
      campaign_criterion.ad_schedule.day_of_week,
      campaign_criterion.ad_schedule.start_hour,
      campaign_criterion.ad_schedule.end_hour,
      campaign.id,
      campaign.name
    FROM campaign_criterion
    WHERE campaign_criterion.type IN ('LOCATION','DEVICE','AD_SCHEDULE')
    """
):
    c = r.campaign_criterion
    bid_rows.append(
        {
            "criterion_id": str(c.criterion_id),
            "type": c.type_.name,
            "status": c.status.name,
            "negative": bool(c.negative),
            "bid_modifier": round(c.bid_modifier, 3) if c.bid_modifier else None,
            "geo": c.location.geo_target_constant or "",
            "device": c.device.type_.name if c.device else "",
            "schedule_day": c.ad_schedule.day_of_week.name if c.ad_schedule else "",
            "schedule_start": c.ad_schedule.start_hour or 0,
            "schedule_end": c.ad_schedule.end_hour or 0,
            "campaign_name": r.campaign.name,
        }
    )
dump("bid_modifiers", bid_rows)


# --- 7. Conversion action config ---
print("Pulling conversion action config...")
ca_rows = []
for r in search(
    """
    SELECT
      conversion_action.id,
      conversion_action.name,
      conversion_action.status,
      conversion_action.type,
      conversion_action.category,
      conversion_action.value_settings.default_value,
      conversion_action.value_settings.always_use_default_value,
      conversion_action.counting_type,
      conversion_action.attribution_model_settings.attribution_model,
      conversion_action.click_through_lookback_window_days,
      conversion_action.view_through_lookback_window_days,
      conversion_action.primary_for_goal,
      conversion_action.include_in_conversions_metric
    FROM conversion_action
    """
):
    ca = r.conversion_action
    ca_rows.append(
        {
            "id": str(ca.id),
            "name": ca.name,
            "status": ca.status.name,
            "type": ca.type_.name,
            "category": ca.category.name,
            "primary_for_goal": bool(ca.primary_for_goal),
            "include_in_conv_metric": bool(ca.include_in_conversions_metric),
            "default_value": round(ca.value_settings.default_value, 2),
            "always_use_default": bool(ca.value_settings.always_use_default_value),
            "counting_type": ca.counting_type.name,
            "attribution_model": ca.attribution_model_settings.attribution_model.name,
            "ctw_lookback_days": int(ca.click_through_lookback_window_days),
            "vtw_lookback_days": int(ca.view_through_lookback_window_days),
        }
    )
dump("conversion_actions", ca_rows)


print("Done.")
