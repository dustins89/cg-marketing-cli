# GA4 Measurement Protocol Fan-Out — LIVE

**Status:** 🟢 Activated 2026-05-16. Companion to Google Ads OCI (`OCI_ACTIVATED.md`). Same SF queue table, parallel pipeline, sends every conversion to GA4 + BigQuery regardless of click ID.

## Why this exists

Google Ads OCI only fires when SF records have a click ID. About 80% of DBH lead volume (Voice Nation phone, organic, direct, Facebook, referral) gets `Skipped_No_ClickId` on the OCI side. GA4 MP catches all of them — events land in GA4 regardless of source, and auto-flow to BigQuery for unlimited-time-horizon analysis.

Specifically critical for DBH's **120-day cash conversion cycle** vs Google Ads' 90-day click window: `SF - Deal Closed` events fire 120 days after click on average — Google rejects most as `CLICK_NOT_FOUND`, but GA4 has no time limit and BigQuery stores forever.

## Architecture

```
SF queue row (single source of truth)
  ├─→ Status__c            → GoogleAdsOciQueueable    → Google Ads OCI (needs click ID)
  └─→ GA4_Status__c        → GoogleAnalyticsMpQueueable → GA4 MP → BigQuery (streaming + daily)
        ↑ client_id = GA4_Client_Id__c (from _ga cookie) OR 'sfid-' + Source_Record_Id__c (synth)
        ↑ event_name from Google_Ads_Conversion_Action__mdt.GA4_Event_Name__c
```

Both pipelines poll their own status column. Each row tracks independently — a row can be `Skipped_No_ClickId` for Ads but `Uploaded` for GA4. That's the design.

## Event mapping

| SF stage | GA4 event name | Params sent | Native ecommerce? |
|---|---|---|---|
| SF_Calendly_Booked | `sf_calendly_booked` | sf_record_id, sf_queue_row_id | no (custom) |
| SF_Appointment_Scheduled | `sf_appointment_scheduled` | sf_record_id, sf_queue_row_id | no (custom) |
| SF_Contract_Signed | `sf_contract_signed` | sf_record_id, value, currency=USD | no (custom) |
| SF_Deal_Closed | **`purchase`** | transaction_id, value, currency=USD | ✅ YES — lands in GA4 Ecommerce reports |

## Conversion values (Apex sends these per-row; Google Ads conv-action defaults also set)

Same value math as OCI — see `OCI_ACTIVATED.md § DBH funnel economics + Conversion value math` for the full breakdown. Quick reference:

| Stage | Per-record value | Sent by Apex? | Sourced from |
|---|---|---|---|
| Calendly Booked | $1,950 | no (count-only) | conv action default |
| Appointment Scheduled | $3,000 | no (count-only) | conv action default |
| Contract Signed | $25,500 typical | YES | `Tx.Projected_Profit__c` |
| Deal Closed | $30,000 typical | YES | `Tx.Actual_Profit__c` |

For GA4: count-only events still get `value: 0` in the `purchase` payload to satisfy GA4's ecommerce schema. Contract Signed + Deal Closed carry real margin numbers.

## DBH funnel economics

```
Calendly phone consults booked / mo
  └─ ×0.65 convert to real Appointment Scheduled
85 Appointments Scheduled / mo
  ├─ ×0.85 attended → 72 attended
  ├─ ×0.14 sign today (goal 0.25) → 10 contracts (goal 18)
  ├─ ×0.85 close → 8 closed (goal 15)
  └─ ×$30K profit → $240K/mo gross (goal $459K/mo)
```

## Live components

**5 new fields on `Google_Ads_Conversion_Queue__c`:**
- `GA4_Status__c` — Picklist Pending(default) / Uploaded / Failed / Skipped
- `GA4_Last_Error__c` — Long Text Area 1024
- `GA4_Uploaded_At__c` — DateTime
- `GA4_Attempts__c` — Number(3,0), default 0
- `GA4_Client_Id__c` — Text(100), captured from _ga cookie via GTM

**3 new `GA4_Client_Id__c` fields on Lead / Opportunity / Left_Main__Transactions__c** — Text(100). Propagates via Lead Convert mapping (Dustin set up 2026-05-16) and `Dustin_Create_New_Transaction` flow (both wholesale + sell-side paths).

**New `Google_Ads_Conversion_Action__mdt.GA4_Event_Name__c`** field — Text(80), populated on all 4 records (see Event Mapping table above).

**New custom metadata `GA4_Config__mdt`** with single record `Default`:
- `Measurement_Id__c` = `G-VHGF74SKQ6` (Carrot Site web stream on property YOUR_GA4_PROPERTY_ID)
- `API_Secret__c` = (created via GA4 Admin API 2026-05-16)
- `Active__c` = true

**Apex:**
- `GoogleAnalyticsMpQueueable.cls` — POSTs to `https://www.google-analytics.com/mp/collect?measurement_id={X}&api_secret={Y}`. Synthesizes client_id as `sfid-{Source_Record_Id__c}` if `GA4_Client_Id__c` blank. Special-cases `purchase` event for GA4 ecommerce params.
- `GoogleAnalyticsMpSchedulable.cls` — polls `WHERE GA4_Status__c='Pending' AND GA4_Attempts__c<5`, batches 100/Queueable.
- Both with `_Test` classes; 12/12 tests passing.

**RemoteSiteSetting `Google_Analytics_MP`** → `https://www.google-analytics.com` (required for direct HTTP callout since GA4 MP uses URL-param auth, not header auth = no Named Credential).

**Schedule**: 4 CronTrigger jobs `GA4 MP Uploader :0/15/30/45`.

**GTM tag**: `GA4 - Capture client_id into form field` (Custom HTML, fires on All Pages, published in v60 2026-05-16). Reads `_ga` cookie → writes to `input[name*="ga4_client_id"]` and `input.ga4-cid-field` selectors.

## BigQuery auto-export — already linked

Property YOUR_GA4_PROPERTY_ID has BigQuery linking active with both streaming (events within minutes) and daily export enabled. All GA4 events including the new `sf_*` and `purchase` ones flow to BigQuery automatically — no additional setup needed.

```sql
-- Daily counts of SF-originated events
SELECT event_name, event_date, COUNT(*) AS cnt
FROM `<gcp-project>.analytics_YOUR_GA4_PROPERTY_ID.events_*`
WHERE event_name IN ('sf_calendly_booked','sf_appointment_scheduled','sf_contract_signed','purchase')
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY))
GROUP BY event_name, event_date
ORDER BY event_date DESC, cnt DESC
```

```sql
-- Lifetime ROAS by source (joining purchase events to traffic sources via user_pseudo_id)
WITH purchases AS (
  SELECT user_pseudo_id, event_timestamp,
         (SELECT value.double_value FROM UNNEST(event_params) WHERE key='value') AS revenue
  FROM `<gcp-project>.analytics_YOUR_GA4_PROPERTY_ID.events_*`
  WHERE event_name = 'purchase'
),
sessions AS (
  SELECT user_pseudo_id, traffic_source.source, traffic_source.medium
  FROM `<gcp-project>.analytics_YOUR_GA4_PROPERTY_ID.events_*`
  WHERE event_name = 'session_start'
)
SELECT s.source, s.medium, SUM(p.revenue) AS revenue, COUNT(*) AS purchases
FROM purchases p JOIN sessions s USING(user_pseudo_id)
GROUP BY s.source, s.medium
ORDER BY revenue DESC
```

## End-of-funnel verification (next 24-72h after activation)

```sql
-- SF queue: GA4 should be uploading at near-100% rate
SELECT GA4_Status__c, COUNT(Id) AS cnt
FROM Google_Ads_Conversion_Queue__c
WHERE CreatedDate = LAST_N_DAYS:2
GROUP BY GA4_Status__c
-- Expected: all/most rows Uploaded, zero/few Failed
```

```python
# GA4 Realtime — confirm events still flowing
cd ~/marketing-cli && source .venv/bin/activate
python3 -c "
import yaml
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import RunRealtimeReportRequest, Dimension, Metric, FilterExpression, Filter

cfg = yaml.safe_load((Path.home()/'marketing-cli/google-ads.yaml').read_text())
creds = Credentials(token=None, refresh_token=cfg['refresh_token'],
                    client_id=cfg['client_id'], client_secret=cfg['client_secret'],
                    token_uri='https://oauth2.googleapis.com/token')
data = BetaAnalyticsDataClient(credentials=creds)
req = RunRealtimeReportRequest(
    property=f'properties/{cfg[\"ga4_property_id\"]}',
    dimensions=[Dimension(name='eventName')],
    metrics=[Metric(name='eventCount')],
    dimension_filter=FilterExpression(filter=Filter(
        field_name='eventName',
        string_filter=Filter.StringFilter(value='sf_', match_type=Filter.StringFilter.MatchType.BEGINS_WITH))))
resp = data.run_realtime_report(req)
for r in resp.rows:
    print(f'{r.dimension_values[0].value}: {r.metric_values[0].value}')
"
```

## Pre-existing gotchas

- **`RemoteSiteSetting` required** even when using direct HTTP callout (no Named Credential). SF's allowed-list is enforced for `Http().send()` regardless of credential pattern.
- **GA4 MP returns 204 (not 200)** on success. Apex must accept both.
- **GTM workspace ID changes after each publish** — don't hardcode it in scripts. Look up by `name = 'Default Workspace'` dynamically.
- **Built-in GTM triggers** like "All Pages" aren't reliably returned by the list API for new containers. Either create a custom pageview trigger with no filters, or reference the built-in trigger ID `2147479553` directly.
- **`GA4_Last_Error__c` security gap**: when MP returns an error, the failed request URL (including `api_secret`) gets stored in this field. Low priority since the field is FLS-restricted to Dustin only, but the api_secret should be truncated from error messages.

## Source files

- Apex: `force-app/main/default/classes/GoogleAnalyticsMp*.cls`
- New MDT object: `force-app/main/default/objects/GA4_Config__mdt/`
- Queue fields: `force-app/main/default/objects/Google_Ads_Conversion_Queue__c/fields/GA4_*.field-meta.xml`
- Custom metadata record: `force-app/main/default/customMetadata/GA4_Config.Default.md-meta.xml`
- RemoteSiteSetting: `force-app/main/default/remoteSiteSettings/Google_Analytics_MP.remoteSite-meta.xml`
- Lead/Opp/Tx GA4_Client_Id__c fields: respective `objects/{Lead,Opportunity,Left_Main__Transactions__c}/fields/GA4_Client_Id__c.field-meta.xml`
- GTM tag deploy script: `~/marketing-cli/scripts/apply_gtm_ga4_cid_capture.py`
- Plan: `~/.claude/plans/expressive-splashing-cookie.md`
- Memory: `~/.claude/projects/-Users-dustinsinger-leadConvertWrapper/memory/project_ga4_measurement_protocol.md`

All SF metadata in worktree: `~/leadConvertWrapper/.claude/worktrees/adoring-bardeen-e5615b/`.

## Next sessions

1. **Re-tune Calendly Booked value $3,000 → $1,950** via Google Ads API (Dustin confirmed 65% Calendly→Appointment conversion rate after initial tune).
2. **Day-14 (2026-05-30) bid strategy switch** — campaign-level move to Maximize Conversion Value on `SF - Appointment Scheduled`.
3. **Meta CAPI Phase 3** — same architecture, third pipeline on same queue (FB_* columns). Resolves Meta phone-hashing policy violation while shipping. ~5 hours work — see plan file.
