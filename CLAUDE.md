# Marketing CLI — workspace context

Personal multi-platform marketing CLI for <Your Business> (real estate wholesaler, <your-city>-area). Built to be used WITH Claude — Claude pulls data, suggests changes, you apply them with per-change confirmation.

This file is loaded into every Claude Code session in this directory. Keep it tight; it's instructions, not docs.

## Owner

Dustin Singer. Real estate wholesaler / investor. <Your City>, <ST> market. Single-account Google Ads (customer YOUR_CUSTOMER_ID) under MCC YOUR_MCC_ID. SF org is the source of truth for leads/opportunities/transactions — lives in the `~/leadConvertWrapper` repo.

## Current state (as of 2026-05-15)

### Built and working
- **`gads`** — Google Ads pull/apply CLI. Phase 1–3 complete. Reads campaigns, ad groups, keywords, search terms, negatives, ads, conversions. Applies negatives, pauses, budget changes, bid changes with per-change confirm. All apply attempts log to `audit.log`.

### Built and working (added 2026-05-15)
- **`ga4`** — GA4 Data API CLI, LIVE. Property YOUR_GA4_PROPERTY_ID. Subcommands: `pull landing-pages | channels | source-medium | geo | devices | conversions-by-page | events`.
- **`sc`** — Search Console CLI, LIVE. Property `sc-domain:YOUR_DOMAIN`. Subcommands: `pull queries | pages | query-page | countries | devices`, plus `sc sites`.

### Scaffolded — needs Phase 0 unlock to be usable
- **`gtm`** — Google Tag Manager v2 CLI with full read/write. Read: `gtm accounts | containers | workspaces | pull tags | pull triggers | pull variables | pull conversions` (last is a diagnostic for "what conversion tags exist + what triggers fire them?"). Write via `gtm apply changes.yaml` with per-change y/N/q + audit log; supported types in `gtm/changes.py` (`pause_tag`, `unpause_tag`, `update_tag_name`, `add_trigger`, `add_ga4_event_tag`, `publish_workspace`). **Blocked on**: re-running `gads auth init` (3 GTM scopes added 2026-05-15) + `gtm_account_id` + `gtm_container_id` keys in yaml.

### Built and working (added 2026-05-15)
- **`cegg`** — Crazy Egg CLI. HMAC-signed (separate auth from the Google stack). Commands: `cegg status | auth-check | pull snapshots | pull snapshot <id> | apply <yaml>`. Mutation types in `crazyegg/changes.py`: `create_snapshot`, `update_snapshot`, `stop_snapshot`, `restart_snapshot`. Account has 19 stale heatmaps, all `expires_at` in 2020-2021 — tracking script likely not installed on current WP site (dbh_migration is active).

### Planned (in rough priority order)

1. **Salesforce Offline Conversion Import (HIGHEST LEVERAGE)** — wire SF Opportunity/Transaction stage changes → Google Ads `ConversionUploadService` so the bid algorithm optimizes for actual deals, not just form fills. Requires GCLID capture on Carrot/WordPress forms, GCLID propagation through Lead→Opp→Tx, Apex schedulable for uploads. This is THE highest-impact paid-ads improvement available.
2. **Cross-tool joiner** — once gads + ga4 + sc + sf are all wired, a `marketing report` command that joins by landing-page / campaign / date for unified review.

## Architecture conventions

- Each integration is a subpackage under `gads/` (or eventually a sibling package).
- All credentials live in `~/marketing-cli/*.yaml` files. chmod 600. gitignored.
- All mutations go through the `changes.py` schema → `apply.py` handlers → `audit.log`. Read-only commands skip this.
- Default output format is `table` (Rich) for terminal, `json` for piping to Claude.
- Python ≥ 3.9. System Python on this Mac is 3.9.6 — keep compatibility there.

## Working with Dustin in this project

- He's a wholesaler, not a developer. Frame recommendations in marketing/business terms first, code/API terms second.
- Heavy SF user — when relevant, cross-reference SF objects (Lead/Opportunity/Transaction/__c custom fields) from `~/leadConvertWrapper`.
- Prefers seeing the data before approving changes — never auto-apply mutations, always use the `--dry-run` then interactive `gads apply` flow.
- Has a Make.com → SF-native migration in flight (memory: project_sf_lead_intake_migration.md). Don't introduce new Make.com dependencies; native-first or Apex-first.

## Day-to-day commands

```bash
cd ~/marketing-cli && source .venv/bin/activate

# Pull data
gads pull campaigns --days 30 --format json > /tmp/gads_campaigns.json
gads pull search-terms --days 30 --format json > /tmp/gads_search_terms.json
gads pull keywords --days 30 --format json > /tmp/gads_keywords.json
gads pull negatives --format json > /tmp/gads_negatives.json
gads pull ads --days 30 --format json > /tmp/gads_ads.json
gads pull conversions --days 30 --format json > /tmp/gads_conversions.json

# Apply Claude-generated changes
gads apply /tmp/proposed_changes.yaml --dry-run    # preview
gads apply /tmp/proposed_changes.yaml              # interactive y/N/q
```

## Files

- `gads/` — Google Ads CLI package (cli, auth, client, pull, apply, changes, format)
- `ga4/` — GA4 Data API CLI package (cli, client, pull, format)
- `search_console/` — Search Console CLI package (cli, client, pull, format)
- `gtm/` — Google Tag Manager CLI package (cli, client, pull, apply, changes, format)
- `crazyegg/` — Crazy Egg CLI package (cli, client, pull, apply, changes, format)
- `google-ads.yaml` — shared credentials for ALL FIVE CLIs (chmod 600, gitignored). Keys: `ga4_property_id`, `search_console_site_url`, `gtm_account_id`, `gtm_container_id`, `crazyegg_api_key`, `crazyegg_api_secret`.
- `audit.log` — JSON lines log of every mutation attempt (gitignored)
- `README.md` — public-facing setup walkthrough (Phase 0 prerequisites)
- `GA4_SEARCH_CONSOLE_HANDOFF.md` — Phase 0 unlock steps for `ga4` + `sc`
- `OCI_HANDOFF.md` — SF offline conversion import design doc
- `pyproject.toml` — Python project + deps

## Known gotchas

- Editable installs (`pip install -e .`) hardcode absolute paths. If you ever rename or move this directory, recreate the venv.
- Google Ads developer tokens are MCC-only — single advertiser accounts can't get one directly. We use the MCC (YOUR_MCC_ID) for auth, query the single account (YOUR_CUSTOMER_ID).
- All `conv_value_usd` is currently $0 because conversion values aren't set in Google Ads UI. Until that's fixed, ROAS is meaningless and the bid algorithm has no value-signal. Fixing this is a manual UI step OR (better) flows through from SF OCI once that's built.
