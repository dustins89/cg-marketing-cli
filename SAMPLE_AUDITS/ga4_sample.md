# Sample GA4 audit findings

**Redacted excerpt from a real GA4 audit Claude ran on an active property.** Numbers scrubbed; finding structure and fix steps are as produced.

---

## 🚨 Tier 1 — Enhanced Conversions are not configured

GA4 → Admin → Data Streams → Web → Configure tag settings → **"Include user-provided data for conversions"** is OFF.

**Impact**: every form submission ships to GA4 (and downstream to Google Ads via the linked conversion) with no email/phone hash. Match rates on offline-to-online attribution drop by ~30–50%. Smart Bidding loses signal.

**Fix**:
1. Enable user-provided data inclusion in the GA4 tag settings.
2. Confirm your GTM has variables capturing form email + phone (DataLayer variables `user_data.email`, `user_data.phone_number`).
3. Verify in Tag Assistant that hashed email/phone flow on the conversion event.

Without this, Google Ads OCI and Customer Match audiences are operating at half-fidelity.

---

## 🚨 Tier 1 — `purchase` event has no `value` set

Found via `ga4 pull events --days 30`:

| Event | Count | Has `value` | Has `currency` |
|---|---|---|---|
| `page_view` | [high] | n/a | n/a |
| `form_submit` | [med] | n/a | n/a |
| `phone_call` | [low] | n/a | n/a |
| `purchase` | [low] | ❌ NO | ❌ NO |

**Impact**: every `purchase` event reports as $0. ROAS is undefined. Smart Bidding (target_roas, maximize_conversion_value) cannot run. Reports show "0 revenue" everywhere despite real deals closing.

**Fix**: on the source firing `purchase` (Salesforce OCI flow, Shopify, your form thank-you page — wherever), include `value` (the deal amount or expected LTV) and `currency` ("USD") in the event payload. For real-estate offline conversions, ship the contracted purchase price as `value`.

---

## 🟠 Tier 2 — Event taxonomy has 14 events but no Key Events selected

`ga4 pull events --days 30` lists 14 distinct event names. GA4 Admin → Events → Key Events shows ZERO marked.

**Impact**: Key Events are what populates "Conversions" reports. Without any Key Events, the Conversions card on every report is blank. Audiences and exploration reports can't filter "users who converted."

**Fix**: in Admin → Events, mark these as Key Events:
- `form_submit` (lead capture)
- `phone_call` (CallRail integration)
- `schedule` (Calendly booking)
- `purchase` (closed deal — once it has a value)

Anything you'd report on monthly should be marked. Don't mark `page_view` — it's not an outcome.

---

## 🟠 Tier 2 — Channel grouping shows 38% "(Other)" traffic

`ga4 pull channels --days 30` shows the "(Other)" channel taking 38% of sessions. That means the default channel grouping rules don't classify a large chunk of your traffic.

**Cause**: typically (1) UTM tags inconsistent or missing on key campaigns, (2) some referrer domains not in the default referral list, (3) custom channel grouping not configured.

**Fix**:
1. `ga4 pull source-medium --days 30` to see which source/medium combos are landing in "(Other)."
2. Standardize UTM tags on your highest-traffic campaigns (CallRail DNI swap targets, email links, paid social).
3. In Admin → Channel groups → Custom, add rules for the source/medium combos showing up most.

---

## 🟡 Tier 3 — Geo report shows traffic outside your service area

`ga4 pull geo --days 30` shows ~12% of sessions from regions outside your service area.

**Possible causes**: (1) display campaigns geo-targeting too broadly, (2) competitors clicking, (3) referral traffic from out-of-region directories. Cross-reference with `gads pull geo` to isolate whether paid is the source.

If paid is the source, tighten campaign location settings to "Presence" (not "Presence or Interest"), and add negative geos for the worst-performing regions.

---

## How Claude built this

Single prompt: *"Audit my GA4 property using the `ga4` CLI in this repo. Cover events + Key Events config, enhanced conversions, channel grouping fidelity, geo fitness, and the top configuration gaps. Use `ga4 pull` for every claim. Output as Tier 1 / Tier 2 / Tier 3 with one numbered fix per finding."*

Claude pulled `events`, `channels`, `source-medium`, `geo`, `landing-pages`, and `conversions-by-page` over 30-day windows. Total runtime: ~5 minutes.
