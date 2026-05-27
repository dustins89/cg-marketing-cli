# Postalytics Handoff & Setup — 2026-05-27

Reference for the Postalytics direct-mail integration: how it's wired in Salesforce, how the marketing-cli `postalytics` subcommand works, and decisions made along the way.

---

## TL;DR

- **There is NO Postalytics managed package on AppExchange.** "Salesforce integration" in Postalytics is a cloud OAuth connector that runs on their servers — you enable it from the Postalytics dashboard, not from SF setup.
- **The DBH org does NOT use that connector either.** What we have is a custom Apex implementation (`PostalyticsDispatcher` invocable + `PostalyticsQueueable`) that hits `POST /api/v1/send/{endpoint_id}` directly.
- **2026-05-27 fix:** the Apex previously read from `LeftM_DirectOne__Property_Address__c` family, which drifted from the address the flow gate evaluated (`Left_Main__Street__c`). Now reads from `Left_Main__*` (which are formulas pulling from `Account.Billing*`), so gate-checks and payload match.
- **Webhooks are not in this Postalytics plan.** Response tracking has to be polled, not pushed.

---

## How the SF side works

### Trigger chain

```
Opportunity Create where StageName='Appointment Set'
       │
       ▼  (record-triggered flow: 5-min scheduled path)
Dustin_Opportunity_Send_Appt_Booked_Direct_Mail.flow
       │
       ▼  (decision gate: First_Name__c + Last_Name__c + Left_Main__Street__c all populated)
PostalyticsDispatcher.send()  ← @InvocableMethod
       │
       ▼  (Test.isRunningTest() guard, then enqueue)
System.enqueueJob(PostalyticsQueueable)
       │
       ▼  (async, Database.AllowsCallouts)
POST https://api.postalytics.com/api/v1/send/{endpoint_id}
       │  Authorization: Basic base64(api_key + ":")
       │  body: {first_name, last_name, address_street, address_city,
       │         address_state, address_zip, address_street2: "-"}
       ▼
Postalytics queues the postcard for print + USPS
```

### Files

| Component | Repo path |
|---|---|
| Invocable entry point | `leadConvertWrapper/force-app/main/default/classes/PostalyticsDispatcher.cls` |
| Queueable + callout | `leadConvertWrapper/force-app/main/default/classes/PostalyticsQueueable.cls` |
| Tests (8, all green) | `leadConvertWrapper/force-app/main/default/classes/PostalyticsDispatcherTest.cls` |
| Trigger flow | `leadConvertWrapper/force-app/main/default/flows/Dustin_Opportunity_Send_Appt_Booked_Direct_Mail.flow` |
| Credentials | `Appointment_Notification_Config__mdt.Production` → `Postalytics_Endpoint_Id__c` + `Postalytics_API_Key__c` |

### Address field gotcha (READ BEFORE EDITING)

The Apex reads `Left_Main__{Street,City,State,Zipcode}__c` — these are **formula fields** on Opportunity that resolve `Account.Billing{Street,City,State,PostalCode}`. They are read-only.

- Runtime SOQL queries them fine — that's the whole point.
- Tests must populate `Account.Billing*` before inserting the Account so the formulas resolve in the queueable's re-query.
- DO NOT try `o.put('Left_Main__Street__c', '123 Main St')` — Apex throws `Field Left_Main__Street__c is not editable`.

### Why not the "Customer" address fields?

Dustin pointed out that `LeftM_DirectOne__Customer_Street__c` (Customer Street) is "the actual mailing address" — the absentee-owner mailing field. We dug in: **of 30 Appointment Set Opps in the last 90 days, only 1 had `Customer_Street__c` populated.** Nothing automated populates it (BatchData writes property data, not customer mailing addresses; Lead doesn't have a Customer_* field for convert mapping). Until a populator exists, mailing to the property (via `Left_Main__*` → `Account.Billing*`) is the only consistent path.

---

## How the marketing-cli side works

### Install

The package is registered as `postalytics` in `pyproject.toml`. After `pip install -e .`:

```bash
postalytics --help
```

Credentials come from `~/marketing-cli/google-ads.yaml` under key `postalytics_api_key`. (Get the key from Postalytics dashboard → Account → API.)

### Commands

| Command | What it does |
|---|---|
| `postalytics pull campaigns` | List every campaign. Add `--live-only` to filter to active ones, `--with-stats` to backfill real delivery numbers (N+1 calls — slow but accurate). |
| `postalytics pull campaign <drop_id>` | Detail for a single campaign with full stats. |
| `postalytics pull events <drop_id>` | Page of events (default page 1, 100/page). Use `--since-days N` to walk pages until events older than N days. |
| `postalytics audit` | Account rollup — totals, derived rates, flagged issues. `--json-out file.json` dumps the full blob. |

### Gotchas

- **The `/campaigns` list endpoint returns every campaign with ALL stat fields zeroed.** Only `/campaigns/{drop_id}` returns real numbers. `--with-stats` issues one call per campaign to backfill.
- **The path param everywhere is `drop_id`, NOT `campaign_id`.** (60323 vs 71238 for "Appt Booked W/ QR" — the latter is what the URL uses.)
- **Auth is HTTP Basic with empty password.** Header format: `Authorization: Basic base64(apikey + ":")`. The trailing colon is required.
- **`/events` has no server-side date filter.** Pagination only. The `--since-days` flag walks pages newest→oldest client-side and stops once events cross the threshold.

---

## On the question "should I install the managed package?"

**There is no managed package to install.** Postalytics' "Salesforce Integration" is a cloud-side OAuth connector — Postalytics' servers connect to your SF org and read/write standard objects. It is NOT listed on AppExchange.

If you ever enable the connector (Postalytics dashboard → Connect Integration Hub → Salesforce → OAuth as a sysadmin), it would:
- Add ONE custom field to Lead + ONE to Contact to receive delivery/response status codes
- Import SF Contacts/Leads/Accounts/Campaigns as Postalytics mailing lists
- Allow sending from SF Outbound Messages and Flows (something we already do via our custom Apex, so no conflict)

**Open question:** does the user's Postalytics plan tier include the SF connector? Webhooks aren't in their plan — the connector might be the same story. **Check `Connect Integration Hub` in the dashboard** before assuming it's available. If it IS available, it's the cheapest path to delivery + response tracking (status flows back to SF Lead/Contact via OAuth, no polling or webhook required).

---

## Response/delivery tracking options (none yet built)

Pick one to layer onto the current "send only" integration:

### Option A: Native Postalytics SF connector (cheapest IF plan supports it)

- Configure once in Postalytics dashboard
- Status writes to a field on Lead/Contact automatically
- No SF code beyond a small flow to mirror status onto the Opportunity
- **Blocker:** unknown whether the user's plan tier exposes this

### Option B: SF-side polling (the realistic fallback)

- New `Postalytics_Mailpiece__c` object stamped on every send (Opp lookup, send_date, captured address)
- Daily SF schedulable runs `GET /campaigns/{drop_id}/events` (via Apex HTTP callout, same auth scheme as `PostalyticsQueueable`), fuzzy-matches events to Mailpieces by name + zip, updates status
- Pros: works on any plan
- Cons: matching is fragile (typos break it), event firehose grows unboundedly

### Option C: Send-tracking only (MVP — ~1hr)

- Just the `Postalytics_Mailpiece__c` object + stamping on send
- No status tracking
- Gives you "did Opp X receive a postcard?" visibility today, no response data
- Can layer A or B on top later

**Recommendation:** Check the Postalytics dashboard for the SF connector first. If it's there, do A. If not, do C now, B if you decide response tracking is worth the matching fragility.

---

## Cross-references

- **Memory:** `project_postalytics_native_integration` — running state of the SF Apex side.
- **Audit:** [MASTER_POSTALYTICS_DEEP_AUDIT_2026-05-27.md](./MASTER_POSTALYTICS_DEEP_AUDIT_2026-05-27.md) — 9 findings from the first-pass audit.
- **Upstream data hygiene:** `project_callrail_dni`, `project_batchdata_enrichment` — both feed the address/name quality of what gets printed.
