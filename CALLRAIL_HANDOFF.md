# CallRail Hybrid — Session Handoff 2026-05-18

> **Status as of 2026-05-19:** Phase A-E shipped per this doc. Subsequent same-day + next-day work (Step 2 bug fixes, full intake pipeline audit, Meta `test_event_code` clear, `First_Page__c` LongTextArea conversion) documented separately in `~/marketing-cli/HANDOFF_2026-05-19.md`. Branch is now 8 commits ahead of base. Read both docs together for full picture.

Phone-lead attribution via CallRail Dynamic Number Insertion (DNI). Replaces the deferred "Path B" Apex `uploadCallConversions` approach. Closes the phone-attribution gap that was leaving **17 of 18 Google PPC appointments invisible to Smart Bidding**, plus **63 of 90 TV-driven leads mis-attributed** to Google/Organic.

**Branch:** `feat/callrail-form-entry-fields` on `dustins89/dbh-sf`, 8 commits ahead of `chore/full-org-sync-2026-05-10`, pushed.
PR: https://github.com/dustins89/dbh-sf/pull/new/feat/callrail-form-entry-fields

---

## TL;DR

| Component | State | Detail |
|---|---|---|
| CallRail Call Tracking Starter + Advanced Call Routing | 🟢 LIVE | $50/mo base + $15/mo routing add-on ≈ $65-80/mo all-in |
| Visitor Pool with DNI (10 PA numbers) | 🟢 LIVE | Swap targets: `+1-XXX-XXX-XXXX`, `+1-XXX-XXX-XXXX`, `+1-XXX-XXX-XXXX`, `+1-XXX-XXX-XXXX` |
| Call Flow w/ 4 source-conditional Responsive Routing rules | 🟢 LIVE | Google PPC / Organic / TV / Facebook → matching 360sms numbers |
| GTM tag deployed (CallRail swap.js) | 🟢 LIVE | Container `GTM-K7GK4SK` version published; fires on All Pages |
| SF Schema (16 Form_Entry__c fields + 4 Lead fields) | 🟢 LIVE | Lead fields created by Dustin; Form_Entry__c fields deployed via this branch |
| Zapier post-call → Form_Entry__c | 🟢 LIVE | "Upsert" recommended via `CallRail_Call_Id__c` External Id |
| FormEntryProcessor CallRail branch (Phase E) | 🟢 LIVE | Commit `21c37b4`. Deploy `0AfQO000001fUnx0AE`. 18/18 tests passing. |
| End-to-end smoke test verified | 🟢 PASS | FE-0000065 → Terri Sabo Lead enriched, no Re_Engagement Slack |

---

## Architecture

```
Visitor on dustinbuyshouses.net (any page)
  │  CallRail swap.js runs (via GTM-K7GK4SK) — replaces visible phone
  │  numbers with a session-bound CallRail tracking number
  ▼
Visitor taps swapped number → CallRail's switch
  │  - Records call (caller_id, start_time, recording)
  │  - Captures session attribution at DNI time: GCLID, FBCLID, UTM_*, IP,
  │    User Agent, landing page, referrer, source category, first-touch +
  │    last-touch milestones
  │  - Responsive Routing evaluates 4 source-conditional rules
  │
  ▼ forwards call to one of 4 destination 360sms numbers
360sms receives call (parallel webhook flow)
  │  - Routes call to agent / Voice Nation / IVR
  │  - Fires its own webhook (T+5s) → creates SF Lead (existing pipeline)
  │  - Lead.LeadSource = inferred from which 360sms number was dialed
  │  - Lead has Phone + LeadSource but NO GCLID/IP/UA (360sms doesn't capture)
  ▼
[call concludes]
  │
  ▼
CallRail post-call webhook (T+call_duration+10s) → Zapier
  │  Upsert Form_Entry__c by CallRail_Call_Id__c (External Id, Unique)
  ▼
SF FormEntryTrigger → FormEntryProcessor.processNew
  │
  ├── Detect CallRail intake: Form_Id__c='CALLRAIL' OR CallRail_Call_Id__c populated
  │
  ├── processCallRailEntry()
  │     1. Spam gate (Spam_Flag__c=true → exit)
  │     2. Idempotency (Lead.CallRail_Call_Id__c already set to this call_id → exit)
  │     3. Phone match (Lead WHERE Phone OR MobilePhone matches E.164-normalized
  │        variants. No CreatedDate filter — match any existing record.)
  │     4. NO match → 'callrail_orphan_no_match'. NEVER CREATE a Lead.
  │     5. MATCH → blank-fill standard attribution (only write null fields):
  │        GCLID, FBCLID, FB_FBP, GA4_Client_Id, IP_Address, UTM_*, Landing_URL
  │     6. ALWAYS overwrite per-call fields:
  │        CallRail_Call_Id__c, Call_Start_Time__c, Call_Duration_Seconds__c,
  │        Call_Recording_URL__c
  │     7. User_Agent sanity filter: reject parsed browser names (e.g. "Safari"),
  │        require Mozilla/Opera prefix OR len > 30 chars
  │
  └── SKIPS the existing LeadIntakeRestResource.processIntake call
        → no Re_Engagement_Event__e platform event published
        → no "Filled Out Another Webform" Slack on CallRail-only paths
```

---

## Master Audit findings closed

From `MASTER_AUDIT_2026-05-16.md`:
- Phone-attribution gap (17 of 18 Google PPC appts invisible to Smart Bidding) — addressed for any phone caller with a prior web session
- TV-halo measurement gap (63 of 90 self-reported-TV leads mis-attributed) — addressed; `Original_Source__c` on Form_Entry__c now captures first-touch
- Meta CAPI EMQ on phone leads — addressed (IP + raw UA when available; FB_FBP cookie captured)

From master audit Phase 7 plan: this is the CallRail/DNI implementation that was deferred. Now LIVE.

---

## 4 conditional routing rules

CallRail Call Flow → Responsive Routing (Advanced Call Routing add-on enabled):

| Branch | Criteria | Forward To | 360sms Channel |
|---|---|---|---|
| 1 — Google PPC | Source = "PPC Search" OR "Google Paid" OR Landing contains `cash-for-house` | `412-754-7801` | Google PPC |
| 2 — Organic | Source = "Organic Search" / "Google Organic" / "Bing Organic" / "Yahoo Organic" | `412-688-6311` | Organic |
| 3 — TV | Landing contains `as-seen-on-tv` OR Referrer contains `selltodustin` | `412-615-0000` | TV |
| 4 — Facebook | Referrer contains `facebook` OR Landing contains `fbclid` | `412-455-8080` | Facebook |
| Default | (anything else) | `412-688-6311` | Organic (safe fallback) |

---

## SF schema shipped this session

**16 new fields on `Form_Entry__c`:**
- CallRail_Call_Id__c (Text 50, External Id, Unique) — idempotency key
- CallRail_Tracking_Number__c (Phone) — which DNI number was dialed
- CallRail_Source__c (Text 50) — CallRail's last-touch source label
- CallRail_Person_Id__c (Text 50) — stable identifier for repeat-caller detection
- Call_Start_Time__c (DateTime)
- Call_Duration_Seconds__c (Number 6,0)
- Call_Recording_URL__c (URL 255)
- Caller_Phone__c (Phone) — raw caller_id from CallRail
- First_Page__c (URL 255)
- Forwarded_To__c (Phone) — which 360sms number CallRail routed to (audit trail)
- Session_UUID__c (Text 50) — CallRail's session identifier
- Caller_City__c (Text 100) — caller's carrier-lookup city
- Caller_State__c (Text 50) — caller's carrier-lookup state
- Original_Source__c (Text 50) — first-touch source (Milestones First Touch Source)
- Original_Acquired_At__c (DateTime) — first-touch event date
- Spam_Flag__c (Checkbox) — gate to skip Lead enrichment for spam calls

**4 new fields on `Lead`** (Dustin created manually):
- CallRail_Call_Id__c
- Call_Start_Time__c
- Call_Duration_Seconds__c
- Call_Recording_URL__c

Form_Entry_Manage permset extended (52 → 68 fieldPermissions blocks).

---

## End-to-end smoke test result (2026-05-18 21:01 UTC)

Test row FE-0000065 against existing Lead `00QQO00001GAp5x2AD` (Geraldine "Terri" Sabo):

| Field | Before | After Phase E | Expected | Result |
|---|---|---|---|---|
| Lead.GCLID__c | `CjwKCA...` | `CjwKCA...` (preserved) | preserve | ✅ |
| Lead.IP_Address__c | `73.174.16.240` | `73.174.16.240` (preserved) | preserve | ✅ |
| Lead.User_Agent__c | `/user agent` | `/user agent` (preserved; CallRail's "Safari" rejected) | preserve | ✅ |
| Lead.UTM_Source__c | `google` | `google` (preserved) | preserve | ✅ |
| Lead.CallRail_Call_Id__c | null | `CAL019e3c9c7f...` | set | ✅ |
| Lead.Call_Recording_URL__c | null | working URL | set | ✅ |
| Lead.Call_Duration_Seconds__c | null | 353 | set | ✅ |
| Lead.Call_Start_Time__c | null | 2026-05-18T19:42:29 | set | ✅ |
| Form_Entry__c.Processing_Result__c | — | `callrail_enriched` | new path | ✅ |
| Slack notification fired | — | None | None (Zapier-only test, no real call) | ✅ |

---

## Apex test coverage (FormEntryProcessor_Test, 7 new methods)

- `callRail_orphanNoMatch_stampsOrphan_doesNotCreateLead`
- `callRail_matchedLead_blankFillsAttribution`
- `callRail_preservesExistingAttribution_doesNotOverwrite`
- `callRail_spamFlag_skipsEnrichment`
- `callRail_idempotencyGuard_skipsWhenLeadAlreadyHasCallId`
- `callRail_rejectsParsedBrowserAsUserAgent`
- `callRail_detectedViaCallRailCallId_whenFormIdMissing`

18/18 total passing in mydevorg.

---

## Zapier configuration

**Action:** Salesforce → Upsert Record on `Form_Entry__c` using `CallRail_Call_Id__c` as External Id

**Constants (literal text, not from payload):**
- `Form Id` = `CALLRAIL`
- `Source` = `callrail - inbound`

**Critical field mappings:**

| CallRail payload | SF field |
|---|---|
| Resource Id | CallRail_Call_Id__c |
| Trackingnum | CallRail_Tracking_Number__c |
| Milestones Last Touch Source | CallRail_Source__c |
| Milestones First Touch Source | Original_Source__c |
| Milestones First Touch Event Date | Original_Acquired_At__c |
| Timestamp | Call_Start_Time__c, Submitted_At__c |
| Duration | Call_Duration_Seconds__c |
| Recording Player | Call_Recording_URL__c |
| Callernum | Caller_Phone__c, Phone__c |
| Destinationnum | Forwarded_To__c |
| Milestones Lead Created Landing | First_Page__c |
| Last Requested Url | Landing_URL__c |
| Gclid / Fbclid | GCLID__c / FBCLID__c |
| Integration Data Data Fbp | FB_FBP__c |
| Ga | GA4_Client_Id__c |
| Utm * | UTM_Source__c / Medium / Campaign / Content / Term |
| (CallRail IP-send checkbox enabled) → ip | IP_Address__c |
| Session Uuid | Session_UUID__c |
| Person Resource Id | CallRail_Person_Id__c |
| Callercity / Callerstate | Caller_City__c / Caller_State__c |
| Spam | Spam_Flag__c |

**DO NOT map** CallRail's parsed-browser field (e.g. `Browser` → "Safari") to `User_Agent__c`. The Phase E Apex rejects short non-Mozilla values anyway, but keeping it unmapped avoids polluting Form_Entry__c too.

---

## What Dustin does next (priority order)

### High value (next session)

1. **Add Lead-side schema for first-touch + repeat-caller fields** (~30 min):
   - Create on Lead: `Original_Source__c`, `Original_Acquired_At__c`, `Session_UUID__c`, `Caller_City__c`, `Caller_State__c`, `CallRail_Person_Id__c`
   - Extend `FormEntryProcessor.processCallRailEntry` to propagate (blank-fill for Original_Source, always-set for the others)
   - Unlocks TV-halo reporting at the Lead level (currently only at Form_Entry level)

2. **Resume Master Audit Tier 2 cleanup batch** (the work paused when CallRail came up):
   - #23 Bulk-pause 6,260 zero-impression Google Ads keywords
   - #24 Build `Universal_Anti_Junk` shared negative list
   - #15 Standardize 7 conversion actions to DATA_DRIVEN + 90/30 + ONE_PER_CLICK
   - Master audit estimates this as 4-5 hr scope

### Medium value (within 7 days)

3. **Apply Customer Match suppression audiences** (Phase 6 follow-up — UI work):
   - In Meta Ads Manager: apply `CRM_Suppression_DNC` as exclusion on every active adset
   - In Google Ads: apply `GAds_Suppression_DNC` as exclusion on every campaign
   - Build a Google Similar Audience off `GAds_Closed_Won`

4. **Clear `Meta_Config.Test_Event_Code__c` ('TEST95135')** — send Meta CAPI events to production Pixel reports instead of Test Events tab

### Lower priority

5. **Phase 8 — Lead INSERT refire after CallRail enrichment lands**: mirrors Phase 4a Step2 refire pattern. Fires when Lead.CallRail_Call_Id__c transitions null → populated. Replays the Lead INSERT conversion event with full GCLID. Adds ~50 lines Apex. Only worth doing if Smart Bidding data shows missing Lead-stage signal.

6. **Historical backfill** for Leads polluted by pre-Phase-E `lead_match_updated` path (e.g. Terri's User_Agent='Safari' from FE-0000064). Low priority; doesn't affect Smart Bidding.

---

## Open / known issues

- **CallRail User_Agent value is parsed-browser name only** (e.g. "Safari"), not raw UA. Phase E rejects it; Lead.User_Agent__c stays uncorrupted. If CallRail offers a raw-UA opt-in similar to their IP-send checkbox, enabling it would lift Meta CAPI EMQ. Worth checking next session.
- **Voice Nation phone leads still ship without GCLID** on the 360sms path. CallRail addresses the website-then-call subset. The cold-call-from-yard-sign subset still has no GCLID source — accept as residual gap.
- **Pure direct-to-homepage callers** with no `as-seen-on-tv` landing currently route to Organic (Rule 4 default). If 30 days of data shows TV-correlation patterns (call spikes during commercial windows), add a time-window rule for TV.

---

## Diagnostic queries

```bash
# Recent CallRail Form_Entry rows + processing result
sf data query --target-org mydevorg --query "
SELECT Id, Name, Form_Id__c, CallRail_Call_Id__c, Caller_Phone__c, Forwarded_To__c,
       CallRail_Source__c, Original_Source__c,
       Processed__c, Processing_Result__c, Matched_Record_Id__c, CreatedDate
FROM Form_Entry__c
WHERE Form_Id__c='CALLRAIL' OR CallRail_Call_Id__c != null
ORDER BY CreatedDate DESC LIMIT 20"

# Leads enriched by CallRail
sf data query --target-org mydevorg --query "
SELECT Id, Name, Phone, MobilePhone, LeadSource,
       GCLID__c, IP_Address__c, User_Agent__c,
       CallRail_Call_Id__c, Call_Recording_URL__c, Call_Duration_Seconds__c
FROM Lead
WHERE CallRail_Call_Id__c != null
ORDER BY LastModifiedDate DESC LIMIT 10"

# Form_Entry processing distribution by result
sf data query --target-org mydevorg --query "
SELECT Processing_Result__c, COUNT(Id) cnt
FROM Form_Entry__c
WHERE (Form_Id__c='CALLRAIL' OR CallRail_Call_Id__c != null) AND CreatedDate=LAST_N_DAYS:7
GROUP BY Processing_Result__c
ORDER BY COUNT(Id) DESC"
```

---

## Files shipped (4 commits on `feat/callrail-form-entry-fields`)

```
21c37b4 Phase E: FormEntryProcessor CallRail branch (no-create, blank-fill, spam-gated)
10bb189 Add Original_Acquired_At__c — first-touch event date
4a3fe24 Add 6 more Form_Entry__c fields for richer CallRail payload mapping
9101050 Add 9 Form_Entry__c fields for CallRail webhook intake (Phase C)
```

**Key SF artifacts (now in prod):**
- `force-app/main/default/objects/Form_Entry__c/fields/` — 16 new field-meta.xml files
- `force-app/main/default/permissionsets/Form_Entry_Manage.permissionset-meta.xml` — 68 fieldPermissions
- `force-app/main/default/classes/FormEntryProcessor.cls` — `processCallRailEntry` + helpers (`blankFill`, `looksLikeRealUserAgent`, `phoneMatchVariants`)
- `force-app/main/default/classes/FormEntryProcessor_Test.cls` — 7 new test methods + `ensureLiveMode()` helper

---

## Next-session starter prompt

```
Continuing CallRail integration work shipped 2026-05-18.

Read first (~5 min):
1. ~/marketing-cli/CALLRAIL_HANDOFF.md (this doc — full state)
2. ~/.claude/plans/read-master-audit-2026-05-16-md-and-any-curious-flute.md (the plan)
3. Memory: project_360sms_lead_source, project_sf_lead_intake_migration

What's live:
- CallRail Starter + Advanced Call Routing (~$65-80/mo all-in)
- DNI on every page via GTM
- 4 conditional routing rules → 4 source-specific 360sms numbers
- 16 Form_Entry__c fields + 4 Lead fields for CallRail enrichment
- Phase E FormEntryProcessor branch (no-create, blank-fill, spam-gated, UA-filtered)
- Webhook-to-Lead path verified end-to-end via FE-0000065 / Terri Sabo

Top priority for this session (pick one):
1. Add Lead-side schema for Original_Source / Caller_City / Caller_State /
   CallRail_Person_Id / Session_UUID / Original_Acquired_At. ~30 min.
2. Resume Master Audit Tier 2 cleanup batch (#23 bulk-pause 6,260 zero-imp
   keywords + #24 Universal_Anti_Junk shared neg list + #15 standardize
   conv-action attribution). ~4-5 hr.
3. Apply Customer Match audiences to Meta + Google Ads campaigns (UI work).
4. Investigate raw-UA opt-in checkbox in CallRail (lift Meta CAPI EMQ on
   phone leads).

Auto mode is fine. Start by reading the 3 sources above + tell me what
makes sense to ship today.
```
