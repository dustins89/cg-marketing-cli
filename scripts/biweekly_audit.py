"""Bi-weekly deep-dive audit across all marketing CLIs.

Pulls fresh data from each platform, diffs against the previous audit run,
writes a dated markdown report to ~/marketing-cli/audits/, and optionally
emails the report via SMTP.

Run manually:
    cd ~/marketing-cli && source .venv/bin/activate
    python3 scripts/biweekly_audit.py [--email] [--no-pull]

Scheduled via launchd — see scripts/com.dustin.marketing-cli.biweekly-audit.plist
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import subprocess
import sys
import traceback
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import yaml

REPO = Path(os.environ.get("MARKETING_CLI_DIR", "/Users/dustinsinger/marketing-cli"))
SF_REPO = Path(os.environ.get("SF_REPO_DIR", "/Users/dustinsinger/leadConvertWrapper"))
SF_TARGET_ORG = os.environ.get("SF_TARGET_ORG", "mydevorg")
AUDITS_DIR = REPO / "audits"
DATA_DIR = AUDITS_DIR / "_data"
YAML_PATH = REPO / "google-ads.yaml"

TODAY = date.today().isoformat()


def load_cfg() -> dict:
    return yaml.safe_load(YAML_PATH.read_text())


def run_cli(cmd: list[str], output_path: Path, timeout: int = 120) -> tuple[bool, str]:
    """Run a CLI command and capture JSON output to a file. Returns (ok, err_msg)."""
    try:
        proc = subprocess.run(
            cmd, cwd=REPO, timeout=timeout,
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return False, f"exit {proc.returncode}: {proc.stderr.strip()[:300]}"
        # Find JSON in output (skip warnings + progress lines)
        out = proc.stdout
        for marker in ("[\n", "[", "{\n", "{"):
            idx = out.find(marker)
            if idx >= 0:
                output_path.write_text(out[idx:])
                return True, ""
        output_path.write_text(out)
        return True, ""
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout}s"
    except Exception as e:
        return False, str(e)[:300]


def run_sf_query(soql: str, output_path: Path, timeout: int = 180) -> tuple[bool, str]:
    """Run a SOQL query via sf CLI, save records to JSON. Returns (ok, err_msg)."""
    cmd = ["sf", "data", "query", "--target-org", SF_TARGET_ORG, "--query", soql, "--json"]
    try:
        proc = subprocess.run(cmd, cwd=SF_REPO, timeout=timeout, capture_output=True, text=True)
        if proc.returncode != 0:
            return False, f"exit {proc.returncode}: {proc.stderr.strip()[:300]}"
        # sf CLI emits warnings on stderr but JSON on stdout; pick stdout
        out = proc.stdout
        idx = out.find("{")
        if idx < 0:
            return False, f"no JSON in output: {out[:200]}"
        data = json.loads(out[idx:])
        records = data.get("result", {}).get("records", [])
        # Strip attributes for cleaner storage
        for r in records:
            r.pop("attributes", None)
        output_path.write_text(json.dumps(records, indent=2, default=str))
        return True, ""
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout}s"
    except Exception as e:
        return False, str(e)[:300]


def diff_rows(prev: list[dict], curr: list[dict], key: str) -> dict:
    """Return {'added': [...], 'removed': [...], 'unchanged_count': N} keyed on `key`."""
    if not isinstance(prev, list) or not isinstance(curr, list):
        return {"added": [], "removed": [], "unchanged_count": 0}
    pkeys = {str(r.get(key)): r for r in prev if isinstance(r, dict)}
    ckeys = {str(r.get(key)): r for r in curr if isinstance(r, dict)}
    return {
        "added": [ckeys[k] for k in ckeys.keys() - pkeys.keys()],
        "removed": [pkeys[k] for k in pkeys.keys() - ckeys.keys()],
        "unchanged_count": len(ckeys.keys() & pkeys.keys()),
    }


def safe_load_json(path: Path) -> list | dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


# === Pull definitions ===
# Each entry: (slug, cli_command, json_filename, post_process_fn_name_or_None)

PULLS = [
    ("gads_campaigns",    ["gads", "pull", "campaigns", "--days", "14", "--format", "json"], "gads_campaigns.json", "summarize_gads_campaigns"),
    ("gads_search_terms", ["gads", "pull", "search-terms", "--days", "14", "--format", "json"], "gads_search_terms.json", "summarize_gads_search_terms"),
    ("gads_ad_strength",  ["gads", "pull", "ads", "--format", "json"], "gads_ad_strength.json", "summarize_gads_ad_strength"),
    ("ga4_events",        ["ga4", "pull", "events", "--days", "14", "--limit", "50", "--format", "json"], "ga4_events.json", "summarize_ga4_events"),
    ("ga4_landing",       ["ga4", "pull", "landing-pages", "--days", "14", "--limit", "30", "--format", "json"], "ga4_landing.json", "summarize_ga4_landing"),
    ("sc_queries",        ["sc", "pull", "queries", "--days", "14", "--limit", "100", "--format", "json"], "sc_queries.json", "summarize_sc_queries"),
    ("sc_pages",          ["sc", "pull", "pages", "--days", "14", "--limit", "50", "--format", "json"], "sc_pages.json", "summarize_sc_pages"),
    ("fb_campaigns",      ["fb", "pull", "campaigns", "--days", "14", "--format", "json"], "fb_campaigns.json", "summarize_fb_campaigns"),
    ("fb_pixel_events",   ["fb", "pull", "pixel-events", "--days", "14", "--format", "json"], "fb_pixel.json", "summarize_fb_pixel"),
    ("yt_videos",         ["yt", "pull", "videos", "--limit", "30", "--format", "json"], "yt_videos.json", "summarize_yt_videos"),
    ("maps_competitors",  ["maps", "search", "we buy houses <your-city>", "--lat", "0.0", "--lng", "0.0", "--radius-km", "30", "--limit", "20", "--format", "json"], "maps_competitors.json", "summarize_maps_competitors"),
    ("cegg_snapshots",    ["cegg", "pull", "snapshots", "--format", "json"], "cegg_snapshots.json", "summarize_cegg_snapshots"),
]

# Salesforce SOQL queries — use run_sf_query() instead of run_cli()
SF_QUERIES = [
    ("sf_marketing_kpi", """
        SELECT Lead_Source__c, Month__c, Monthly_Spend__c, Gross_Leads__c,
               Qualified_Leads__c, Contracts_Signed__c, Closed_Deals__c,
               Projected_Total_Revenue__c, Closed_Total_Profit__c,
               Actual_ROAS__c, Projected_ROAS__c,
               Cost_Per_Gross_Lead__c, Cost_Per_Qualified_Lead__c,
               Cost_Per_Contract__c, Cost_Per_Closed_Deal__c
        FROM Marketing_KPI_Line_Items__c
        WHERE Monthly_Spend__c != null
        ORDER BY Monthly_Spend__c DESC NULLS LAST
        LIMIT 50
    """, "sf_marketing_kpi.json", "summarize_sf_marketing_kpi"),
    ("sf_source_audit", """
        SELECT LeadSource, How_Did_You_Hear_About_Us__c, COUNT(Id) lead_count
        FROM Lead
        WHERE CreatedDate = LAST_N_DAYS:14
        GROUP BY LeadSource, How_Did_You_Hear_About_Us__c
        ORDER BY COUNT(Id) DESC
    """, "sf_source_audit.json", "summarize_sf_source_audit"),
]


# === Per-platform summarizers — return markdown sections ===

def summarize_gads_campaigns(curr, prev) -> str:
    if not curr: return "_(no data)_"
    lines = [f"**{len(curr)} campaigns pulled.**", ""]
    total_spend = sum(c.get("cost", 0) for c in curr if isinstance(c, dict))
    total_conv = sum(c.get("conversions", 0) for c in curr if isinstance(c, dict))
    cpa = total_spend / total_conv if total_conv else 0
    lines.append(f"- Total spend (14d): **${total_spend:,.0f}**")
    lines.append(f"- Total conversions: **{total_conv:.0f}**")
    lines.append(f"- Gross CPA: **${cpa:,.0f}**")
    if prev:
        prev_spend = sum(c.get("cost", 0) for c in prev if isinstance(c, dict))
        prev_conv = sum(c.get("conversions", 0) for c in prev if isinstance(c, dict))
        ds = total_spend - prev_spend
        dc = total_conv - prev_conv
        lines.append(f"- Δ vs last audit: spend **{ds:+,.0f}** ({ds/max(prev_spend,1)*100:+.1f}%), conv **{dc:+.0f}**")
    return "\n".join(lines)


def summarize_gads_search_terms(curr, prev) -> str:
    if not curr: return "_(no data)_"
    lines = [f"**{len(curr)} search terms pulled (14d).**"]
    diff = diff_rows(prev or [], curr, "search_term")
    if diff["added"]:
        lines.append(f"\n🆕 **{len(diff['added'])} NEW search terms since last audit** (review for negative-keyword candidates):")
        new_with_spend = sorted([t for t in diff["added"] if t.get("cost", 0) > 0], key=lambda x: -x.get("cost", 0))[:10]
        for t in new_with_spend:
            text = t.get("search_term", "?")
            cost = t.get("cost", 0)
            conv = t.get("conversions", 0)
            lines.append(f"  - `{text[:60]}` — spent ${cost:.0f}, conv {conv:.0f}")
    return "\n".join(lines)


def summarize_ga4_events(curr, prev) -> str:
    if not curr: return "_(no data)_"
    rows = [r for r in curr if isinstance(r, dict)]
    lines = [f"**Top events (14d):**"]
    for r in sorted(rows, key=lambda x: -x.get("eventCount", 0))[:10]:
        lines.append(f"  - {r.get('eventName','?')}: {r.get('eventCount',0):,}")
    return "\n".join(lines)


def summarize_ga4_landing(curr, prev) -> str:
    if not curr: return "_(no data)_"
    rows = [r for r in curr if isinstance(r, dict)]
    total_sess = sum(r.get("sessions", 0) for r in rows)
    lines = [f"**Top landing pages (14d) — {total_sess:,} total sessions:**"]
    for r in sorted(rows, key=lambda x: -x.get("sessions", 0))[:10]:
        lp = (r.get("landingPage", "?") or "")[:60]
        sess = r.get("sessions", 0)
        br = r.get("bounceRate", 0) * 100 if r.get("bounceRate") else 0
        lines.append(f"  - {lp:60}  sessions={sess:5}  bounce={br:.0f}%")
    return "\n".join(lines)


def summarize_sc_queries(curr, prev) -> str:
    if not curr: return "_(no data)_"
    rows = [r for r in curr if isinstance(r, dict)]
    diff = diff_rows(prev or [], curr, "query")
    lines = [f"**{len(rows)} queries pulled (14d).**"]
    lines.append(f"- Total clicks: {sum(r.get('clicks',0) for r in rows):,}")
    lines.append(f"- Total impressions: {sum(r.get('impressions',0) for r in rows):,}")
    if diff["added"]:
        lines.append(f"\n🆕 **{len(diff['added'])} new queries appeared since last audit:**")
        for q in sorted(diff["added"], key=lambda x: -x.get("impressions", 0))[:8]:
            lines.append(f"  - `{q.get('query','?')[:50]}`  impr={q.get('impressions',0):,}  pos={q.get('position',0):.1f}")
    if diff["removed"]:
        lines.append(f"\n⚠️ **{len(diff['removed'])} queries no longer appearing** (top 5 by previous impressions):")
        for q in sorted(diff["removed"], key=lambda x: -x.get("impressions", 0))[:5]:
            lines.append(f"  - `{q.get('query','?')[:50]}`  was impr={q.get('impressions',0):,}")
    return "\n".join(lines)


def summarize_sc_pages(curr, prev) -> str:
    if not curr: return "_(no data)_"
    rows = [r for r in curr if isinstance(r, dict)]
    lines = [f"**Top pages by impressions (14d):**"]
    for r in sorted(rows, key=lambda x: -x.get("impressions", 0))[:10]:
        page = (r.get("page", "?") or "").replace("https://www.your-domain.com", "")[:50]
        impr = r.get("impressions", 0)
        clicks = r.get("clicks", 0)
        ctr = r.get("ctr", 0) * 100 if r.get("ctr") else 0
        pos = r.get("position", 0)
        lines.append(f"  - {page:50}  impr={impr:5}  clicks={clicks:3}  CTR={ctr:.2f}%  pos={pos:.1f}")
    return "\n".join(lines)


def summarize_fb_campaigns(curr, prev) -> str:
    if not curr: return "_(no data)_"
    rows = [r for r in curr if isinstance(r, dict)]
    if not rows: return "_(no active campaigns)_"
    lines = [f"**{len(rows)} active Meta campaigns (14d):**"]
    for r in rows:
        spend = r.get("spend_usd", 0)
        leads = r.get("leads", 0)
        clicks = r.get("clicks", 0)
        cpc = r.get("cpc", 0)
        lines.append(f"  - {r.get('name','?')[:40]}  spend=${spend:.0f}  clicks={clicks}  leads={leads}  CPC=${cpc:.2f}")
    return "\n".join(lines)


def summarize_fb_pixel(curr, prev) -> str:
    if not curr: return "_(no data)_"
    # fb pixel response shape varies — handle gracefully
    if isinstance(curr, list):
        lines = [f"**Pixel events (14d, top by count):**"]
        rows = [r for r in curr if isinstance(r, dict)]
        for r in sorted(rows, key=lambda x: -x.get("count", 0))[:10]:
            lines.append(f"  - {r.get('event_name','?')}: {r.get('count',0):,}")
        return "\n".join(lines)
    return "_(unexpected shape — check raw json)_"


def summarize_yt_videos(curr, prev) -> str:
    if not curr: return "_(no data)_"
    rows = [r for r in curr if isinstance(r, dict)]
    lines = [f"**{len(rows)} videos on DBH channel:**"]
    top = sorted(rows, key=lambda x: -x.get("views", 0))[:5]
    for v in top:
        lines.append(f"  - {(v.get('title','?'))[:50]:50}  views={v.get('views',0):,}  likes={v.get('likes',0)}")
    return "\n".join(lines)


def summarize_gads_ad_strength(curr, prev) -> str:
    """Ad-strength + asset-count audit. Flags POOR ads + identical A/B variants."""
    if not curr: return "_(no data)_"
    rows = [r for r in curr if isinstance(r, dict)]
    if not rows: return "_(no ads)_"

    from collections import Counter, defaultdict
    by_strength = Counter(r.get("ad_strength", "UNKNOWN") for r in rows)
    lines = [f"**{len(rows)} ads total. Strength distribution:**"]
    for s in ("EXCELLENT", "GOOD", "AVERAGE", "POOR", "PENDING", "NO_ADS", "UNKNOWN"):
        if s in by_strength:
            lines.append(f"  - {s}: {by_strength[s]}")

    # Flag POOR ads
    poor = [r for r in rows if r.get("ad_strength") == "POOR"]
    if poor:
        lines.append(f"\n🚨 **{len(poor)} POOR-strength ads** (need urgent rewrites):")
        for r in poor[:10]:
            lines.append(f"  - #{r.get('id')} in {r.get('campaign','?')}/{r.get('ad_group','?')[:25]}  url={r.get('final_url','?')[:40]}")

    # Flag ad groups where all enabled ads have same strength (no real A/B)
    by_ag = defaultdict(list)
    for r in rows:
        by_ag[(r.get('campaign'), r.get('ad_group'))].append(r)
    no_real_test = []
    for (camp, ag), ads in by_ag.items():
        strengths = {a.get('ad_strength') for a in ads}
        if len(ads) > 1 and len(strengths) == 1:
            no_real_test.append((camp, ag, ads[0].get('ad_strength')))
    if no_real_test:
        lines.append(f"\n⚠️ **{len(no_real_test)} ad groups with no strength variance** (all variants same rating — not really A/B testing):")
        for camp, ag, s in no_real_test[:10]:
            lines.append(f"  - {camp}/{ag}: all rated {s}")

    return "\n".join(lines)


def summarize_cegg_snapshots(curr, prev) -> str:
    if not curr: return "_(no data)_"
    rows = [r for r in curr if isinstance(r, dict)]
    if not rows: return "_(no snapshots)_"
    from collections import Counter
    statuses = Counter((r.get("status") or "unknown").lower() for r in rows)
    lines = [f"**{len(rows)} Crazy Egg snapshots total.**", ""]
    lines.append("Status counts:")
    for status, cnt in statuses.most_common():
        lines.append(f"  - {status}: {cnt}")
    # Highlight active ones (those collecting data)
    active = [r for r in rows if (r.get("status") or "").lower() == "active"]
    if active:
        lines.append("")
        lines.append(f"**{len(active)} active heatmaps currently collecting data:**")
        for s in active[:10]:
            name = (s.get("name") or "?")[:50]
            url = (s.get("url") or s.get("page_url") or "")[:60]
            visits = s.get("visits") or s.get("snapshot_visits") or 0
            lines.append(f"  - {name}  →  {url}  visits={visits}")
    return "\n".join(lines)


def summarize_sf_marketing_kpi(curr, prev) -> str:
    if not curr: return "_(no data)_"
    rows = [r for r in curr if isinstance(r, dict)]
    if not rows: return "_(no spend rows)_"

    lines = ["**Marketing KPI Line Items — top by monthly spend:**", ""]
    lines.append("| Channel | Month | Spend | Gross Leads | Qual Leads | Contracts | Closed | Actual ROAS | Cost/Lead | Cost/Deal |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows[:20]:
        ch = r.get("Lead_Source__c", "—")
        mo = r.get("Month__c", "—")
        spend = r.get("Monthly_Spend__c") or 0
        gross = r.get("Gross_Leads__c") or 0
        qual = r.get("Qualified_Leads__c") or 0
        contracts = r.get("Contracts_Signed__c") or 0
        closed = r.get("Closed_Deals__c") or 0
        roas = r.get("Actual_ROAS__c") or 0
        cpl = r.get("Cost_Per_Gross_Lead__c") or 0
        cpd = r.get("Cost_Per_Closed_Deal__c") or 0
        lines.append(f"| {ch} | {mo} | ${spend:,.0f} | {gross:.0f} | {qual:.0f} | {contracts:.0f} | {closed:.0f} | {roas:.2f}x | ${cpl:.0f} | ${cpd:,.0f} |")

    # Totals
    total_spend = sum((r.get("Monthly_Spend__c") or 0) for r in rows)
    total_closed = sum((r.get("Closed_Deals__c") or 0) for r in rows)
    total_revenue = sum((r.get("Closed_Total_Profit__c") or 0) for r in rows)
    overall_roas = (total_revenue / total_spend) if total_spend else 0
    lines.append("")
    lines.append(f"**Totals across rows:** spend ${total_spend:,.0f} · closed deals {total_closed:.0f} · profit ${total_revenue:,.0f} · blended ROAS {overall_roas:.2f}×")
    return "\n".join(lines)


def summarize_sf_source_audit(curr, prev) -> str:
    """Compare LeadSource (system) vs How_Did_You_Hear_About_Us__c (self-reported)."""
    if not curr: return "_(no data)_"
    rows = [r for r in curr if isinstance(r, dict)]
    if not rows: return "_(no leads in last 14d)_"

    # Build attribution mismatch matrix
    total_leads = sum(r.get("lead_count", 0) for r in rows)
    matched = 0
    mismatch_pairs = []  # (LeadSource, HowHeard, count) where the two differ
    null_self = 0  # how many leads have no "how did you hear" response
    null_system = 0

    for r in rows:
        ls = r.get("LeadSource") or "(null)"
        hh = r.get("How_Did_You_Hear_About_Us__c") or "(null)"
        cnt = r.get("lead_count", 0)
        if hh == "(null)":
            null_self += cnt
        if ls == "(null)":
            null_system += cnt
        if ls != "(null)" and hh != "(null)":
            # Heuristic match: case-insensitive substring overlap
            if ls.lower() in hh.lower() or hh.lower() in ls.lower():
                matched += cnt
            else:
                mismatch_pairs.append((ls, hh, cnt))

    lines = [
        f"**Lead source attribution audit (last 14d, {total_leads:,} leads):**",
        f"- Matched (LeadSource roughly aligns with self-reported): **{matched:,}** ({matched/max(total_leads,1)*100:.1f}%)",
        f"- Mismatched system vs self-report: **{sum(c for _,_,c in mismatch_pairs):,}**",
        f"- No self-report value ('How Did You Hear About Us?' blank): **{null_self:,}** ({null_self/max(total_leads,1)*100:.1f}%)",
        f"- No LeadSource set: **{null_system:,}**",
        "",
        "### Top attribution mismatches (system says X, lead said Y)",
        "",
        "| LeadSource (system) | How Did You Hear (self) | Count |",
        "|---|---|---|",
    ]
    for ls, hh, cnt in sorted(mismatch_pairs, key=lambda x: -x[2])[:15]:
        lines.append(f"| {ls} | {hh} | {cnt} |")
    if not mismatch_pairs:
        lines.append("| _(none — attribution is consistent across all leads)_ | | |")

    lines.extend(["",
        "### Full LeadSource × HowHeard breakdown (all rows)",
        "",
        "| LeadSource | How Did You Hear | Count |",
        "|---|---|---|",
    ])
    for r in sorted(rows, key=lambda x: -x.get("lead_count", 0))[:30]:
        ls = r.get("LeadSource") or "_(null)_"
        hh = r.get("How_Did_You_Hear_About_Us__c") or "_(null)_"
        cnt = r.get("lead_count", 0)
        lines.append(f"| {ls} | {hh} | {cnt} |")

    return "\n".join(lines)


def summarize_maps_competitors(curr, prev) -> str:
    if not curr: return "_(no data)_"
    rows = [r for r in curr if isinstance(r, dict)]
    lines = ["**<Your City> competitor scan — ranked by GBP review count:**", ""]
    lines.append("| Brand | Reviews | Rating | Website |")
    lines.append("|---|---|---|---|")
    for r in sorted(rows, key=lambda x: -(x.get("reviewCount") or 0))[:15]:
        name = (r.get("name") or "")[:30]
        rev = r.get("reviewCount") or 0
        rating = r.get("rating") or 0
        site = (r.get("website") or "—").replace("https://", "").replace("http://", "")[:35]
        marker = " 🏠 **DBH**" if "dustin" in name.lower() else ""
        lines.append(f"| {name}{marker} | {rev} | {rating:.1f}★ | {site} |")
    # Diff for new/missing competitors
    if prev:
        prev_names = {r.get("name") for r in prev if isinstance(r, dict)}
        curr_names = {r.get("name") for r in rows}
        new = curr_names - prev_names
        gone = prev_names - curr_names
        if new:
            lines.append(f"\n🆕 New on the map: {', '.join(n for n in new if n)}")
        if gone:
            lines.append(f"\n⚠️ Gone from the map: {', '.join(n for n in gone if n)}")
    return "\n".join(lines)


# === Main orchestrator ===

def run_audit(pull_data: bool = True) -> Path:
    AUDITS_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    today_data = DATA_DIR / TODAY
    today_data.mkdir(exist_ok=True)

    # Determine previous run for diffs
    prev_dirs = sorted([d for d in DATA_DIR.iterdir() if d.is_dir() and d.name < TODAY])
    prev_dir = prev_dirs[-1] if prev_dirs else None

    findings = {}
    errors = {}

    if pull_data:
        print(f"=== Bi-weekly audit — {TODAY} ===", flush=True)
        for slug, cmd, fname, _ in PULLS:
            print(f"  pulling {slug}...", flush=True)
            out_path = today_data / fname
            ok, err = run_cli(cmd, out_path, timeout=180)
            if not ok:
                errors[slug] = err
                print(f"    ✗ {err}", flush=True)
            else:
                print(f"    ✓ {out_path.stat().st_size:,}b", flush=True)

        # Salesforce SOQL queries (separate handler — uses sf CLI not marketing-cli)
        for slug, soql, fname, _ in SF_QUERIES:
            print(f"  querying SF: {slug}...", flush=True)
            out_path = today_data / fname
            ok, err = run_sf_query(soql, out_path)
            if not ok:
                errors[slug] = err
                print(f"    ✗ {err}", flush=True)
            else:
                print(f"    ✓ {out_path.stat().st_size:,}b", flush=True)

    # Generate report
    print("\nGenerating report...", flush=True)
    report_lines = [
        f"# DBH Marketing Audit — {TODAY}",
        "",
        f"_Bi-weekly automated audit. Diffs computed against previous audit on {prev_dir.name if prev_dir else 'N/A (first run)'}._",
        "",
    ]
    if errors:
        report_lines.append("## ⚠️ Pull errors")
        for slug, err in errors.items():
            report_lines.append(f"- **{slug}**: `{err}`")
        report_lines.append("")

    section_titles = {
        "gads_campaigns":    "## Google Ads — Campaigns",
        "gads_search_terms": "## Google Ads — Search Terms",
        "gads_ad_strength":  "## Google Ads — Ad Strength + Asset Audit",
        "ga4_events":        "## GA4 — Events",
        "ga4_landing":       "## GA4 — Landing Pages",
        "sc_queries":        "## Search Console — Queries",
        "sc_pages":          "## Search Console — Pages",
        "fb_campaigns":      "## Meta — Campaigns",
        "fb_pixel_events":   "## Meta — Pixel Events",
        "yt_videos":         "## YouTube — Videos",
        "maps_competitors":  "## Maps — <Your City> Competitors",
        "cegg_snapshots":    "## Crazy Egg — Heatmap Snapshots",
        "sf_marketing_kpi":  "## Salesforce — Marketing KPI (spend + ROAS + deals)",
        "sf_source_audit":   "## Salesforce — LeadSource vs 'How Did You Hear About Us?' Audit",
    }
    # Combine marketing-cli PULLS + SF_QUERIES for report sections
    all_sources = [(slug, fname, fn) for slug, _, fname, fn in PULLS] + \
                  [(slug, fname, fn) for slug, _, fname, fn in SF_QUERIES]
    for slug, fname, fn_name in all_sources:
        report_lines.append(section_titles.get(slug, f"## {slug}"))
        curr = safe_load_json(today_data / fname)
        prev = safe_load_json(prev_dir / fname) if prev_dir else None
        try:
            if fn_name and curr is not None and globals().get(fn_name):
                section = globals()[fn_name](curr, prev)
            else:
                section = "_(no data pulled)_"
        except Exception as e:
            section = f"_(summarizer error: {e})_\n```\n{traceback.format_exc()[:500]}\n```"
        report_lines.append(section)
        report_lines.append("")

    report_lines.extend([
        "---",
        f"_Generated by `scripts/biweekly_audit.py`. Raw JSON in `audits/_data/{TODAY}/`. Next audit in 14 days._",
    ])

    report_path = AUDITS_DIR / f"{TODAY}_biweekly.md"
    report_path.write_text("\n".join(report_lines))
    print(f"\n✅ Report written: {report_path}", flush=True)
    return report_path


def email_report(report_path: Path, cfg: dict) -> None:
    """Send the markdown report via SMTP. Requires audit_email_* keys in yaml."""
    required = ["audit_email_from", "audit_email_to", "audit_email_smtp_host",
                "audit_email_smtp_user", "audit_email_smtp_password"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        print(f"⏭ Email skipped — missing yaml keys: {missing}", flush=True)
        return

    msg = EmailMessage()
    msg["From"] = cfg["audit_email_from"]
    msg["To"] = cfg["audit_email_to"]
    msg["Subject"] = f"DBH Marketing Audit — {TODAY}"
    msg.set_content(f"Bi-weekly audit report attached.\n\nReport: {report_path}\n\n--- BEGIN REPORT ---\n\n{report_path.read_text()}")

    host = cfg["audit_email_smtp_host"]
    port = cfg.get("audit_email_smtp_port", 587)
    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(cfg["audit_email_smtp_user"], cfg["audit_email_smtp_password"])
        s.send_message(msg)
    print(f"📧 Emailed report to {cfg['audit_email_to']}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", action="store_true", help="Send report via SMTP (requires audit_email_* in yaml)")
    ap.add_argument("--no-pull", action="store_true", help="Skip CLI pulls, regenerate report from cached _data only")
    args = ap.parse_args()

    report_path = run_audit(pull_data=not args.no_pull)

    if args.email:
        try:
            email_report(report_path, load_cfg())
        except Exception as e:
            print(f"⚠️ Email failed: {e}", flush=True)
            sys.exit(2)


if __name__ == "__main__":
    main()
