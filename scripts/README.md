# scripts/

Operational helpers for the marketing-cli — scheduled audits, batch ops, etc.

## Bi-weekly audit

`biweekly_audit.py` pulls fresh data from every CLI (gads, ga4, sc, fb, yt, maps),
compares to the previous run, generates a markdown report, and optionally emails it.

### Manual run

```bash
cd ~/marketing-cli && source .venv/bin/activate

# Pull + report (no email)
python3 scripts/biweekly_audit.py

# Pull + report + email
python3 scripts/biweekly_audit.py --email

# Skip pulls, just regenerate report from cached JSON
python3 scripts/biweekly_audit.py --no-pull
```

Reports land in `~/marketing-cli/audits/YYYY-MM-DD_biweekly.md`. Raw JSON in
`audits/_data/YYYY-MM-DD/`.

### Email setup (one-time)

Add to `~/marketing-cli/google-ads.yaml`:

```yaml
audit_email_from: "dustin@dustinbuyshouses.net"
audit_email_to: "dustin@dustinbuyshouses.net"
audit_email_smtp_host: "smtp.gmail.com"
audit_email_smtp_port: 587
audit_email_smtp_user: "dustin@dustinbuyshouses.net"
audit_email_smtp_password: "abcd efgh ijkl mnop"  # Gmail App Password
```

**For Gmail with 2FA:** generate an App Password at https://myaccount.google.com/apppasswords
(can't use your regular Gmail password if you have 2-step verification enabled — Google blocks it).

### Schedule it (launchd)

```bash
bash scripts/install_audit_job.sh
```

This:
- Copies the plist to `~/Library/LaunchAgents/`
- Loads it with launchctl
- Fires every Sunday at 06:00

Logs: `~/marketing-cli/audits/_data/launchd.{stdout,stderr}.log`

### Test the scheduled job immediately (without waiting for Sunday)

```bash
launchctl start com.dustin.marketing-cli.biweekly-audit
```

### Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.dustin.marketing-cli.biweekly-audit.plist
rm ~/Library/LaunchAgents/com.dustin.marketing-cli.biweekly-audit.plist
```

### What's in the report

For each platform:

| Section | Tells you |
|---|---|
| Google Ads — Campaigns | Spend / conv / CPA totals + delta vs last audit |
| Google Ads — Search Terms | **NEW search terms** since last audit (negative-keyword candidates) |
| GA4 — Events | Top 10 event volumes |
| GA4 — Landing Pages | Top 10 LPs by sessions + bounce rate |
| Search Console — Queries | Total clicks/impressions + **new + dropped queries** |
| Search Console — Pages | Top 10 pages by impressions |
| Meta — Campaigns | Active campaign spend / leads / CPC |
| Meta — Pixel Events | Top events |
| YouTube — Videos | Top 5 by views |
| Maps — <Your City> Competitors | Ranked competitor GBP review counts + new/gone entrants |

The diff sections (NEW search terms, NEW queries, NEW competitors on map) are the most
actionable — they surface drift you'd otherwise miss.

### Bi-weekly vs weekly

The plist is currently set to fire **weekly** (Sunday 06:00). Bi-weekly throttling
isn't natively supported by launchd. Options:

1. **Leave it weekly** — weekly drift detection is arguably MORE useful than bi-weekly
2. **Monthly** — change the plist `Weekday=0` to `Day=1` (1st of every month)
3. **True bi-weekly** — add a date check at the top of `run_audit()` that skips if
   the last report file is < 13 days old
