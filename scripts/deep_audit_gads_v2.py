#!/usr/bin/env python3
"""Deep gads v2: search impression share (lost to budget/rank), per-extension
impression share, per-asset performance, auction insights metric."""
import json
import sys
from datetime import date, timedelta
from pathlib import Path
import yaml
from google.ads.googleads.client import GoogleAdsClient

cfg = yaml.safe_load((Path.home()/'marketing-cli/google-ads.yaml').read_text())
CUST = "YOUR_CUSTOMER_ID"

client = GoogleAdsClient.load_from_storage(str(Path.home()/'marketing-cli/google-ads.yaml'))
ga = client.get_service("GoogleAdsService")

today = date.today()
start = (today - timedelta(days=90)).isoformat()
end = today.isoformat()

def search(query):
    return [r for batch in ga.search_stream(customer_id=CUST, query=query) for r in batch.results]

def micros(v): return round((v or 0)/1_000_000, 2)

out = {}

# === CAMPAIGN-LEVEL impression share ===
print('Pulling campaign impression-share metrics...', file=sys.stderr)
camp_is = []
for r in search(f"""
    SELECT
      campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type,
      campaign_budget.amount_micros,
      metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions,
      metrics.search_impression_share,
      metrics.search_rank_lost_impression_share,
      metrics.search_budget_lost_impression_share,
      metrics.search_top_impression_share,
      metrics.search_absolute_top_impression_share,
      metrics.absolute_top_impression_percentage,
      metrics.top_impression_percentage
    FROM campaign
    WHERE segments.date BETWEEN '{start}' AND '{end}'
"""):
    c = r.campaign
    m = r.metrics
    camp_is.append({
        'id': str(c.id), 'name': c.name, 'status': c.status.name, 'channel': c.advertising_channel_type.name,
        'budget_usd': micros(r.campaign_budget.amount_micros),
        'impr': int(m.impressions), 'clicks': int(m.clicks), 'spend_usd': micros(m.cost_micros), 'conv': round(m.conversions,2),
        'is_search': round(m.search_impression_share,4) if m.search_impression_share else None,
        'is_rank_lost': round(m.search_rank_lost_impression_share,4) if m.search_rank_lost_impression_share else None,
        'is_budget_lost': round(m.search_budget_lost_impression_share,4) if m.search_budget_lost_impression_share else None,
        'is_top': round(m.search_top_impression_share,4) if m.search_top_impression_share else None,
        'is_abs_top': round(m.search_absolute_top_impression_share,4) if m.search_absolute_top_impression_share else None,
    })
out['campaign_impression_share'] = camp_is

# === Extension/Asset-level performance ===
print('Pulling extension impression-share + perf...', file=sys.stderr)
ext_is = []
for r in search(f"""
    SELECT
      asset.id, asset.type, asset.name,
      campaign.id, campaign.name,
      metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions, metrics.ctr
    FROM campaign_asset
    WHERE segments.date BETWEEN '{start}' AND '{end}'
"""):
    ca = r
    ext_is.append({
        'asset_id': str(ca.asset.id),
        'asset_type': ca.asset.type_.name,
        'asset_name': ca.asset.name or '',
        'campaign_name': ca.campaign.name,
        'impr': int(ca.metrics.impressions),
        'clicks': int(ca.metrics.clicks),
        'spend_usd': micros(ca.metrics.cost_micros),
        'conv': round(ca.metrics.conversions, 2),
        'ctr': round(ca.metrics.ctr, 4) if ca.metrics.ctr else 0,
    })
out['campaign_asset_perf'] = ext_is

# === Ad group asset perf (sitelinks, callouts per ad group) ===
print('Pulling ad-group-level asset perf...', file=sys.stderr)
agap = []
for r in search(f"""
    SELECT
      asset.id, asset.type,
      ad_group.id, ad_group.name,
      campaign.id, campaign.name,
      metrics.impressions, metrics.clicks
    FROM ad_group_asset
    WHERE segments.date BETWEEN '{start}' AND '{end}'
"""):
    agap.append({
        'asset_id': str(r.asset.id),
        'asset_type': r.asset.type_.name,
        'ad_group': r.ad_group.name,
        'campaign': r.campaign.name,
        'impr': int(r.metrics.impressions),
        'clicks': int(r.metrics.clicks),
    })
out['ad_group_asset_perf'] = agap

# === Geo-level impression share — top spending zips ===
print('Pulling geo-level impression share...', file=sys.stderr)
geo_is = []
for r in search(f"""
    SELECT
      campaign.name,
      geographic_view.location_type,
      segments.geo_target_city,
      segments.geo_target_metro,
      metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions
    FROM geographic_view
    WHERE segments.date BETWEEN '{start}' AND '{end}'
"""):
    if r.metrics.impressions == 0: continue
    geo_is.append({
        'campaign': r.campaign.name,
        'location_type': r.geographic_view.location_type.name,
        'city': r.segments.geo_target_city,
        'metro': r.segments.geo_target_metro,
        'impr': int(r.metrics.impressions),
        'clicks': int(r.metrics.clicks),
        'spend_usd': micros(r.metrics.cost_micros),
        'conv': round(r.metrics.conversions,2),
    })
out['geographic_perf'] = sorted(geo_is, key=lambda x: -x['impr'])[:100]

# === Hourly breakdown for active campaigns ===
print('Pulling hour-of-day breakdown...', file=sys.stderr)
hourly = []
for r in search(f"""
    SELECT
      campaign.name,
      segments.hour,
      segments.day_of_week,
      metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions
    FROM campaign
    WHERE segments.date BETWEEN '{start}' AND '{end}'
"""):
    if r.metrics.impressions == 0: continue
    hourly.append({
        'campaign': r.campaign.name,
        'hour': int(r.segments.hour),
        'dow': r.segments.day_of_week.name,
        'impr': int(r.metrics.impressions),
        'clicks': int(r.metrics.clicks),
        'spend_usd': micros(r.metrics.cost_micros),
        'conv': round(r.metrics.conversions,2),
    })
out['hourly_breakdown'] = hourly

with open('/tmp/gads_deep_v2.json', 'w') as f:
    json.dump(out, f, indent=2, default=str)
print(f'[done] /tmp/gads_deep_v2.json', file=sys.stderr)
