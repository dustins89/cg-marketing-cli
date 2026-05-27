# marketing-cli — your marketing stack, on the command line, with Claude

A Python toolkit that lets Claude read your Google Ads, GA4, Search Console, Meta, Tag Manager, Business Profile, CallRail, and more — then make changes with per-change confirmation and an audit log.

14 CLIs share a single credentials file. Built to be used **with Claude Code**: Claude pulls the data, suggests fixes, you `apply` what you approve.

> **What this is for**: getting a real, asset-level audit of your paid + organic marketing stack in about 20 minutes, then iterating with Claude to fix what's broken.

---

## 15-minute Quickstart

### 1. Install Claude Code

```bash
# Mac
brew install --cask claude-code

# Or any OS
curl -fsSL https://claude.ai/install.sh | bash
```

Then sign in:

```bash
claude
```

It will prompt for an API key or a `claude.ai/code` web login the first time.

### 2. Install Python 3.9+ (skip if you have it)

Mac: `brew install python@3.12`
Anything else: https://www.python.org/downloads/

### 3. Clone this repo

```bash
git clone https://github.com/<your-handle>/cg-marketing-cli.git
cd cg-marketing-cli
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 4. Set up credentials for the first platform (Google Ads)

```bash
cp google-ads.yaml.example google-ads.yaml
chmod 600 google-ads.yaml
```

Open `google-ads.yaml` in your editor. The Google Ads section needs a developer token + OAuth client + customer ID. See **"Getting Google Ads credentials"** below — about 10 minutes the first time.

Then:

```bash
gads auth init
```

Browser opens, you log in, refresh token gets saved.

### 5. Verify and run your first pull

```bash
gads whoami           # should print your customer ID
gads pull campaigns --days 30
```

You should see a table of your campaigns. You're in.

### 6. Launch Claude in this directory and paste the day-one prompt

```bash
claude
```

Then paste the **day-one memory prompt** from [PROMPTING_GUIDE.md](./PROMPTING_GUIDE.md) — it sets six guardrail rules that persist across every future session. Then ask:

> "Audit my Google Ads account at the asset level. Use the `gads` CLI for every claim. Cover impression share, ad strength per RSA, extension performance, hourly CPA, and the top wasted spend. Output as Tier 1 / Tier 2 / Tier 3 with one numbered fix per finding."

Claude will run ~20 `gads pull` commands and produce an audit. See [SAMPLE_AUDITS/google_ads_sample.md](./SAMPLE_AUDITS/google_ads_sample.md) for what to expect.

---

## What's in this repo

| File | What for |
|---|---|
| [README.md](./README.md) | This file — Quickstart + per-CLI reference |
| [PROMPTING_GUIDE.md](./PROMPTING_GUIDE.md) | Day-one memory prompt + Salesforce+Claude setup + "build your own CLI" starter prompt |
| [LESSONS_LEARNED.md](./LESSONS_LEARNED.md) | Patterns and gotchas from real Claude-Salesforce work |
| [SAMPLE_AUDITS/](./SAMPLE_AUDITS/) | Redacted examples of what Claude produces |
| [HANDOUT.pdf](./HANDOUT.pdf) | Printable 5-page leave-behind |
| [google-ads.yaml.example](./google-ads.yaml.example) | Template for credentials (copy, fill in, gitignored) |
| Platform subpackages | `gads/`, `ga4/`, `search_console/`, `gtm/`, `crazyegg/`, `fb/`, `gbp/`, `psi/`, `yt/`, `maps/`, `cse/`, `lsa/`, `callrail/`, `postalytics/` |
| Per-CLI handoffs | Setup notes for the trickier platforms — `FACEBOOK_HANDOFF.md`, `GA4_SEARCH_CONSOLE_HANDOFF.md`, `OCI_HANDOFF.md`, `CALLRAIL_HANDOFF.md`, etc. |

---

## The 14 CLIs

| CLI | Platform | Auth | Status | Setup help |
|---|---|---|---|---|
| `gads` | Google Ads | OAuth | Live (read + apply) | This README, "Getting Google Ads credentials" below |
| `ga4` | GA4 Analytics + Admin | OAuth | Live (read + key-events) | [GA4_SEARCH_CONSOLE_HANDOFF.md](./GA4_SEARCH_CONSOLE_HANDOFF.md) |
| `sc` | Search Console | OAuth | Live (read) | [GA4_SEARCH_CONSOLE_HANDOFF.md](./GA4_SEARCH_CONSOLE_HANDOFF.md) |
| `gtm` | Google Tag Manager | OAuth | Live (read + apply) | Re-run `gads auth init` after enabling GTM scopes |
| `cegg` | Crazy Egg | HMAC | Live (read + apply) | API key + secret in yaml |
| `fb` | Meta Marketing API | System User token | Live (read) | [FACEBOOK_HANDOFF.md](./FACEBOOK_HANDOFF.md) |
| `gbp` | Google Business Profile | OAuth | Read | Needs `gbp_account_id` + `gbp_location_id` |
| `psi` | PageSpeed Insights | API key | Read | Works at low quota without key |
| `yt` | YouTube Data + Analytics | OAuth | Read | Needs `youtube_channel_id` |
| `maps` | Google Places (New) | API key | Read | `maps_api_key` in yaml |
| `cse` | Custom Search | API key + Engine ID | Read | Needs Programmable Search Engine set up |
| `lsa` | Local Services Ads | OAuth | Read | Works if you have an LSA account |
| `callrail` | CallRail v3 (DNI) | API key | Read | [CALLRAIL_HANDOFF.md](./CALLRAIL_HANDOFF.md) |
| `postalytics` | Postalytics direct mail | HTTP Basic | Live (read + audit) | [POSTALYTICS_HANDOFF.md](./POSTALYTICS_HANDOFF.md) |

After enabling new OAuth scopes (gbp, yt, gtm), re-run `gads auth init` once to refresh the shared refresh token across all OAuth-based CLIs.

`--help` works on every CLI: `gads --help`, `ga4 --help`, `fb --help`, etc.

---

## Getting Google Ads credentials

You need three things. Collect them first, then come back to step 4 in the Quickstart.

### A. Manager (MCC) account + developer token

Google requires developer tokens to be issued from a **Manager (MCC) account** — standalone advertiser accounts can't get one. If you only have a regular account, you need to create a free MCC first.

**Create an MCC** (5 min, instant):
1. https://ads.google.com/home/tools/manager-accounts/ → **Create a manager account**.
2. Pick "Manage other people's accounts" (counterintuitive but required for API access).
3. Country / timezone / currency to match your existing account.

**Link your existing account to the MCC**:
1. In the MCC: **Accounts → Performance → + → Link existing account** → enter your single account's customer ID.
2. Switch to your single account: **Tools & Settings → Setup → Account access** → accept the pending invitation.

**Apply for a developer token from the MCC**:
1. In the MCC: **Tools & Settings → Setup → API Center** (this menu only appears in MCC accounts).
2. Apply for **Basic access**. Approval is usually 1–2 business days.
3. Copy the developer token once approved.

You'll need:
- Developer token (from the MCC's API Center)
- MCC ID — goes into `login_customer_id`
- Your single-account ID — goes into `customer_id`

Test tokens only work on test accounts and won't see your real data.

### B. Google Cloud OAuth client

1. Go to https://console.cloud.google.com — create or pick a project.
2. **APIs & Services → Library** → search "Google Ads API" → **Enable**.
3. **APIs & Services → OAuth consent screen** → set up External, add your email as a test user.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID** → application type **Desktop app**.
5. Download the JSON. Note the `client_id` (ends in `.apps.googleusercontent.com`) and `client_secret`.

### C. Customer ID

In Google Ads (top-right corner): 10 digits, format `123-456-7890`. Dashes will be stripped on save.

---

## Pull commands (read-only)

All accept `--days N` (default 30) or `--since YYYY-MM-DD`, and `--format table|json` (default table).

```bash
gads pull campaigns
gads pull adgroups
gads pull keywords
gads pull search-terms      # primary source for negative-keyword analysis
gads pull negatives         # existing negatives (no date filter)
gads pull ads
gads pull conversions
gads pull ad-strength       # per-RSA ad strength
gads pull assets            # per-asset performance label
gads pull recommendations   # Google's pending recs
gads pull change-history    # 90-day audit log of who changed what
```

**Workflow for sharing with Claude**: pipe JSON to a file:

```bash
gads pull search-terms --days 30 --format json > /tmp/st.json
# then paste the contents in chat, or share the path if Claude can read it
```

---

## Apply commands (mutations with confirmation)

Claude (or you) produces a YAML file like this:

```yaml
version: 1
account: "1234567890"
changes:
  - type: add_negative_keyword
    scope: campaign
    campaign_id: "987654321"
    text: "free"
    match_type: PHRASE
    rationale: "12 clicks, $48 spend, 0 conv on 'free X' queries last 30d"

  - type: pause_keyword
    ad_group_id: "111222333"
    criterion_id: "444555666"
    rationale: "$120 spend / 0 conv / QS 3 over 60d"

  - type: adjust_budget
    campaign_id: "987654321"
    new_daily_budget_usd: 75
    previous_daily_budget_usd: 50
    rationale: "ROAS 4.2x, budget exhausted by 2pm avg"
```

Then:

```bash
gads apply changes.yaml --dry-run    # preview — no writes
gads apply changes.yaml              # interactive, prompts y/N/q per change
gads apply changes.yaml --yes        # batch apply (only if you trust the file)
```

Each apply is logged to `audit.log` (gitignored) with the rationale preserved.

### Supported change types

| `type` | Required fields | What it does |
|---|---|---|
| `add_negative_keyword` | `scope` (campaign\|ad_group), `text`, `match_type` (EXACT\|PHRASE\|BROAD), plus `campaign_id` or `ad_group_id` | Creates a new negative criterion |
| `pause_keyword` | `ad_group_id`, `criterion_id` | Sets keyword status to PAUSED |
| `pause_ad` | `ad_group_id`, `ad_id` | Sets ad status to PAUSED |
| `pause_ad_group` | `ad_group_id` | Sets ad group status to PAUSED |
| `adjust_budget` | `campaign_id`, `new_daily_budget_usd` | Updates campaign budget |
| `adjust_bid` | `ad_group_id`, `criterion_id`, `new_cpc_usd` | Updates keyword CPC bid |

Add `rationale: "..."` to any change — it shows in the confirm prompt and the audit log.

---

## Day-to-day loop

1. `gads pull search-terms --days 30 --format json > /tmp/st.json`
2. Paste contents to Claude → get back `changes.yaml`.
3. `gads apply changes.yaml --dry-run` → sanity check.
4. `gads apply changes.yaml` → confirm each one.
5. Spot check the Google Ads UI to confirm the change landed.

---

## Architecture conventions

- Each integration is a Python subpackage under the repo root (`gads/`, `ga4/`, etc.).
- All credentials live in a single `google-ads.yaml` file at the repo root (chmod 600, gitignored).
- All mutations go through a `changes.py` schema → `apply.py` handlers → `audit.log`. Read-only commands skip this.
- Default output format is `table` (Rich) for terminal, `json` for piping to Claude.
- Python ≥ 3.9.

---

## Troubleshooting

- **`gads: command not found`** — venv not activated. `source .venv/bin/activate`.
- **OAuth flow returns no refresh token** — Google's reusing a prior consent. Revoke at https://myaccount.google.com/permissions and re-run `gads auth init`.
- **`PERMISSION_DENIED: The customer ... is not enabled for the API`** — your Ads account needs Basic-tier developer token approval. Check API Center status.
- **`AUTHENTICATION_ERROR`** — refresh token revoked or expired. Re-run `gads auth init`.
- **GAQL errors after a library update** — Google deprecates API versions ~yearly. `pip install -U google-ads` and rerun.

---

## License

MIT — fork it, modify it, ship it. Attribution appreciated but not required.

## Contributing

Forks welcome. If you add a new platform CLI following the existing pattern (`cli.py`, `client.py`, `pull.py`, `apply.py`, `changes.py`, `format.py`), PRs are open.
