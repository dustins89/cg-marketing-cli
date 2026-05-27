# OCI Phase 4 — Apex uploader: manual finish steps

Last updated: 2026-05-15. Deployed to `mydevorg` (prod) AND `dbh-partial` (sandbox).

## What's live in SF right now

**Custom MDT** — `Google_Ads_Conversion_Action__mdt` with 3 records (`SF_Appointment_Scheduled`, `SF_Contract_Signed`, `SF_Deal_Closed`). All records have `Resource_Name__c = REPLACE_WITH_RESOURCE_NAME` — you'll overwrite these in step 2 below.

**Custom object** — `Google_Ads_Conversion_Queue__c` (10 fields, 2 list views). Flows are already stamping rows on every Opp insert / Tx profit-set / Tx Closed/Won transition. Rows accumulate as `Status = Pending` until the schedulable starts draining them.

**3 record-triggered flows** — `Dustin_OCI_Stamp_Appointment_Scheduled`, `Dustin_OCI_Stamp_Contract_Signed` (+ `_OnInsert` edge case), `Dustin_OCI_Stamp_Deal_Closed`. All active. Already firing on real records.

**Apex** — `GoogleAdsApiClient`, `GoogleAdsOciQueueable`, `GoogleAdsOciSchedulable`, `GoogleAdsTestMocks` + 3 test classes. Deployed but NOT scheduled — the schedulable doesn't run until you start it (step 6).

**Permission Set** — `Google_Ads_OCI_User`. Deployed but missing External Credential principal grant (step 3 adds it) and unassigned to any user (step 5 assigns).

## What you need to do (~30 min total)

### Step 1 — Create 3 conversion actions in Google Ads UI (~10 min)

In Google Ads → **Goals → Conversions → New conversion action**:

For each of the three, choose: **Import → Other data sources or CRMs → Track conversions from clicks**.

| Conversion name             | Category               | Count | Value                           | Click-through window |
|-----------------------------|------------------------|-------|---------------------------------|----------------------|
| `SF - Appointment Scheduled` | Lead                   | One   | Don't use a value               | 90 days              |
| `SF - Contract Signed`       | Submit lead form       | One   | Use different values, default $500 | 90 days           |
| `SF - Deal Closed`           | Purchase               | One   | Use different values, default $5000 | 90 days          |

After saving each, click into it → copy the **conversion action resource name** from the URL or the "Conversion source" section. Format: `customers/{customer_id}/conversionActions/{action_id}` (e.g. `customers/YOUR_CUSTOMER_ID/conversionActions/987654321`).

### Step 2 — Plug resource names into SF (CLI, ~2 min)

Once you have the 3 resource names, run from the worktree (`~/leadConvertWrapper/.claude/worktrees/jovial-saha-af9d78/`):

```bash
# Edit the 3 MDT records in this worktree, replacing REPLACE_WITH_RESOURCE_NAME with the real values:
# force-app/main/default/customMetadata/Google_Ads_Conversion_Action.SF_Appointment_Scheduled.md-meta.xml
# force-app/main/default/customMetadata/Google_Ads_Conversion_Action.SF_Contract_Signed.md-meta.xml
# force-app/main/default/customMetadata/Google_Ads_Conversion_Action.SF_Deal_Closed.md-meta.xml

# Then deploy just those 3 MDT records to prod:
sf project deploy start \
  --source-dir force-app/main/default/customMetadata/Google_Ads_Conversion_Action.SF_Appointment_Scheduled.md-meta.xml \
  --source-dir force-app/main/default/customMetadata/Google_Ads_Conversion_Action.SF_Contract_Signed.md-meta.xml \
  --source-dir force-app/main/default/customMetadata/Google_Ads_Conversion_Action.SF_Deal_Closed.md-meta.xml \
  --target-org mydevorg
```

(Or just tell Claude the resource names and Claude can do the file edits + deploy.)

### Step 3 — Create External Credential in SF UI (~5 min)

Setup → Security → **External Credentials** → New:

- Label: `Google Ads OCI`
- Name: `Google_Ads_OCI`
- Auth Protocol: **OAuth 2.0**

After saving, you'll need an **Auth Provider** for Google. If one doesn't exist already:
- Setup → Auth Providers → New → Provider Type: **Google**
- Consumer Key: `client_id` from `~/marketing-cli/google-ads.yaml`
- Consumer Secret: `client_secret` from same yaml
- Save. Copy the Callback URL Salesforce shows.
- Go to console.cloud.google.com → APIs & Services → Credentials → your OAuth client → add that Callback URL to "Authorized redirect URIs" → save.

Back on the External Credential:
- Tab **Principals** → New:
  - Parameter Name: `Dustin` (or anything; just needs to match the permset)
  - Identity Type: **Named Principal**
  - Sequence Number: 1
  - Authentication Flow Type: **Browser Flow**
  - Scope: `https://www.googleapis.com/auth/adwords`
  - Save → "Authenticate" button → log in as `dustin@dustinbuyshouses.net` → consent → Salesforce captures the refresh token.
- Tab **Custom Headers** → New:
  - Name: `developer-token`
  - Value: your developer token from `~/marketing-cli/google-ads.yaml` (the `developer_token` key)
  - Sequence Number: 1

### Step 4 — Create Named Credential in SF UI (~1 min)

Setup → Security → **Named Credentials** → tab "Named Credentials" → New:

- Label: `Google Ads API`
- Name: `Google_Ads_API`
- URL: `https://googleads.googleapis.com`
- Allowed Namespaces: (leave blank)
- External Credential: `Google_Ads_OCI`
- ✓ Allow Formulas in HTTP Body
- ✓ Generate Authorization Header
- Save.

### Step 5 — Grant permset access + assign to yourself (~2 min)

Setup → **Permission Sets** → `Google Ads OCI User` → click **External Credential Principal Access** → **Edit** → move `Google_Ads_OCI - Dustin` to "Enabled" → Save.

Then from CLI to assign permset to yourself:
```bash
sf org assign permset --name Google_Ads_OCI_User --target-org mydevorg
```

### Step 6 — Start the schedulable (~30 sec)

From CLI (must run as Dustin — your default org context):
```bash
echo "System.schedule('GA OCI Uploader', '0 0,15,30,45 * * * ?', new GoogleAdsOciSchedulable());" | sf apex run --target-org mydevorg
```

That schedules it to run every 15 minutes. To verify it's scheduled:
```bash
sf data query --query "SELECT CronJobDetail.Name, NextFireTime FROM CronTrigger WHERE CronJobDetail.Name = 'GA OCI Uploader'" --target-org mydevorg
```

## Verification (after step 6 completes)

Within ~30 min of step 6, you should see:

```bash
# Are there queue rows waiting?
sf data query --query "SELECT Status__c, Conversion_Action__c, COUNT(Id) cnt FROM Google_Ads_Conversion_Queue__c GROUP BY Status__c, Conversion_Action__c" --target-org mydevorg

# Most recent uploaded row (proves schedulable + queueable worked end-to-end):
sf data query --query "SELECT Id, Name, Conversion_Action__c, Status__c, Uploaded_At__c, Last_Error__c FROM Google_Ads_Conversion_Queue__c ORDER BY LastModifiedDate DESC LIMIT 5" --target-org mydevorg
```

Within ~6 hours, Google Ads UI → Goals → Conversions → `SF - Appointment Scheduled` should show count > 0.

## Common troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| All rows `Status=Failed, Last_Error contains 'customer_id'` | MDT records still have `REPLACE_WITH_RESOURCE_NAME` | Redo step 2 |
| Rows `Status=Failed, Last_Error contains '401'` or `'UNAUTHENTICATED'` | OAuth refresh token expired or External Credential not set up | Redo step 3 |
| Rows `Status=Failed, Last_Error contains '403'` | Developer token missing or invalid | Verify Custom Header on External Credential (step 3 last part) |
| Rows `Status=Failed, Last_Error contains 'GCLID'/'GBRAID'/'WBRAID'` | Click ID expired (>90 days old) or invalid | Acceptable — Google ignores click IDs past their lookback. Reset Attempts to 5 to stop retries. |
| Rows `Status=Pending` indefinitely, never upload | Schedulable not running | Re-run step 6; check CronTrigger query above |
| Rows `Status=Skipped_No_ClickId` | No click ID on the source Opp/Tx | Expected for non-Google-Ads leads (Voice Nation phone, organic, direct). |

## Sandbox path (same steps, separate config)

Same steps 1–6 against `dbh-partial`, but:
- Use **separate** sandbox conversion actions in Google Ads UI (don't share with prod — `SF - Appointment Scheduled (SANDBOX)`, etc.)
- Update the sandbox MDT records to point at the sandbox resource names
- The External Credential principal in sandbox can reuse the same OAuth client but does its own auth dance

## What this DOESN'T cover (separate phases)

- **Phase 5 — Python `gads oci` companion** in `~/marketing-cli/`. Read-only queue inspector + manual replay.
- **Backfill** of historical Opp/Tx records that have GCLID/GBRAID populated but were created before the flows existed. One-off Anonymous Apex.
- **Voice Nation phone-lead attribution** — VN leads have no URL data, so they currently stamp queue rows with all click-IDs null, get marked `Skipped_No_ClickId`. Adding phone tracking (CallRail) is a separate sub-project.
- **Conversion adjustments** — if Projected_Profit gets recalculated after Conv2 fires, the original conversion value isn't updated. Google Ads has `UploadConversionAdjustments` for this; deferred.

## File locations

**SF source** (worktree): `~/leadConvertWrapper/.claude/worktrees/jovial-saha-af9d78/`
- `force-app/main/default/objects/Google_Ads_Conversion_Action__mdt/`
- `force-app/main/default/objects/Google_Ads_Conversion_Queue__c/`
- `force-app/main/default/customMetadata/Google_Ads_Conversion_Action.*`
- `force-app/main/default/flows/Dustin_OCI_Stamp_*.flow-meta.xml`
- `force-app/main/default/classes/GoogleAds*.cls`
- `force-app/main/default/permissionsets/Google_Ads_OCI_User.permissionset-meta.xml`

**Plan**: `~/.claude/plans/logical-petting-ladybug.md`

**This handoff**: `~/marketing-cli/OCI_PHASE_4_HANDOFF.md`

**Parent OCI handoff**: `~/marketing-cli/OCI_HANDOFF.md`
