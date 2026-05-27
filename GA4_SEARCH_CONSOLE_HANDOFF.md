# GA4 + Search Console integration — handoff

Last updated: 2026-05-15

Self-contained doc for adding GA4 and Search Console connectors to `~/marketing-cli/` alongside the existing `gads` integration. A fresh Claude reading this cold should be able to execute end-to-end.

---

## Why this exists

`gads` is live and pulling Google Ads campaign/keyword/search-term data. It tells you WHAT clicks cost and WHAT converts in Google Ads' eyes. It doesn't tell you:

- **Which landing pages convert** (Ads doesn't see post-click behavior beyond the conversion ping). → GA4 answers this.
- **What organic queries you rank for** and where there's untapped traffic. → Search Console answers this.

Together with gads, you get a full picture: paid acquisition cost → landing-page behavior → organic counterpart. That enables three concrete decisions:

1. **Pause underperforming landing pages** in Ads while keeping the keywords. (GA4 bounce-rate + conversion data per landing page.)
2. **Build SEO content** for high-impression / low-CTR queries we already rank for. (Search Console queries report.)
3. **Reallocate spend** from paid keywords where organic already wins to paid keywords where organic doesn't appear. (Joined gads + Search Console.)

Both APIs are read-heavy and low-risk. No mutations planned for either — these are pull-only integrations.

---

## Phase 0 — Prerequisites (verify before any code)

The existing Google Cloud OAuth client used for `gads` can be reused. You need to:

### 0a. Enable APIs in the existing Cloud project

Same project that holds `gads`' OAuth client (see `~/marketing-cli/google-ads.yaml` → `client_id` → look it up in console.cloud.google.com).

In that project: **APIs & Services → Library** → enable each:
- **Google Analytics Data API** (for GA4)
- **Google Search Console API**

(The existing Google Ads API stays enabled.)

### 0b. GA4 property ID

GA4 doesn't use the old `UA-xxxxxxxxx` view IDs. You need the **Property ID** (numeric, ~9 digits).

Where to find it: GA4 admin → **Admin** (gear icon, bottom left) → **Property Settings** → top-right shows "Property ID". Save it.

### 0c. Search Console verified property

Open https://search.google.com/search-console. You should see your verified properties — likely `https://www.dustinbuyshouses.net/` (or `sc-domain:YOUR_DOMAIN`).

If neither shows, verification needs to happen first (DNS TXT record or HTML tag). Note: Carrot has a Search Console verification panel that automates this if it's not done yet.

The exact site URL string (including trailing slash for URL-prefix properties, or `sc-domain:` prefix for domain properties) is what the API needs.

### 0d. Expand the OAuth refresh token's scopes

The current refresh token at `~/marketing-cli/google-ads.yaml` was minted with `https://www.googleapis.com/auth/adwords` scope only. To call GA4 + Search Console, you need a token with all three scopes:

- `https://www.googleapis.com/auth/adwords`
- `https://www.googleapis.com/auth/analytics.readonly`
- `https://www.googleapis.com/auth/webmasters.readonly`

You can't add scopes to an existing token — you have to re-do the OAuth dance. Two options:

- **Re-run `gads auth init`** with the scope list expanded (cleanest — single token, single yaml).
- **Mint separate tokens** per API into `ga4.yaml` and `search-console.yaml` (more files, but each is independently revocable).

Recommendation: single shared token. Change the scope list in `gads/auth.py` and re-run `gads auth init`. Existing gads functionality keeps working because `adwords` is still in the list.

---

## Phase 1 — Code scaffolding

Layout, mirroring the existing `gads/` subpackage shape:

```
~/marketing-cli/
├── gads/                       # existing, untouched
├── ga4/                        # NEW
│   ├── __init__.py
│   ├── cli.py                  # click subcommands: pull landing-pages, pull funnel, ...
│   ├── client.py               # google.analytics.data_v1beta client factory
│   ├── pull.py                 # GA4 Data API queries (RunReport)
│   └── format.py               # table / JSON output (reuse gads/format.py if possible)
├── search_console/             # NEW
│   ├── __init__.py
│   ├── cli.py                  # click subcommands: pull queries, pull pages, ...
│   ├── client.py               # webmasters v3 client factory
│   ├── pull.py                 # SearchAnalytics.query calls
│   └── format.py
└── pyproject.toml              # add: google-analytics-data, google-api-python-client
```

### Dependencies to add to `pyproject.toml`

```toml
[project]
dependencies = [
    # existing
    "google-ads>=25.0.0",
    "click>=8.0",
    "pyyaml",
    "rich",
    # new
    "google-analytics-data>=0.18.0",        # GA4 Data API
    "google-api-python-client>=2.0",        # Search Console (webmasters v3)
    "google-auth-oauthlib>=1.0",            # if not already pulled by google-ads
]
```

After editing, run from `~/marketing-cli/`:
```bash
source .venv/bin/activate
pip install -e .
```

### Console-script entries in pyproject.toml

```toml
[project.scripts]
gads = "gads.cli:cli"
ga4 = "ga4.cli:cli"
sc = "search_console.cli:cli"
```

So you get `gads ...`, `ga4 ...`, `sc ...` as three siblings.

### Credentials yaml

If single-token approach (recommended): no new yaml needed. Both new packages read from `~/marketing-cli/google-ads.yaml` (rename to `~/marketing-cli/credentials.yaml` eventually, but not blocking).

Add these keys to the yaml after re-auth:
```yaml
ga4_property_id: "123456789"          # from Phase 0b
search_console_site_url: "sc-domain:YOUR_DOMAIN"   # from Phase 0c
```

---

## Phase 2 — Pull commands

All commands default to **last 30 days** unless `--days N` or `--since YYYY-MM-DD` is passed. All have `--json` and `--table` output (table default).

### GA4 — `ga4 pull <thing>`

| Command | What it returns | Why |
|---|---|---|
| `ga4 pull landing-pages` | landingPage × { sessions, conversions, conv rate, bounce rate, avg session duration } | Find pages that convert vs leak. |
| `ga4 pull channels` | sessionDefaultChannelGroup × { sessions, conversions, revenue } | Paid vs organic vs direct vs referral mix. |
| `ga4 pull source-medium` | sessionSourceMedium × { sessions, conversions } | More granular than channel groups. |
| `ga4 pull geo` | city + state × { sessions, conversions } | <your-city>-area concentration check. |
| `ga4 pull devices` | deviceCategory × { sessions, conversions } | Mobile vs desktop conversion gap. |
| `ga4 pull conversions-by-page` | landingPage × eventName × eventCount, filtered to `conversion=true` events | Which pages fire which conversions. |
| `ga4 pull events` | eventName × eventCount × eventValue | All custom events (form submits, scroll depth, phone clicks). |

Underlying call: `BetaAnalyticsDataClient.run_report(RunReportRequest(...))`. Each command is one function in `ga4/pull.py`, ~15 lines each. Reference: https://developers.google.com/analytics/devguides/reporting/data/v1/basics

Critical fields for real estate use case:
- **Dimension**: `landingPage`, `sessionSourceMedium`, `sessionCampaignName`, `city`, `region`, `deviceCategory`, `eventName`.
- **Metric**: `sessions`, `screenPageViews`, `conversions`, `eventCount`, `bounceRate`, `userEngagementDuration`, `eventValue`.

### Search Console — `sc pull <thing>`

| Command | What it returns | Why |
|---|---|---|
| `sc pull queries` | query × { clicks, impressions, CTR, position } | Find high-impression low-CTR queries → SEO content opportunities. |
| `sc pull pages` | page × { clicks, impressions, CTR, position } | Which pages bring organic traffic. |
| `sc pull query-page` | (query, page) pairs × metrics | Which page ranks for which query. |
| `sc pull countries` | country × metrics | Filter out international noise. |
| `sc pull devices` | device × metrics | Mobile-search performance gap. |

Underlying call: `webmasters.searchanalytics().query(...)`. Reference: https://developers.google.com/webmaster-tools/v1/searchanalytics/query

Critical detail: Search Console data lags ~3 days. Default date range should be `today - 30 days` to `today - 3 days`.

### Defaults baked into every command

- `--limit 100` (rows). Override via flag.
- `--output table` (Rich) or `--output json`.
- Money values in micros (GA4 returns currency in standard units; gads returns micros — be consistent — convert micros → standard in format.py).
- Date format ISO-8601 throughout.

---

## Phase 3 — Cross-tool joiner (deferred, but design now)

Eventually a top-level `marketing report` command that joins:

- gads campaign perf
- GA4 landing-page conversion rate
- Search Console organic-vs-paid for the same query

Output: per-landing-page sheet showing paid CPA + organic clicks + conversion rate. Highlights pages where paid + organic both win (double down), pages where organic wins and paid loses (cut paid), pages where paid wins and organic doesn't appear (build SEO).

Don't build this in Phase 1–2. Note it exists so the data structures from each puller stay compatible (consistent date columns, consistent landing-page URL normalization — strip query strings + trailing slashes consistently across the three).

---

## Phase 4 — Usage loop

Same pattern as gads:

1. You: `ga4 pull landing-pages --days 30 --json | pbcopy` → paste to Claude.
2. Claude: reads, suggests bid changes / negatives / new ad copy based on landing-page behavior, produces a `pending_changes.yaml` for **gads** (since GA4 is read-only — the action lives in Google Ads).
3. You: `gads apply pending_changes.yaml`.

Search Console flow:
1. `sc pull queries --days 30 --json | pbcopy` → paste to Claude.
2. Claude: suggests blog topics / page-content tweaks based on high-impression / low-CTR queries.
3. You: implement the content changes on the WordPress site (manual, no apply step).

---

## Verification

End-to-end smoke test after Phase 1:

- `ga4 pull landing-pages --days 7 --table` returns at least one row with non-zero sessions for `dustinbuyshouses.net/cash-for-house/` or similar Carrot landing page.
- `sc pull queries --days 30 --table` returns the top-impression queries (likely "we buy houses <your-city>" / "sell my house fast <your-city>" variants).
- Cross-check: GA4 landing-page session count for `/cash-for-house/` should roughly match Search Console clicks for the same page over the same date range, within 30% (GA4 includes paid traffic too, so it'll be higher).

---

## Critical files

**To create**:
- `~/marketing-cli/ga4/{__init__.py, cli.py, client.py, pull.py, format.py}`
- `~/marketing-cli/search_console/{__init__.py, cli.py, client.py, pull.py, format.py}`

**To edit**:
- `~/marketing-cli/pyproject.toml` (add deps + scripts)
- `~/marketing-cli/gads/auth.py` (expand scope list)
- `~/marketing-cli/google-ads.yaml` (after re-auth + add property_id / site_url keys)

**To re-run**:
- `gads auth init` (mints fresh token with all three scopes)

---

## Open caveats

- **GA4 data freshness**: ~24h delay for processed data, ~3h for streaming dashboard data. The Data API returns the processed version. Don't use these for same-day decisions.
- **Search Console data freshness**: ~3 days. Default queries should exclude the last 3 days.
- **API quotas**: GA4 Data API allows 25,000 tokens/day per property (each report = ~1 token). Search Console allows 1,200 queries/min. Both are far above what we'll hit.
- **Sampling**: GA4 doesn't sample for queries under 10M events; we're nowhere near that. Search Console anonymizes queries with very low impressions ("anonymous queries" row). Live with it.
- **Auth scope conflict**: Adding new scopes invalidates the existing refresh token's permissions for those new scopes until re-consent. The first `ga4 pull` call after scope change will fail if you didn't re-run `auth init`. Always re-auth after scope changes.

---

## Memory references

- `project_gads_cli.md` — overall marketing-cli status
- `~/marketing-cli/CLAUDE.md` — workspace conventions
- `~/marketing-cli/OCI_HANDOFF.md` — sister project (SF → Google Ads conversion uploads)

---

## Next action

Phase 0 — verify GA4 property ID and Search Console verified property. If both exist, proceed to Phase 1 scaffolding. If verification's missing on Search Console, do that first (10 min DNS record).
