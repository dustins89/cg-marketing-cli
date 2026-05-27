#!/usr/bin/env python3
"""Deep YouTube audit: per-video retention curves, traffic sources, audience
demographics, end-screen/card CTR via YouTube Analytics API."""
import json
import sys
from datetime import date, timedelta
from pathlib import Path
import yaml
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

cfg = yaml.safe_load((Path.home()/'marketing-cli/google-ads.yaml').read_text())
creds = Credentials(
    token=None,
    refresh_token=cfg['refresh_token'],
    client_id=cfg['client_id'],
    client_secret=cfg['client_secret'],
    token_uri='https://oauth2.googleapis.com/token',
)
CHAN = cfg.get('youtube_channel_id', 'UC7NWR4r7mZm9sEESqHdgnew')

yt = build('youtube', 'v3', credentials=creds, cache_discovery=False)
yta = build('youtubeAnalytics', 'v2', credentials=creds, cache_discovery=False)

# Get all video IDs
ch = yt.channels().list(part='contentDetails', id=CHAN).execute()
upl = ch['items'][0]['contentDetails']['relatedPlaylists']['uploads']
playlist = yt.playlistItems().list(part='contentDetails', playlistId=upl, maxResults=50).execute()
video_ids = [it['contentDetails']['videoId'] for it in playlist['items']]
print(f'Channel videos: {len(video_ids)}', file=sys.stderr)

# Date range: ~365d
end = date.today().isoformat()
start = (date.today() - timedelta(days=365)).isoformat()

out = {'videos': []}

# Per-video Analytics — focus on top 8 by recent views
for vid in video_ids[:18]:
    print(f'  vid={vid}', file=sys.stderr)
    v_info = {'video_id': vid}
    # Basic stats
    vd = yt.videos().list(part='snippet,statistics,contentDetails,player', id=vid).execute()
    if not vd.get('items'):
        continue
    item = vd['items'][0]
    sn = item['snippet']
    v_info['title'] = sn['title']
    v_info['publishedAt'] = sn['publishedAt']
    v_info['views_total'] = int(item['statistics'].get('viewCount', 0))
    v_info['privacyStatus'] = item.get('status', {}).get('privacyStatus', 'public')

    # Per-video traffic source breakdown
    try:
        ts = yta.reports().query(
            ids=f'channel=={CHAN}',
            startDate=start, endDate=end,
            metrics='views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage',
            dimensions='insightTrafficSourceType',
            filters=f'video=={vid}',
            sort='-views',
        ).execute()
        v_info['traffic_sources'] = ts.get('rows', [])[:10]
        v_info['traffic_columns'] = [c['name'] for c in ts.get('columnHeaders', [])]
    except Exception as e:
        v_info['traffic_sources_err'] = str(e)[:100]

    # Audience demographics
    try:
        dm = yta.reports().query(
            ids=f'channel=={CHAN}',
            startDate=start, endDate=end,
            metrics='viewerPercentage',
            dimensions='ageGroup,gender',
            filters=f'video=={vid}',
        ).execute()
        v_info['demographics'] = dm.get('rows', [])
        v_info['demographics_columns'] = [c['name'] for c in dm.get('columnHeaders', [])]
    except Exception as e:
        v_info['demographics_err'] = str(e)[:100]

    # Retention summary (averageViewPercentage already in traffic_sources but get over time)
    try:
        rt = yta.reports().query(
            ids=f'channel=={CHAN}',
            startDate=start, endDate=end,
            metrics='views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,annotationClickThroughRate,annotationClickableImpressions,cardClickRate,cardImpressions,cardClicks',
            filters=f'video=={vid}',
        ).execute()
        v_info['summary'] = rt.get('rows', [{}])[0] if rt.get('rows') else []
        v_info['summary_columns'] = [c['name'] for c in rt.get('columnHeaders', [])]
    except Exception as e:
        v_info['summary_err'] = str(e)[:100]

    # Geography
    try:
        gd = yta.reports().query(
            ids=f'channel=={CHAN}',
            startDate=start, endDate=end,
            metrics='views',
            dimensions='country',
            filters=f'video=={vid}',
            sort='-views', maxResults=10,
        ).execute()
        v_info['geo'] = gd.get('rows', [])
    except Exception as e:
        v_info['geo_err'] = str(e)[:100]

    out['videos'].append(v_info)

# Channel-level aggregates
print('Pulling channel-level analytics...', file=sys.stderr)
try:
    overview = yta.reports().query(
        ids=f'channel=={CHAN}',
        startDate=start, endDate=end,
        metrics='views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost',
    ).execute()
    out['channel_summary'] = overview
except Exception as e:
    out['channel_summary_err'] = str(e)[:200]

# Top-of-funnel traffic sources (channel-wide)
try:
    ts = yta.reports().query(
        ids=f'channel=={CHAN}',
        startDate=start, endDate=end,
        metrics='views,estimatedMinutesWatched',
        dimensions='insightTrafficSourceType',
        sort='-views',
    ).execute()
    out['channel_traffic_sources'] = ts.get('rows', [])
    out['channel_traffic_columns'] = [c['name'] for c in ts.get('columnHeaders', [])]
except Exception as e:
    out['channel_traffic_err'] = str(e)[:200]

with open('/tmp/yt_deep.json', 'w') as f:
    json.dump(out, f, indent=2, default=str)
print(f'\n[done] /tmp/yt_deep.json ({len(out["videos"])} videos)', file=sys.stderr)
