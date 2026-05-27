#!/usr/bin/env python3
"""Deep Maps audit: per-competitor full Places Details for top 5 by review count.
Captures hours, current status, reviews list with text + author, photos, services
type list. Then computes review velocity (reviews/month by parsing dates)."""
import json
import sys
from datetime import date, timedelta, datetime
from pathlib import Path
import requests
import yaml
import time

cfg = yaml.safe_load((Path.home()/'marketing-cli/google-ads.yaml').read_text())
KEY = cfg['maps_api_key']

# Top competitors from earlier maps pull.
# REPLACE with Google Places IDs of competitors in your market. Run
# `maps search "<your competitor name>" --lat <lat> --lng <lng>` to find IDs.
COMPETITORS = [
    # "ChIJ..."  # Example: place ID for "Competitor Name #1"
    # "ChIJ..."  # Example: place ID for "Competitor Name #2"
]

# Re-search to get fresh IDs
def text_search(query, lat=0.0, lng=0.0, radius=20000):
    r = requests.post(
        'https://places.googleapis.com/v1/places:searchText',
        headers={
            'Content-Type': 'application/json',
            'X-Goog-Api-Key': KEY,
            'X-Goog-FieldMask': 'places.id,places.displayName,places.rating,places.userRatingCount,places.formattedAddress,places.websiteUri,places.googleMapsUri,places.primaryType,places.types,places.currentOpeningHours,places.regularOpeningHours,places.businessStatus,places.priceLevel,places.editorialSummary,places.servesBeer',
        },
        json={
            'textQuery': query,
            'locationBias': {'circle': {'center': {'latitude': lat, 'longitude': lng}, 'radius': radius}},
            'maxResultCount': 20,
        },
        timeout=30,
    )
    return r.json()

queries = ['we buy houses <your-city>', 'sell house fast <your-city>', 'cash home buyers <your-city>', '<your-city> home buyers', 'cash for houses <your-city>']
all_places = {}
for q in queries:
    print(f'search: {q}', file=sys.stderr)
    res = text_search(q)
    for p in res.get('places', []):
        all_places[p['id']] = p

print(f'Distinct places: {len(all_places)}', file=sys.stderr)
# Sort by review count
ranked = sorted(all_places.values(), key=lambda x: -(x.get('userRatingCount') or 0))

# Pull full details on top 10
details = []
for p in ranked[:10]:
    pid = p['id']
    print(f'  detail: {pid} {p.get("displayName",{}).get("text","?")}', file=sys.stderr)
    try:
        r = requests.get(
            f'https://places.googleapis.com/v1/places/{pid}',
            headers={
                'X-Goog-Api-Key': KEY,
                'X-Goog-FieldMask': 'id,displayName,formattedAddress,nationalPhoneNumber,internationalPhoneNumber,websiteUri,googleMapsUri,rating,userRatingCount,reviews,photos,types,primaryType,businessStatus,currentOpeningHours,regularOpeningHours,priceLevel,editorialSummary,paymentOptions,parkingOptions,accessibilityOptions',
            },
            timeout=30,
        )
        d = r.json()
        # Review velocity: parse review dates
        reviews = d.get('reviews', [])
        review_dates = []
        for rv in reviews:
            t = rv.get('publishTime') or rv.get('relativePublishTimeDescription','')
            if t:
                try:
                    dt = datetime.fromisoformat(t.replace('Z','+00:00'))
                    review_dates.append(dt)
                except: pass
        # Velocity = reviews per month, last 90d
        cutoff = datetime.now(review_dates[0].tzinfo if review_dates else None) - timedelta(days=90)
        recent = [d for d in review_dates if d > cutoff] if review_dates else []
        d['_review_velocity_90d'] = len(recent)
        d['_review_dates_sample'] = [dt.isoformat() for dt in review_dates[:10]]
        d['_photo_count'] = len(d.get('photos', []))
        # Response rate (replies field in each review)
        responses = sum(1 for rv in reviews if rv.get('authorAttribution', {}).get('displayName') and 'Response from the owner' in str(rv))
        # Actually responses appear as `reply` field
        replies = sum(1 for rv in reviews if rv.get('reply'))
        d['_response_count'] = replies
        d['_review_text_samples'] = [(rv.get('rating'), (rv.get('text',{}) or {}).get('text','')[:200]) for rv in reviews[:5]]
        details.append(d)
    except Exception as e:
        details.append({'id': pid, 'err': str(e)[:200]})
    time.sleep(0.3)

with open('/tmp/maps_deep.json', 'w') as f:
    json.dump({'places': details, 'queries_searched': queries}, f, indent=2, default=str)
print(f'[done] /tmp/maps_deep.json ({len(details)} competitors)', file=sys.stderr)
