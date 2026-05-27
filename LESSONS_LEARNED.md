# Lessons Learned — patterns and gotchas from real Claude-Salesforce work

These are the rules that emerged over 6+ months of building Salesforce + marketing automation with Claude Code. Each one is here because skipping it cost time. Generalized so they apply to any org, not just the one this repo came from.

---

## Salesforce hygiene

### Retrieve before deploy — every time

Local files drift from the org within hours. Other admins make declarative changes in Setup. Parallel Claude sessions deploy on top of each other. A flow you "last edited" in your local repo may be missing five fields a coworker added yesterday.

**The rule**: before deploying any flow, permission set, profile, dashboard, custom object, or Apex class, run `sf project retrieve` for that component first. Diff the live version against your local copy. Only deploy after the diff looks right.

This is the most-violated rule and the one with the highest cost when violated. A bad permset deploy stripped two `classAccesses` an admin needed and broke a Lightning Web Component for an hour — recovery required pulling the prior version from version control.

### Sandbox or scratch org first

Set the default target to a non-prod org: `sf config set target-org=mysandbox`. Watch Claude work for at least a week before pointing it at production. The first time Claude deploys to prod, do it as a single small change you've already validated in sandbox.

### Auto-layout flows only

Never use free-form canvas flows. Set `<canvasMode>AUTO_LAYOUT_CANVAS</canvasMode>` in the flow meta. When you touch an existing free-form flow, convert it to auto-layout as part of the change. Mixed layouts in the same org create rendering bugs that waste hours.

### "Don't change anything" means describe-only

When you tell Claude to investigate, audit, plan, or describe — Claude should stay read-only until you explicitly approve. Follow-up clarifying questions from you are NOT approval to start editing. End describe-only responses with "Ready to implement when you give the word."

This rule exists because Claude is biased toward action. Without it, you'll find yourself reverting unsolicited edits.

---

## Permissions and access

### Always ask who needs access after a deploy

After deploying anything access-controlled — new Apex class, new field, new object, new permission set, new LWC — ask which users, profiles, or permsets need access. Missing permissions are the #1 silent failure after a Salesforce deploy. Catching it at deploy time saves the inevitable "why doesn't this work" debug session an hour later.

### The Automated Process user can't hold External Credential + page-access permsets together

Platform Event triggers, queueables called from PE, `@future` methods, and batch jobs invoked from PE all run as the Automated Process user. That user CAN'T be assigned a permission set that grants both `externalCredentialPrincipalAccesses` AND `pageAccesses` — the license rejects it.

Design around it from day one. If you need to make a callout from a PE-triggered flow, the PE trigger should stamp state only. A user-context schedulable polls and dispatches the actual callout queueable.

The lesson learned the hard way: an automated chain that never completed in production until a Plan B retrofit replaced the PE-direct callout with the schedulable pattern.

### Profile / permset deploys clobber

Same retrieve-before-deploy rule, with an extra twist: profiles and permsets accumulate access grants from many sources. Your local copy will be missing entries that exist live. Always retrieve live, diff vs local, merge missing entries, then deploy.

---

## Async patterns

### AsyncAfterCommit flows race on shared Create events

Two record-triggered flows both using `runAsyncAfterCommit` on the same Create event will race. If flow B reads a field that flow A writes, flow B may read the pre-A value and produce wrong output.

The fix: put flow B on a delayed scheduled path (e.g., +2 min) with a fresh `recordLookup` instead of relying on `$Record`. The delay lets flow A's write commit before flow B reads.

### HighVolume PE publishers must guard `Test.isRunningTest()`

Test-context publishes of Platform Events leak to production flow subscribers. Real Slack messages get sent. Dead URLs get pinged with rolled-back record IDs. Always early-return in the publisher unless a test explicitly asserts delivery:

```apex
if (Test.isRunningTest()) { return; }
```

---

## Parallel work

### Detect parallel sessions before you commit

Before writing or committing in any repo, run:

```bash
git status
git worktree list
git stash list
git fetch && git log --oneline @{u}..HEAD
git branch -vv
```

This detects work from other Claude sessions (especially worktrees) that your current session can't see. The 30 seconds it takes is much cheaper than rebasing on top of a parallel session's deploy.

### Multiple chats edit the same org daily — don't trust local

Multiple Claude sessions can edit the same Salesforce org in the same day. Local SFDX repos go stale within hours. Treat the local repo as a snapshot, not a source of truth. Retrieve every metadata file before referencing or editing it.

---

## Auditing with Claude

### Demand asset-level depth, not just structural config

When asking Claude to audit anything — a Google Ads account, a GA4 setup, a marketing site, a Salesforce flow — be explicit about depth. The default response is structural-config-only ("conversion tracking is set up," "campaigns have negatives"). What you want is asset-level findings ("Ad #3 has 4/10 ad strength because headline 7 is duplicated," "the Brand campaign has zero exact-match keywords").

Phrase it: "Audit at the asset level. For Google Ads, check ad strength + creative quality per campaign. For GA4, check enhanced conversions + event taxonomy. For the site, check schema + form validation. Use the APIs directly, not shell tools."

If Claude returns shallow findings, push back: "go deeper, asset-by-asset, not structural-only." The depth difference between the first answer and the third is usually 10x.

### Verify before recommending from memory

When Claude recalls something from memory — "we have a flow called X" — that's a claim that was true when the memory was written. Verify before acting on it: check that the file exists, grep for the function name, read the current code. Memory snapshots go stale fast.

---

## Working with PDFs and documents

### Claude vision is the magic primitive

The single highest-leverage pattern: feed PDFs to Claude's vision API and get structured JSON out. HUD statements, contractor invoices, inspection reports, receipts, ALTA settlement statements — all become structured data.

The recipe: Apex callout (or Python script) → PDF bytes → Claude `messages` endpoint → JSON schema enforced via the system prompt → write to Salesforce / QuickBooks.

One Named Credential serves all parsers in an org. Define a clear output schema in the system prompt; Claude is very good at extracting to a fixed schema and very bad at extracting to "whatever you can find."

### Keep parser per-PDF caps

Heap limits matter. Cap individual PDFs at ~8MB and log + skip anything larger. A retry queue can pick those up via a different mechanism.

---

## Prompting patterns that work

### Plan, then implement

For non-trivial changes, ask Claude to plan first, then implement only after you approve the plan. The `/plan` command (or just "make a plan, don't write code yet") catches misunderstandings before they become wrong code.

### Save preferences as memory, not in every prompt

If you find yourself typing the same instruction every session ("use auto-layout," "don't deploy without retrieving first," "ask about access at the end"), save it as a feedback memory. The auto-memory system loads it into every future session in that directory automatically.

### Be explicit about scope when you mean it

"Don't refactor while you're in there" and "don't add error handling I didn't ask for" are valid instructions Claude will follow. Without them, Claude trends toward larger PRs. Scope discipline is yours to set.

### When in doubt, ask Claude to ask you

If you're not sure how to frame a request, end with: "Ask me clarifying questions before you start." This is especially useful for ambiguous business logic where wrong assumptions cost more than the clarification round-trip.
