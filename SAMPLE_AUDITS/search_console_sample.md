# Sample Search Console audit findings

**Redacted excerpt from a real Search Console audit Claude ran on an active property.** Numbers scrubbed; finding structure and fix steps are as produced.

---

## 🚨 Tier 1 — Top 10 queries by impressions include 4 with zero clicks

`sc pull queries --days 90 --limit 50` reveals:

| Query | Impressions | Clicks | CTR | Avg Position |
|---|---|---|---|---|
| `we buy houses [your-city]` | [high] | [med] | 3.2% | 6.4 |
| `cash for houses [your-city]` | [high] | [low] | 1.1% | 8.7 |
| `sell my house fast` | [high] | 0 | 0.0% | 14.2 |
| `[competitor brand name]` | [med] | 0 | 0.0% | 18.1 |
| `[generic intent phrase]` | [med] | 0 | 0.0% | 12.8 |
| `[long-tail variant]` | [med] | 0 | 0.0% | 15.3 |

**Finding**: four queries with significant impression volume but zero clicks. Common cause: Google is showing your page in position 12–18 (page 2). At page-2 positions, CTR is < 1%.

**Fix**:
1. For each zero-click query, `sc pull query-page --query "<the query>" --days 90` to find which page Google is ranking. Then audit that page's title tag and meta description — both must match the query intent better.
2. If no page on your site directly targets the query, create one. Page 2 rankings usually mean Google sees the topic relevance but not the right page authority.
3. For competitor-brand queries you're ranking on, decide: do you want to compete (spend ad $ to capture, write comparison content) or not (these are unlikely to convert).

---

## 🚨 Tier 1 — XX% of pages with impressions are also returning errors in the Coverage report

`sc pull pages --days 30` lists [count] unique URLs with impressions. The GSC Coverage report flags [N] of those with "Submitted URL marked 'noindex'" or "Crawled — currently not indexed."

**Impact**: Google's bot crawled and rejected those pages. They generate impressions (when Google has them indexed from before) but cannot win new positions.

**Fix**:
1. In GSC → Pages → "Why pages aren't indexed," export the list.
2. For each: confirm whether the noindex is intentional (e.g., thank-you pages, internal listings). If yes, those URLs shouldn't be in the sitemap.
3. If the noindex is unintentional (template bug, stale plugin setting), fix the page and request reindexing.

---

## 🟠 Tier 2 — Mobile vs desktop CTR gap is unusually wide

`sc pull devices --days 30`:

| Device | Impressions | Clicks | CTR | Avg Position |
|---|---|---|---|---|
| MOBILE | [high] | [med] | 2.1% | 7.8 |
| DESKTOP | [med] | [med] | 4.3% | 7.5 |
| TABLET | [low] | [low] | 3.8% | 7.6 |

**Finding**: mobile CTR is ~50% of desktop CTR at nearly the same average position. Common causes: (1) the title tag wraps awkwardly on mobile SERPs, (2) below-the-fold competitors look more relevant in the mobile result, (3) above-the-fold local pack pushes organic results down on mobile.

**Fix**:
1. `sc pull query-page --days 30` for the top 10 mobile-heavy queries → manually search them on mobile → screenshot the SERP.
2. Look at what's getting clicked instead. If the local pack is dominating, GBP optimization (GA4 audit handoff covers this) is higher leverage than title-tag tweaks.
3. Shorten title tags > 55 chars where mobile is truncating. Prioritize the most important keyword early in the title.

---

## 🟡 Tier 3 — Page count vs query count ratio suggests thin content

[total query count] unique queries are driving impressions, but only [low] unique landing pages. Ratio is ~[ratio]:1.

**Finding**: many queries → few pages = pages are doing too much work per topic. Google is matching multiple intents to the same page. Symptom of this: bounce rate high on these pages in GA4.

**Fix**: pick the top 5 highest-impression queries that land on the same page. Decide: does each deserve its own page? If yes (different intents), split. If no (same intent, different phrasing), the page is fine; focus on improving its title + intro paragraph to match the dominant query phrasing.

---

## How Claude built this

Single prompt: *"Audit my Search Console performance over the last 90 days using the `sc` CLI. Cover top queries with zero clicks, mobile vs desktop fidelity, page count vs query coverage, and coverage errors. Use `sc pull` for every claim. Output as Tier 1 / Tier 2 / Tier 3 with numbered fixes."*

Claude pulled `queries`, `pages`, `query-page`, `countries`, and `devices` over 30 and 90-day windows. Total runtime: ~4 minutes.
