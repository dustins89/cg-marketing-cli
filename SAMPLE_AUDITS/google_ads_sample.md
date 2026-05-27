# Sample Google Ads audit findings

**This is a redacted excerpt from a real audit Claude ran on an active Google Ads account.** Dollar figures and campaign IDs are scrubbed; the finding shape and "how to fix" steps are exactly as Claude produced them. Run `gads pull *` against your own account and ask Claude to "audit my Google Ads at the asset level — impression share, ad strength, extension performance" to get the equivalent for your account.

---

## 🚨 Tier 1 — Search Only campaign is losing ~40% of available impressions

| Campaign | Impr 90d | Spend 90d | IS Search | IS Budget Lost | IS Rank Lost |
|---|---|---|---|---|---|
| Search Only | [redacted] | $[redacted] | **60.8%** | **22.6%** | 16.6% |
| Competitor | [redacted] | $[redacted] | 57.7% | 21.6% | 20.7% |

**Interpretation:**
- IS Budget Lost = 22.6% on Search Only — you're missing ~22% of impressions you'd be eligible to buy at your current bids. If you bump budget, you capture more impressions at the same Quality Score. No creative work needed for that subset.
- IS Rank Lost = 16.6% — 17% of available impressions go to higher-bid or higher-QS competitors. Increasing bid OR improving QS fixes this.
- Combined: ~39% lost on Search Only.

**Fix:**
1. **Budget increase test**: if conversion economics hold at current CPL, bump Search Only daily budget by 25% for 14 days. Re-measure IS_budget_lost.
2. **Bid increase test on top keywords**: review the QS=7–8 keywords with reasonable CPA, bump bid 15% to test rank-share recapture.
3. **Watch QS=0–3 keywords**: those drag rank share. Pause or rework them.

Run `gads pull campaigns --days 90 --format table` for your impression-share columns.

---

## 🟠 Tier 1 — Call extension is the single highest-ROI asset; do not pause it

Per-extension performance (90 days, aggregated):

| Extension Type | Impr | Clicks | CTR | Conversions |
|---|---|---|---|---|
| **CALL** | [redacted] | [redacted] | **13.2%** | [highest] |
| SITELINK (4 enabled) | [redacted] | [redacted] | 18.9% | [2nd] |
| IMAGE | [redacted] | [redacted] | 13.6% | [3rd] |
| CALLOUT (3 enabled) | [redacted] | [redacted] | 6.5% | [low] |

**Finding**: phone leads close at much higher rates than web leads in this vertical. The single highest-converting asset is the call extension. Recommendation: never pause it; consider adding call extensions to every search campaign that doesn't have one.

**Callouts underperform** — pick ones that promise action ("Cash Offer in 24h," "No Commissions") not soft brand ("Read Blog").

---

## 🟠 Tier 2 — Hourly breakdown reveals overspend at noon + dead hours 18:00–21:00

Conversion CPA by hour (90d):

| Hour | CPA | Verdict |
|---|---|---|
| 09:00–11:00 | $[low] | ✅ Sweet spot |
| 12:00 | $[2× sweet-spot] | ⚠️ Overspend, low conv rate |
| 14:00–16:00 | $[low] | ✅ Sweet spot |
| 18:00–21:00 | $[3× sweet-spot] | 🔴 Dead hours — pause or bid down |
| 22:00–07:00 | n/a | Outside business hours — already pausing |

**Fix**: ad schedule modifier −50% on 18:00–21:00 weekdays, −20% on 12:00 weekdays. Reallocate the savings to the morning and mid-afternoon sweet spots.

---

## 🟡 Tier 2 — Ad strength is "Average" or worse on 7 of 12 RSAs

`gads pull ad-strength --days 30` reveals:

| Campaign | Ad ID | Ad Strength | Issue |
|---|---|---|---|
| Search Only | [id] | Average | Headline 5 nearly duplicates headline 2 |
| Search Only | [id] | Poor | 0 callout extensions linked |
| Competitor | [id] | Average | All headlines start with brand name (lacks variety) |
| Competitor | [id] | Average | No emotional/benefit headline |

**Fix**: for each "Average" or below, ask Claude: "Generate 5 alternative headlines for this RSA that vary length, lead with benefit, and avoid duplicating headlines I already have. Output as `apply add_ad_headline` actions for the gads CLI." Then `gads apply` interactively to roll them in.

---

## How Claude built this

Single prompt: *"Audit my Google Ads account at the asset level. Cover impression share, ad strength per RSA, extension performance, hourly CPA, geo CPA, and top wasted spend. Pull data with the `gads` CLI — do not estimate. Output as Tier 1 / Tier 2 / Tier 3 findings with a numbered fix for each."*

Claude ran ~20 `gads pull` commands, joined the JSON outputs, and produced this audit. Total runtime: about 8 minutes.
