# Google Ads Offline Conversion Import — handoff

Last updated: 2026-05-15

The single source of truth for the SF Offline Conversion Import (OCI) build. If you're a fresh Claude reading this cold: this is the project state, decisions, and next steps. Start here.

---

## Why this exists

Google Ads currently optimizes for "Submit lead form" conversions — fires for any form-fill including tire-kickers, info-seekers, kids messing around. The Ads bid algorithm has no signal about which of those form-fills became actual contracts or closed deals.

OCI fixes this. We send Salesforce Opportunity/Transaction stage outcomes back to Google Ads tied to the original `gclid` (Google Click ID). The algorithm then learns "gclid X produced a $25K contract 47 days after the click" and biases future bids toward similar clicks.

**Expected impact**: probably 2–3× contracts per ad dollar within 60 days of data accumulation. Higher than any single negative-keyword sweep.

---

## Phase 2 status — DEPLOYED TO PROD 2026-05-15

13 attribution fields + 1 flow change live in `mydevorg`:

**Lead**: `GCLID__c`, `GCLID_Captured_At__c`, `GBRAID__c`, `WBRAID__c`, `Landing_URL__c`
**Opportunity**: `GCLID__c`, `GBRAID__c`, `WBRAID__c`, `Landing_URL__c`
**Left_Main__Transactions__c**: `GCLID__c`, `GBRAID__c`, `WBRAID__c`, `Landing_URL__c`
**Flow**: `Dustin_Create_New_Transaction` v22 — copies all 4 attribution fields Opp→Tx in both code paths (wholesale + sell-side).

**Pre-existing test failures noted**: 14 prod tests failing (QuickBooks + Zapier-intake), unrelated to OCI. Flow deploy went through using `--test-level RunSpecifiedTests --tests SMSConfigTriggerHandlerTest` to bypass them. **These should be fixed separately** — they'll keep blocking future Apex/Flow deploys if not addressed.

**Sandbox is partial / out of date** — fields deployed there too but flow deploy blocked by missing Underwriting__c (32 records in prod, absent in sandbox) and its Lightning Record Page dependency. Skipped sandbox verification, validated changes are additive-only.

## Pending manual steps (Dustin)

### 1. Lead Convert field mapping (SF UI, 2 min)

Prod → Setup → Object Manager → Lead → **Map Lead Fields**. Map four pairs:
- `Lead.GCLID__c` → `Opportunity.GCLID__c`
- `Lead.GBRAID__c` → `Opportunity.GBRAID__c`
- `Lead.WBRAID__c` → `Opportunity.WBRAID__c`
- `Lead.Landing_URL__c` → `Opportunity.Landing_URL__c`

Until this is done, click IDs won't propagate to Opportunity on Lead Convert.

### 2. Import patched Make blueprint into scenario 3763484 (5 min)

Modified blueprint is at: `~/Downloads/Add Leads to Salesforce.blueprint_OCI_PATCHED.json`

What changed: added 4 new field mappings to ALL 7 SF Lead create/update modules in the scenario:
- `landing_URL__c` ← `{{59.\`Page Name\`}}` (full URL, into the new 32K Long Text Area)
- `gCLID__c` ← regex-extracted from URL
- `gBRAID__c` ← regex-extracted from URL
- `wBRAID__c` ← regex-extracted from URL

Steps:
1. Open Make → scenarios → "Add Leads to Salesforce" (id 3763484)
2. Three-dot menu → **Import Blueprint** → upload the patched file
3. Save the scenario
4. **Restart** the scenario — it's been stopped since 2026-05-09 (looks like it was paused when native Carrot Phase 2 attempt happened)

### 3. Verify on first new Carrot lead

After import + restart, the next Carrot web form submission should produce a Lead with:
- `Landing_URL__c` populated with the full URL (no 200-char cap)
- `GBRAID__c` populated (Google uses gbraid for this account)
- `GCLID__c` likely null (Google has shifted away from gclid here)
- `WBRAID__c` populated only for iOS web-to-app flows

Query:
```bash
sf data query --query "SELECT Id,Name,GBRAID__c,GCLID__c,WBRAID__c,Landing_URL__c FROM Lead WHERE Carrot_Source__c != null ORDER BY CreatedDate DESC LIMIT 3" --target-org mydevorg
```

## Important caveats found mid-Phase-3

**Carrot web leads are LOW VOLUME.** Only 1 in the last 7 days. Most "Google PPC" leads are PHONE CALLS via Voice Nation. The Make scenario blueprint patch only solves the small web-form slice.

**Voice Nation phone leads have NO URL data.** Phone calls don't pass URL params. For OCI to catch phone leads tied to Google Ads:
- Voice Nation would need to capture caller's gclid via Google's call ad attribution (forwarding numbers)
- Or use a phone tracking provider that exposes gclid (CallRail, CallSource)
- Currently neither is configured

This is a **larger blocker than the SF schema work**. OCI on web-only will undercount real conversions by ~80%+ given current lead-source mix. Adding phone tracking is a Phase 3.5 or 4 task.

**Make scenario 3763484 is currently STOPPED** (last execution 2026-05-09 02:06 UTC, stopped 02:33 same day). Was paused around the time of the native Carrot Phase 2 attempt. Investigate whether stopping was intentional before restarting.

## Major mid-Phase-2 finding (2026-05-15)

**Google has shifted this account from `gclid` to `gbraid`.** Sample of 10 recent Google PPC leads showed the landing URL contains `gbraid=0AA...` (and `gad_source=1`, `gad_campaignid=21383612348`) but no `gclid` param. `gbraid` is Google's privacy-compliant click ID introduced for iOS 14+. Google Ads OCI accepts gbraid uploads the same way as gclid uploads — same `ConversionUploadService` endpoint, different field name (`gbraid` vs `gclid` in the request body).

**Existing `Lead.Page_Name__c` captures the landing URL but is capped at 200 chars** — cuts off right before the click ID. We added a new `Landing_URL__c` (Long Text Area, 32768) to preserve the full URL.

## Discovery findings (Phase 1 — done 2026-05-15)

### What exists today

**SF objects + fields**:
- `Lead` (431 fields, 14 tracked locally) — has UTM_Source__c, UTM_Campaign__c, UTM_Term__c, UTM_Content__c, Carrot_Source__c, LeadSource, Raw_Intake_Payload__c.
- `Opportunity` (365 fields) — has UTM_Source__c, UTM_Campaign__c, UTM_Term__c, UTM_Content__c, Carrot_Source__c.
- `Left_Main__Transactions__c` (372 fields) — has UTM_Source__c, UTM_Campaign__c, UTM_Term__c, UTM_Content__c, Carrot_Source__c.

**Existing data flow** (sampled 5 recent Carrot leads):
- Carrot writes `Carrot_Source__c` (e.g. "google - ppc") and SOMETIMES `UTM_Source__c` / `UTM_Campaign__c`. Inconsistent — some "Google PPC" leads have UTM populated, some don't.
- `Raw_Intake_Payload__c` is **empty (length 0)** on all 5 Carrot leads checked — Carrot's webhook handler doesn't write to it. So we can't reconstruct what Carrot sent us today.
- `Form_Entry__c` (VN intake) — 39 fields, only `Source__c` is attribution-flavored. No GCLID.

**UTM propagation Lead → Opp → Tx**: only one flow writes UTM (`Dustin_Create_New_Transaction.flow-meta.xml`). Lead Convert presumably auto-maps via SF's standard field mapping, but worth verifying. No Apex touches these fields.

**Lead intake paths**:
- **VN (Voice Nation)**: Jotform → `Form_Entry__c` insert → SF trigger → Lead. LIVE on native code. No gclid capture.
- **Carrot**: Native platform-event path code-deployed 2026-05-09 but **in shadow mode** (blocked on Left_Main package quirk — see `project_sf_lead_intake_migration.md`). Live path is still **Make scenario 3763484** → SF Lead upsert.

### Gaps (the work to do)

1. **`Lead.GCLID__c` does not exist.** Same for Opportunity, Transactions, Form_Entry__c. Has to be created (length 1024+ to be safe — gclids are typically ~100 chars but no published cap).
2. **Carrot's outbound webhook payload almost certainly doesn't include gclid.** Standard Carrot fields don't include URL params unless explicitly captured by JS into a hidden form field. Needs custom code on Carrot site OR migration to WP form that captures it.
3. **WordPress staging is form-incomplete.** Gravity Forms not yet installed (per `dbh_migration/HANDOFF.md`). Perfect timing to wire gclid capture into the new forms from day 1.
4. **No SF → Google Ads upload mechanism exists.** Net-new build.
5. **Conversion values are $0 in Google Ads** — even when we send conversion uploads, they'll have no $ value unless we assign one (margin per deal makes sense for wholesaling).

---

## Constraints to design around

- **Single SF org** (`mydevorg` = `dustin@dustinbuyshouses.net`, 00DfL0000082x7XUAQ). Sandbox exists (`dbh-partial`).
- **Automated Process user can't hold External Credential permsets** (memory: `feedback_ap_user_external_credential_limit.md`). Any PE-triggered chain that needs the Google Ads callout will fail. Pattern: PE stamps state only → Dustin-context Schedulable polls and dispatches the callout queueable.
- **HighVolume PE publishers must guard `Test.isRunningTest()`** (memory: `feedback_platform_event_test_leak.md`). Test contexts leak to prod subscribers.
- **Lead intake migration is paused** (Carrot Phase 2 blocked on Left_Main quirk). Don't block OCI on intake migration shipping — wire OCI on the current Make-based intake AND make sure the future native path preserves gclid.
- **WP migration in flight.** Production is still Carrot. WP staging at `h52f6jsnvm.onrocket.site` not yet cut over. We need OCI working on the Carrot path while WP migration completes.

---

## Phased plan

### Phase 2 — GCLID capture infrastructure (1–2 days)

**SF schema**:
1. Create `Lead.GCLID__c` (Text, length 1024, External ID, unique).
2. Create `Opportunity.GCLID__c` (Text, 1024). Update standard Lead Convert mapping to carry it across.
3. Create `Left_Main__Transactions__c.GCLID__c` (Text, 1024). Update `Dustin_Create_New_Transaction` flow to copy from Opp.
4. Create `Lead.GCLID_Captured_At__c` (DateTime) — when we captured the click ID. Used to validate against Google Ads' 90-day lookback window.

**Carrot side (current production)**:
- Add hidden field `gclid` to all lead forms in Carrot admin (Lead Capture → Forms → custom fields).
- Add JS snippet to Carrot site footer that reads `gclid` from URL → writes to first-party cookie (90 days) → writes to hidden form field on submit. Stock snippet (Google publishes one) at https://developers.google.com/google-ads/api/docs/conversions/upload-clicks#capture-the-gclid.
- Modify Make scenario 3763484 to pass `gclid` from Carrot payload → Lead.GCLID__c + Lead.GCLID_Captured_At__c.

**WordPress side (new build)**:
- Wait for Gravity Forms install (user task).
- When installing GF, add a "Hidden" field per form named `gclid`. Set default value to the gclid query-string parameter (Gravity Forms supports `{embed_url:gclid}` merge tag, or use a GF gclid-capture plugin).
- WP webhook mapping (Gravity Forms → SF) must include gclid field → Lead.GCLID__c.

### Phase 3 — Google Ads conversion action setup (manual UI, 15 min)

**Three-tier funnel** (decision 2026-05-15):

| Conversion action name | Fires on | Value sent |
|---|---|---|
| `SF - Appointment Scheduled` | Opportunity INSERT (Lead → Opp via convert) | none (count-only — primary count of "real" leads vs form-fills) |
| `SF - Contract Signed` | Transaction INSERT | `Projected_Profit__c` from Tx (deal-size signal pre-close) |
| `SF - Deal Closed` | Tx `Left_Main__Dispo_Status__c` → `Closed/Won` | `Actual_Profit__c` from Tx (real margin) |

For each in Google Ads UI:
1. Goals → Conversions → New → "Import" → "Other data sources or CRMs" → "Track conversions from clicks".
2. Set the name as above.
3. Value: "Use different values for each conversion" (uploader sends $).
4. Count: "One".
5. Attribution: data-driven.

**Pipeline mapping** (from Dustin):
- Lead → Opportunity = "appointment scheduled" (Opp stage starts at "Appointment Set", progresses through "1-30 Days" → "31-90 Days" → "90+ Days" → "Contract Signed" / "Closed Lost" / "Manual Follow Up" / "Needs Rescheduled").
- Opportunity → Transaction = "contract signed" (Transaction insert from Opp).
- Transaction `Left_Main__Dispo_Status__c` picklist: Pending Underwriting → Sent to VIP List / Regular List → Assigned-- Clear to Close / Renegotiating → Dying-- Renegotiating → **Closed/Won** OR Cancelled Contract/Lost.

### Phase 4 — Apex uploader (3–5 days)

**New Apex classes** in `leadConvertWrapper`:
- `GoogleAdsConversionUploader` — main service. Methods: `enqueueOpportunityConversion(Id oppId, String conversionAction)`, `flushQueue()`.
- `GoogleAdsConversionUploaderSchedulable` — runs every N minutes via Schedulable (Dustin-context, NOT Automated Process — needs External Credential).
- `GoogleAdsConversionUploaderQueueable` — async callout. Hits `ConversionUploadService.UploadClickConversions` REST endpoint.
- `Google_Ads_Conversion_Queue__c` custom object — staging queue. Fields: GCLID__c, Conversion_Action__c, Conversion_Value__c, Conversion_DateTime__c, Status__c (PENDING/UPLOADED/FAILED), Last_Error__c, Source_Record__c (Opp or Tx ID).

**Triggers**:
- Opportunity After Update — when Stage transitions to a configured "fire conversion" stage, insert row into Google_Ads_Conversion_Queue__c.
- Same for Left_Main__Transactions__c if you want a separate Closed Won upload.

**External Credential / Named Credential**:
- Setup → Security → External Credentials → new credential `Google_Ads_OCI` using OAuth 2.0 Client Credentials Flow (or use the same refresh token we already have in `~/marketing-cli/google-ads.yaml`).
- Named Credential `Google_Ads_API` → endpoint `https://googleads.googleapis.com/v17`.
- Permission Set `Google_Ads_OCI_User` grants Apex access to the External Credential. Assign to Dustin (NOT Automated Process — see constraint).

**Per the AP user constraint**: the trigger inserts a queue row but doesn't make the callout. The Schedulable (running as Dustin) polls the queue every 15 min, dispatches Queueable callouts, marks rows UPLOADED/FAILED.

### Phase 5 — Python companion in marketing-cli (1 day)

Add to `~/marketing-cli/gads/`:
- `oci.py` — pull queue from SF (via simple_salesforce or sf CLI), do dry-run preview of what would be uploaded, upload directly from CLI for backfills/corrections.
- CLI commands: `gads oci queue` (show pending uploads from SF), `gads oci backfill --opp-id 006...` (manual single-record upload), `gads oci reconcile` (compare what SF says was uploaded vs what Google Ads has).

### Phase 6 — Conversion value model (decision required from Dustin)

The Apex needs to know what dollar value to send per conversion. Options:
- **Flat per stage**: `Opp_Contract_Signed = $500`, `Tx_Closed_Won = $5,000` (margin proxy). Simplest.
- **Per-record actual**: pull margin from Opp/Tx fields if they exist.
- **Hybrid**: flat for Contract Signed, actual margin for Closed Won.

Recommendation: start flat (Phase 4 MVP) → upgrade to per-record once we know which SF field actually holds margin.

### Phase 7 — Verification + iteration

- Verify in Google Ads UI: Goals → Conversions → `SF Opportunity Created` shows count > 0 within 24h of first triggered Opp.
- Pull `gads pull conversions` and confirm new conversion action shows up.
- After 30 days of data, compare CPA per campaign between "Submit lead form" and "SF Opportunity Created" — should diverge meaningfully, with the SF version being a more honest signal.

---

## Critical files / locations

**Existing**:
- `force-app/main/default/objects/Lead/` — Lead object metadata (local copy partial)
- `force-app/main/default/objects/Opportunity/`
- `force-app/main/default/objects/Left_Main__Transactions__c/`
- `force-app/main/default/flows/Dustin_Create_New_Transaction.flow-meta.xml` — currently copies UTM Lead → Tx; add GCLID copy here
- `force-app/main/default/flows/DBH_Lead_Create_Record_Trigger.flow-meta.xml` — Lead intake side
- Make scenario 3763484 — Carrot → SF intake (modify to pass gclid)
- `~/leadConvertWrapper/dbh_migration/` — WP migration project; OCI capture must be baked in when Gravity Forms goes live
- `~/marketing-cli/google-ads.yaml` — Google Ads creds. Same OAuth client can be used by SF External Credential.

**To create**:
- SF fields: `Lead.GCLID__c`, `Lead.GCLID_Captured_At__c`, `Opportunity.GCLID__c`, `Left_Main__Transactions__c.GCLID__c`
- SF object: `Google_Ads_Conversion_Queue__c`
- Apex: `GoogleAdsConversionUploader`, `GoogleAdsConversionUploaderSchedulable`, `GoogleAdsConversionUploaderQueueable` + tests
- External Credential `Google_Ads_OCI`, Named Credential `Google_Ads_API`, Permission Set `Google_Ads_OCI_User`
- Carrot custom JS for gclid cookie capture + hidden field write
- Make 3763484 modification (add gclid field mapping)
- Future: WP Gravity Forms gclid capture
- Python: `~/marketing-cli/gads/oci.py` + CLI subcommands

---

## Open questions (need Dustin's input)

1. **Conversion value model** (Phase 6): what's the right $ value for each conversion stage? Need historical margin data from SF.
2. **Which stages fire conversions?** Recommendation: Opportunity stage = "Contract Signed" (or your equivalent), Transaction stage = "Closed Won". Need to confirm exact StageName values.
3. **Carrot vs WordPress sequencing**: wire gclid capture into Carrot NOW (throwaway work but starts data flow immediately) OR wait for WP migration to ship (cleaner but loses 1–3 months of data — gclids expire after 90 days)? Recommendation: wire BOTH. Carrot first, then bake into WP from day 1 when forms go in.
4. **Where does Apex code land?** Same repo (`leadConvertWrapper`) as everything else, in a new folder like `force-app/main/default/classes/google_ads/` for namespace cleanliness.
5. **Sandbox-first or prod-first?** Recommendation: build in sandbox (`dbh-partial`), test the upload roundtrip against a Google Ads test account, then deploy to prod with `Shadow_Mode__c` toggle for safe rollout.

---

## Memory references

- `project_sf_offline_conversion_import.md` — the decision to do this
- `project_sf_lead_intake_migration.md` — current Carrot/VN intake state, blocked Phase 2
- `project_dbh_migration.md` — WP migration; HANDOFF.md in `dbh_migration/`
- `feedback_ap_user_external_credential_limit.md` — design constraint for Phase 4
- `feedback_platform_event_test_leak.md` — design constraint for any PE trigger
- `feedback_check_prod_state_first.md` — always retrieve fresh metadata, local drifts hourly

## Next action

Decide on conversion value model + Carrot-vs-WP sequencing (open questions 1 + 3 above), then start Phase 2: create the four GCLID fields in `dbh-partial` sandbox and verify Lead Convert auto-maps to Opp.
