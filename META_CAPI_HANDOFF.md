# Meta Conversions API (CAPI) Fan-Out — LIVE

**Status:** 🟢 Activated 2026-05-16. Third pipeline alongside Google Ads OCI + GA4 MP, all sharing the SF `Google_Ads_Conversion_Queue__c` table.

## Why this exists

Three reasons:
1. **Resolve the Meta phone-hashing policy violation** (email from Meta 2026-05-16). CAPI hashes email + phone server-side via SHA-256 before send; never leaves SF unhashed.
2. **Bring Meta Smart Bidding the same outcome signals** we just shipped for Google Ads OCI. Currently your Meta campaigns optimize on Pixel form-fills (tire-kicker noise). After CAPI: Schedule (appointment booked), `sf_appointment_scheduled` (real DBH appointment), `sf_contract_signed` (contract), Purchase (deal closed). Same ~1.5x lift potential as Google Ads OCI.
3. **Lookalike Audiences off real outcomes** — instead of seeding LALs from form-fillers, seed from "closed-won" deals. Meta audit Tier 2 #18 flagged this directly.

## Architecture

```
SF queue row (single source of truth)
  ├─→ Status__c                → GoogleAdsOciQueueable    → Google Ads OCI
  ├─→ GA4_Status__c            → GoogleAnalyticsMpQueueable → GA4 MP → BigQuery
  └─→ FB_Status__c (NEW)       → MetaCapiQueueable        → graph.facebook.com/v23.0/{pixel}/events
        ↑ user_data: SHA-256(email), SHA-256(phone), fbc (computed from FBCLID + ts), fbp
        ↑ event_name: from Google_Ads_Conversion_Action__mdt.FB_Event_Name__c
```

3 independent pipelines on the same queue table, each with their own status column. A row marked `Skipped_No_ClickId` for Ads OCI can still be `Uploaded` for GA4 + Meta CAPI. That's the design.

## Event mapping

| SF stage | FB event | Meta standard? | DBH meaning |
|---|---|---|---|
| Lead INSERT (NEW: 5th stage) | `Lead` | ✅ standard | Form submit (Carrot + VN). Replaces the Pixel Lead signal with hashed PII via CAPI. |
| SF_Calendly_Booked | `Schedule` | ✅ standard | Phone consult booked (Calendly cookie flip on Lead) |
| SF_Appointment_Scheduled | `sf_appointment_scheduled` | custom | Real in-person/property appointment (Opp INSERT) |
| SF_Contract_Signed | `sf_contract_signed` | custom | Tx.Projected_Profit__c first non-null |
| SF_Deal_Closed | **`Purchase`** | ✅ standard ecommerce | Tx.Dispo_Status__c → Closed/Won. Lights up Meta Purchase reports. |

The 3 CRM events (Schedule, sf_appointment_scheduled, sf_contract_signed) get value + currency from queue's Conversion_Value__c. Purchase gets transaction_id + value + currency + content_ids per Meta ecommerce spec.

## Conversion values (same as Google Ads OCI defaults)

Apex sends per-record values when available (Projected_Profit__c / Actual_Profit__c). The conv action MDT defaults provide fallbacks. See `OCI_ACTIVATED.md § Conversion value math` for the full DBH funnel economics.

## User-data match keys

Sent in priority order per Meta's spec:
1. **em** = SHA-256(lowercase(trim(Lead.Email))) — primary match key
2. **ph** = SHA-256(numeric-only(Lead.Phone || Lead.MobilePhone)) — strip all non-digits before hash
3. **fbc** = `fb.1.{event_time_ms}.{FBCLID}` — composed from Lead.FBCLID__c + the conversion timestamp per Meta's spec
4. **fbp** = Lead.FB_FBP__c — captured from `_fbp` cookie via GTM v61

All hashing happens server-side in Apex (`Crypto.generateDigest('SHA-256', Blob.valueOf(s))` → hex encoded). Plaintext PII never touches the queue table.

## Live components

**Apex** (in `~/leadConvertWrapper/.claude/worktrees/adoring-bardeen-e5615b/force-app/main/default/classes/`):
- `MetaCapiQueueable.cls` — handles single batch, builds CAPI body, hashes PII, POSTs
- `MetaCapiSchedulable.cls` — polls FB_Status='Pending', batches 100/Queueable
- `_Test.cls` for both; 10/10 tests passing

**Queue object fields** (6 new + 5 GA4_* from Phase 2 + 10 original = 21 fields total now):
- `FB_Status__c` Picklist (Pending default / Uploaded / Failed / Skipped)
- `FB_Last_Error__c` LongTextArea
- `FB_Uploaded_At__c` DateTime
- `FB_Attempts__c` Number
- `FBCLID__c` Text 255
- `FB_FBP__c` Text 100

**Lead / Opportunity / Left_Main__Transactions__c** — each got `FBCLID__c` + `FB_FBP__c` (Text). Propagation:
- Lead → Opp: via Lead Convert mapping (USER STILL TO DO — Setup → Object Manager → Lead → Map Lead Fields → map both fields)
- Opp → Tx: via `Dustin_Create_New_Transaction` flow (both wholesale + sell-side paths) — already shipped

**`Google_Ads_Conversion_Action__mdt`** new field `FB_Event_Name__c`. All 4 existing records + 1 new record (`SF_Lead_Form_Submit`) populated.

**`Meta_Config__mdt`** with `Default` record:
- Pixel_Id__c = `365910274042753`
- Access_Token__c = (loaded from `~/marketing-cli/google-ads.yaml` fb_access_token)
- API_Version__c = `v23.0`
- Active__c = `true`
- Test_Event_Code__c = `TEST95135` (sends events to Test Events tab; clear to send live)

**`RemoteSiteSetting Meta_Graph_API`** → `https://graph.facebook.com` (required for direct HTTP callout — Meta CAPI uses URL-param auth, not header auth, so no Named Credential).

**6 stamping flows** active:
- `Dustin_OCI_Stamp_Calendly_Booked` — Lead update, Calendly cookie flip
- `Dustin_OCI_Stamp_Appointment_Scheduled` — Opp INSERT
- `Dustin_OCI_Stamp_Contract_Signed` — Tx, Projected_Profit__c non-null
- `Dustin_OCI_Stamp_Contract_Signed_OnInsert` — Tx INSERT edge
- `Dustin_OCI_Stamp_Deal_Closed` — Tx, Dispo_Status__c → Closed/Won
- **NEW** `Dustin_OCI_Stamp_Lead_Form_Submit` — Lead INSERT (Meta-only: stamps row with Status=Skipped_No_ClickId + GA4_Status=Skipped + FB_Status=Pending)

**Cron**: 4 jobs `Meta CAPI Uploader :0/15/30/45`. Drains queue every 15 min.

**Permset** `Google_Ads_OCI_User` covers MetaCapiQueueable + MetaCapiSchedulable. Same permset that covers GoogleAds + GA4 MP classes.

## GTM tags (v61 live)

- `Facebook Pixel ID 365910274042753` (id 24) — UNCHANGED. Still fires PageView on All Pages. NO Lead event was firing from this tag (we verified — it's PageView-only). Automatic Advanced Matching (AAM) handles auto-detected PII; Meta auto-hashes via the Pixel JS library.
- `FB - Capture _fbp cookie into form field` (id 69, NEW v61) — Custom HTML on All Pages. Reads `_fbp` cookie, populates `input[name="fb_fbp"]` or `input.fb-fbp-field` form fields.
- `GA4 - Capture client_id into form field` (id 68, from v60) — unchanged.

## Pixel ↔ CAPI dedup decision (2026-05-16)

We considered building a UUID-based event_id dedup so Pixel Lead + CAPI Lead would dedup as one event. **Decided against** because:
1. The Pixel base tag in GTM is PageView-only — no Lead event to dedup against
2. AAM (Meta's auto-event-detection) may surface form-submits as auto-events, but those are uncontrolled and dedup with CAPI via Meta's own internal matching
3. Building the UUID system would be 2-3 hours for marginal gain

Current behavior: CAPI sends Lead with hashed em/ph/fbp/fbc. If Meta's AAM also auto-fires a Lead event (likely yes), Meta dedups them via event_name + same-event-time + matching user_data. Some double-count risk persists but it's bounded.

## Carrot + Make work (USER STILL TO DO)

Mirror the gclid + ga4_client_id pattern. For each form (1, 4, 6, 9):

1. Add hidden field `fbclid`:
   - Label: `FBCLID`
   - ✅ Allow field to be populated dynamically → Parameter Name: `fbclid`
   - Save

2. Add hidden field `fb_fbp`:
   - Label: `FB Browser ID`
   - Advanced → CSS Class: `fb-fbp-field` (GTM tag finds it by class)
   - Save

3. Make scenario 3763484 — add 2 new mappings in modules #8/9 (SF Lead create/update):
   - `fBCLID__c ← {{1.fbclid}}`
   - `fB_FBP__c ← {{1.fb_fbp}}`

4. SF Lead Convert mapping (Setup → Object Manager → Lead → Map Lead Fields):
   - `Lead.FBCLID__c → Opportunity.FBCLID__c`
   - `Lead.FB_FBP__c → Opportunity.FB_FBP__c`

Until #1-4 are done: CAPI still works on existing leads, but match quality is lower (only email + phone, no fbc/fbp). Meta's match rate drops from ~80% (with all 4 keys) to ~60% (with em + ph only). Still effective.

## Verification

### Live smoke test from 2026-05-16
```
Queue row a5CQO0000002A9l2AE inserted → MetaCapiQueueable executed →
  FB_Status = Uploaded in <5 sec → Meta CAPI accepted (200 OK)
```
Event lands in Meta Events Manager → Pixel 365910274042753 → Test Events tab (because Test_Event_Code is set).

### Ongoing
```sql
-- Queue health by pipeline
SELECT Status__c, GA4_Status__c, FB_Status__c, COUNT(Id)
FROM Google_Ads_Conversion_Queue__c
WHERE CreatedDate = LAST_N_DAYS:2
GROUP BY Status__c, GA4_Status__c, FB_Status__c

-- Meta CAPI uploads only
SELECT COUNT(Id), FB_Status__c
FROM Google_Ads_Conversion_Queue__c
WHERE CreatedDate = LAST_N_DAYS:7
GROUP BY FB_Status__c
```

### Meta Events Manager
1. Open Events Manager → Pixel 365910274042753
2. **Test Events tab** — events with `test_event_code=TEST95135` appear here
3. Look for `Schedule`, `sf_appointment_scheduled`, `sf_contract_signed`, `Purchase`, `Lead` events from Server source
4. To send live events instead of Test: clear `Meta_Config.Default.Test_Event_Code__c` via metadata deploy

## Going live (post-validation)

After ~24-48h of Test Events validation, switch CAPI to send live events:

```bash
# Clear test_event_code so events go to production
sed -i '' 's|<value xsi:type="xsd:string">TEST95135</value>|<value xsi:nil="true"/>|' \
  ~/leadConvertWrapper/.claude/worktrees/adoring-bardeen-e5615b/force-app/main/default/customMetadata/Meta_Config.Default.md-meta.xml
sf project deploy start --source-dir force-app/main/default/customMetadata/Meta_Config.Default.md-meta.xml --target-org mydevorg
```

Then check production events under Events Manager → Overview tab.

## Source files

- Apex: `force-app/main/default/classes/MetaCapi*.cls`
- Queue + Lead/Opp/Tx FB_* fields: respective `objects/.../fields/FB*.field-meta.xml`
- Meta_Config__mdt + Default record: `force-app/main/default/{objects/Meta_Config__mdt,customMetadata/Meta_Config.Default.md-meta.xml}`
- Stamping flow: `force-app/main/default/flows/Dustin_OCI_Stamp_Lead_Form_Submit.flow-meta.xml`
- GTM tag deploy: `~/marketing-cli/scripts/apply_gtm_fbp_capture.py`
- Plan reference: `~/.claude/plans/expressive-splashing-cookie.md`

## Next session candidates

1. **Re-tune CAPI conversion values after 30 days of data** — same logic as the OCI tune.
2. **Implement strict Pixel↔CAPI Lead dedup** if Meta double-count becomes a real problem. UUID-cookie approach. ~2-3 hr.
3. **Capture `client_ip_address` + `client_user_agent`** via Make scenario → SF → CAPI user_data. Bumps match rate further.
4. **Custom Event registration in Meta** — `sf_appointment_scheduled` + `sf_contract_signed` should be registered as Custom Events in Meta Events Manager so they can be selected as conversion optimization goals.
5. **Switch Meta campaign bid strategy** from Pixel `Lead` → `Schedule` (or higher-funnel CAPI event) once 30+ days of data accumulates. Same play as the Google Ads day-30 switch.
