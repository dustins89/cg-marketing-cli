# Facebook (Meta) integration — handoff

Last updated: 2026-05-15

Self-contained doc for adding a `fb` CLI to `~/marketing-cli/` alongside `gads`, `ga4`, `sc`, `gtm`, `cegg`. Goal: read Pixel config + Marketing API state + send conversions via CAPI. A fresh Claude reading this cold should be able to execute Phase 1 once Phase 0 is complete.

---

## Why this exists

Auditing GTM revealed a Facebook tracking gap parallel to the Google Ads one: tag #42 "FB Lead Event" fires on broken trigger #43 (filtered to /step-2 form submissions, but Gravity Forms never fires there because the actual form is on /step-2/ and the AJAX confirmation triggers gform_confirmation_loaded, not a native form-submit). FB conversion attribution has been silently dead.

Before we fix the GTM tag, we want API access so we can:
- Read what the Pixel is currently set up to receive (event subscriptions, recent events)
- See which CAPI integrations are active
- Verify what Meta is actually attributing conversions to today
- Eventually route SF Opportunity/Transaction stage changes into Meta CAPI (parallel to the SF→Google Ads OCI pipeline that just shipped)

---

## What's in scope

| Capability | Phase | Notes |
|---|---|---|
| Read campaigns / ad sets / ads / performance | 1 | Marketing API GET endpoints, mirror `gads pull campaigns / ads / search-terms` shape |
| Read Pixel ID + recent events received | 1 | Pixels endpoint + Pixel Events |
| Read CAPI integration state (which servers are sending events) | 1 | Pixels.dataset_id + connected systems |
| Read connected Ad Accounts, Business Manager assets | 1 | Business Manager API |
| Send CAPI events (server-side conversion uploads, mirror SF OCI) | 2 | Conversions API (`/events` endpoint) — full mutation pipeline like gads apply |
| Mutate campaigns / budgets / pauses | 3 | Marketing API mutations |

Phase 1 is the immediate need (read everything to inform GTM fix). Phase 2 is the real prize (server-side conversion attribution → matches SF OCI on Google side). Phase 3 is opportunistic.

---

## Phase 0 — Prerequisites (you do these in Meta UI)

### 0a. Confirm what's already set up

Visit https://business.facebook.com → check that you have:
- A Business Manager account (you do — your FB Pixel exists at ID 365910274042753 per GTM tag #24)
- The Pixel attached to a Data Source / Dataset
- An Ad Account connected to the Business Manager

Note the IDs:
- **Business Manager ID** (top-right user menu → Business settings → URL has `business_id=...`)
- **Ad Account ID** (Business settings → Ad accounts → format is usually `act_NNNNNNNNNN`)
- **Pixel/Dataset ID**: 365910274042753 (already known from GTM #24)

### 0b. Create a Meta App for Marketing API access

1. Go to https://developers.facebook.com/apps → "Create App"
2. Use case: **"Other"** → App type: **"Business"**
3. Name it something like "DBH Marketing CLI" (you, your business)
4. Once created, in the left sidebar add the products:
   - **Marketing API** (for reading/writing ad data)
   - **Conversions API** (for CAPI event sending)

### 0c. Get a System User access token

System User tokens are the standard for server-to-server API access — they don't expire (unlike user tokens).

1. Business Manager → Business Settings → **System Users** → **Add**
2. Name: "marketing-cli", Role: **Admin**
3. Click **Add Assets** → assign your Ad Account + Pixel + Pages with full control
4. Click **Generate New Token** for the system user → select your app → tick scopes:
   - `ads_read`
   - `ads_management`
   - `business_management`
   - `read_insights`
5. **Token expires: never** (System User tokens don't expire by default — confirm "Never" is selected if asked for duration)
6. Copy the token. **Treat it like a password** — full ad account access.

### 0d. Note the API version

Meta deprecates/replaces API versions every ~3 months. Check the current "Latest" version at https://developers.facebook.com/docs/graph-api/changelog (likely something like `v23.0` as of mid-2026). We'll pin to a specific version in our client.

---

## Phase 1 — Code scaffolding

```
~/marketing-cli/
├── fb/                         # NEW
│   ├── __init__.py
│   ├── cli.py                  # `fb` console script
│   ├── client.py               # facebook_business SDK client factory
│   ├── pull.py                 # GET endpoints (campaigns, ads, pixels, events)
│   └── format.py               # re-export gads.format.emit
└── pyproject.toml              # add: facebook-business
```

### Dependency

`facebook-business` is Meta's official Python SDK:
```toml
dependencies = [
    # ... existing
    "facebook-business>=20.0",
]
```

### Console script

```toml
[project.scripts]
fb = "fb.cli:cli"
```

### Credentials yaml

Add to `~/marketing-cli/google-ads.yaml` (we use one shared yaml, despite the historical name):

```yaml
fb_access_token: "EAAxxxxxxxxxxxxxx"   # System user long-lived token from Phase 0c
fb_app_id: "123456789012345"           # From the Meta App you created in 0b
fb_app_secret: "abc123..."             # From the Meta App's Settings → Basic
fb_business_id: "..."                  # Phase 0a
fb_ad_account_id: "act_..."            # Phase 0a (KEEP the act_ prefix)
fb_pixel_id: "365910274042753"         # Already known
fb_api_version: "v23.0"                # Phase 0d, pin explicitly
```

---

## Phase 1 — Pull commands

| Command | What it returns | Why |
|---|---|---|
| `fb whoami` | Token info: scopes, expiration, business assets | Verify auth works |
| `fb pull campaigns` | campaign × { name, status, objective, daily_budget, spend, impressions, clicks, cpc, conversions } | Mirror `gads pull campaigns` shape |
| `fb pull adsets` | adset × { name, status, targeting summary, spend, ctr } | Per-adset perf |
| `fb pull ads` | ad × { name, creative summary, spend, conversions } | Per-ad perf |
| `fb pull pixel-events` | recent events received by the pixel × {event_name, count, last_received} | Diagnose which CAPI events are arriving (Lead, Purchase, etc.) |
| `fb pull pixel-info` | pixel ID + dataset ID + first-party cookie status + connected systems | Identify if a CAPI server is already sending |
| `fb pull audiences` | custom + lookalike audiences × { source, size, last_refreshed } | Audit retargeting setup |

All read-only. Mirror the `gads pull` flag structure: `--days N`, `--since YYYY-MM-DD`, `--format table|json`, `--limit N`.

---

## Phase 2 — CAPI event sending (the real prize)

When Phase 1 surfaces what events the Pixel is currently configured to receive, we can build a `fb apply changes.yaml` flow analogous to `gads apply`:

- Change types: `send_lead_event`, `send_purchase_event`, `update_pixel_event_subscription`
- Each Lead event includes: hashed PII (email, phone, name) + event_id + value + currency + source URL
- Once stable, this becomes the destination for SF Opportunity/Transaction stage changes (parallel to the SF→Google Ads OCI pipeline)

Don't build Phase 2 in the first session. Just leave the data model compatible.

---

## Phase 3 — Mutations (deferred)

Pause campaigns, adjust budgets, change bid caps, etc. Mirror the `gads apply` schema. Lower priority than CAPI — we can pause campaigns in the Meta UI for now.

---

## Verification (end of Phase 1)

- `fb whoami` returns user info + lists at least one ad account + the pixel
- `fb pull pixel-events --days 7` returns rows including any `Lead` events that have actually fired (we expect this to be near-zero given the broken GTM tag #42 — that's the diagnostic confirmation)
- `fb pull campaigns --days 30` returns campaign performance (or "no active campaigns" if Meta isn't currently spending)

---

## Handoff to fix GTM tag #42

Once Phase 1 is live and we can confirm:
1. The Pixel has recent events received via the gtag.js Pixel tag (browser-side) — these come from tag #24, NOT #42
2. The Pixel is NOT receiving `Lead` events (or only stale ones from before whatever broke tag #43)

Then we know the GTM repoint is safe to apply: it'll start firing real Lead events and we'll see them in `fb pull pixel-events` within minutes.

---

## Critical caveats

- **Meta API breaks frequently.** Pin the version in client.py (`fb_api_version: "v23.0"`). Update intentionally, not casually.
- **Rate limits are aggressive.** The SDK auto-retries with backoff; CLI commands should respect that.
- **System User tokens don't expire**, but they CAN be revoked if business ownership changes. If commands start failing with auth errors, regenerate via Phase 0c.
- **Don't share the access token.** It has full ad-account write access. chmod 600 on the yaml (already in place).
- **Privacy / hashed data**: Phase 2 CAPI events MUST send SHA256-hashed user data (email, phone). The `facebook-business` SDK has helpers for this — never send raw PII.

---

## Memory references

- `project_gads_cli.md` — overall marketing-cli state
- `~/marketing-cli/CLAUDE.md` — workspace conventions
- `~/marketing-cli/GA4_SEARCH_CONSOLE_HANDOFF.md` — the doc this is modeled after
- `~/marketing-cli/OCI_HANDOFF.md` — sister project for Google Ads offline conversions (now SHIPPED)

---

## Next action (you)

Phase 0 — gather credentials. Specifically:
1. Confirm/create a Meta App in developers.facebook.com (Business type)
2. Generate a System User access token via Business Manager (Phase 0c)
3. Note your Business Manager ID + Ad Account ID
4. Paste the values back here and I'll wire them into the yaml and run `fb whoami` to verify
