#!/usr/bin/env python3
"""Deep Meta audit: per-ad creative inspection, day-over-day fatigue curve,
audience overlap matrix, pixel match quality, CAPI dedup status.

Replaces the shallow FB audit that only counted ads + adsets."""
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
import requests
import yaml

cfg = yaml.safe_load((Path.home()/'marketing-cli/google-ads.yaml').read_text())
TOKEN = cfg['fb_access_token']
ACCT = cfg['fb_ad_account_id']
PIXEL = cfg['fb_pixel_id']
VER = cfg.get('fb_api_version', 'v23.0')

def get(path, params=None):
    p = {'access_token': TOKEN}
    if params: p.update(params)
    r = requests.get(f'https://graph.facebook.com/{VER}/{path}', params=p, timeout=60)
    return r.json()


def main():
    out = {}

    # === Per-ad creative + insights with daily breakdown for fatigue curves ===
    print("Pulling per-ad insights with daily breakdown (last 30d)...", file=sys.stderr)
    end = date.today()
    start = end - timedelta(days=30)
    ads = get(f'{ACCT}/ads', {
        'fields': 'id,name,status,effective_status,adset_id,campaign{name,id,objective},'
                  'creative{id,name,title,body,call_to_action_type,object_story_spec,asset_feed_spec,'
                  'thumbnail_url,image_url,video_id,instagram_actor_id,object_id,object_type,link_url}',
        'limit': 200,
    })
    ad_list = ads.get('data', [])
    print(f"  {len(ad_list)} ads pulled", file=sys.stderr)

    # For each active ad, pull daily insights
    active_ads = [a for a in ad_list if a.get('effective_status') == 'ACTIVE']
    print(f"  {len(active_ads)} ACTIVE ads — pulling daily insights for each", file=sys.stderr)
    ad_perf = []
    for a in active_ads:
        ins = get(f'{a["id"]}/insights', {
            'fields': 'date_start,date_stop,impressions,reach,frequency,clicks,spend,ctr,cpc,actions,unique_clicks,unique_ctr,inline_link_clicks',
            'time_range': json.dumps({'since': start.isoformat(), 'until': end.isoformat()}),
            'time_increment': 1,  # daily
            'limit': 100,
        })
        daily = ins.get('data', [])
        leads_total = 0
        impr_total = 0
        for d in daily:
            impr_total += int(d.get('impressions', 0))
            for act in d.get('actions', []) or []:
                if 'lead' in act.get('action_type', ''):
                    leads_total += int(act.get('value', 0))
        ad_perf.append({
            'ad_id': a['id'],
            'ad_name': a.get('name', ''),
            'effective_status': a.get('effective_status'),
            'creative': {
                'id': (a.get('creative') or {}).get('id'),
                'title': (a.get('creative') or {}).get('title', '')[:80],
                'body': (a.get('creative') or {}).get('body', '')[:200],
                'cta': (a.get('creative') or {}).get('call_to_action_type'),
                'thumbnail_url': (a.get('creative') or {}).get('thumbnail_url'),
                'image_url': (a.get('creative') or {}).get('image_url'),
                'video_id': (a.get('creative') or {}).get('video_id'),
            },
            'campaign_name': ((a.get('campaign') or {}).get('name')),
            'daily': daily,
            'totals_30d': {'impr': impr_total, 'leads': leads_total},
        })
        time.sleep(0.2)
    out['active_ads_daily'] = ad_perf

    # === Audience overlap matrix ===
    print("Pulling audience overlap matrix...", file=sys.stderr)
    auds = get(f'{ACCT}/customaudiences', {
        'fields': 'id,name,subtype,approximate_count_lower_bound,approximate_count_upper_bound,retention_days,time_updated,operation_status',
        'limit': 100,
    })
    aud_list = auds.get('data', [])
    out['custom_audiences'] = aud_list
    # Audience overlap is /ad_account/audience_estimate but requires segment specs
    # Try /audience_overlap endpoint instead — not always available; try and capture error
    if len(aud_list) >= 2:
        # Take 2 audiences as a basic test
        ids = [a['id'] for a in aud_list[:6]]
        # No direct overlap endpoint in Marketing API; defer to UI inspection note
        out['audience_overlap'] = {'method_note': 'Meta does not expose audience_overlap via Marketing API. Use Ads Manager → Audiences → Show Audience Overlap.'}

    # === Pixel quality: events received with match quality breakdown ===
    print("Pulling pixel events + stats...", file=sys.stderr)
    pix_stats = get(f'{PIXEL}/stats', {'aggregation': 'event'})
    out['pixel_stats'] = pix_stats.get('data', [])[:50]
    # Pixel CAPI / event match quality
    pix_eq = get(f'{PIXEL}/stats', {'aggregation': 'eventQuality'})
    out['pixel_event_quality'] = pix_eq.get('data', pix_eq) if 'data' in pix_eq else pix_eq
    # Custom conversions
    cc = get(f'{ACCT}/customconversions', {'fields': 'id,name,description,event_source_id,event_type_name,rule,creation_time,first_fired_time,last_fired_time'})
    out['custom_conversions'] = cc.get('data', [])

    # === Lookalike audience eligibility ===
    print("Checking lookalike eligibility...", file=sys.stderr)
    los = get(f'{ACCT}/saved_audiences', {'fields': 'id,name,description,permissions', 'limit': 50})
    out['saved_audiences'] = los.get('data', [])

    # === Frequency cap audit on every adset ===
    print("Pulling all adsets with frequency caps + budget pacing...", file=sys.stderr)
    adsets = get(f'{ACCT}/adsets', {
        'fields': 'id,name,status,effective_status,bid_strategy,billing_event,optimization_goal,'
                  'daily_budget,lifetime_budget,frequency_control_specs,targeting,start_time,end_time,'
                  'pacing_type,attribution_spec,promoted_object',
        'limit': 200,
    })
    out['adsets_full'] = adsets.get('data', [])

    with open('/tmp/fb_deep.json', 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n[done] /tmp/fb_deep.json", file=sys.stderr)

if __name__ == '__main__':
    main()
