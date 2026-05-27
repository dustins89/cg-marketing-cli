# Prompting Guide — getting Claude Code to behave

Three prompts. Paste them as your first messages in Claude Code, in this order:

1. **Day-one memory prompt** — sets six guardrail rules that persist across every future session
2. **Salesforce + Claude Code install walkthrough** — for anyone connecting Claude to a Salesforce org
3. **Build your own marketing CLI from scratch** — for anyone forking the structure of this repo to their own stack

---

## 1. Day-one memory prompt

Paste this into Claude Code the first time you open it in any new project directory. It uses the auto-memory system, so the rules persist into every future session in that directory.

```
Save the following as feedback memories so you apply them in every future conversation in this project. Each should be its own memory file with a clear name and a "Why:" / "How to apply:" structure.

1. Always retrieve before deploy. Before any `sf project deploy` of a flow, permission set, profile, dashboard, custom object, or any metadata I already have locally, you must first run `sf project retrieve` for that component, diff the live version against my local copy, and show me the diff. Only deploy after I confirm.
   Why: local files drift from the org within hours — other admins, declarative changes in Setup, parallel Claude sessions. Deploying a stale local file silently overwrites coworkers' work.
   How to apply: applies to every deploy, every time, even if I sound like I'm in a hurry. If I tell you to "just deploy," remind me of this rule once and ask if I want to skip the retrieve for this specific case.

2. Ask explicit permission before any destructive or irreversible operation. Never run, without my typed confirmation in this conversation:
   - `sf project deploy` (any component, any org)
   - `sf project delete` or `--destructive-changes` deploys
   - `sf data delete` or any DML that deletes/updates records
   - `sf apex run` of anonymous Apex that writes data
   - Any deploy that targets a production org (alias contains "prod", or org is not a sandbox/scratch)
   - `git push`, `git reset --hard`, `git push --force`, deleting branches
   Why: these change shared state I can't easily undo. A bad deploy can break flows for the whole team; a bad anonymous Apex run can corrupt records irreversibly.
   How to apply: state exactly what you're about to do, name the target org, and wait for me to type "yes" or equivalent. One-time approval does NOT carry to the next similar action.

3. Production deploys require a second confirmation. If the target org is production, after I approve the deploy you must restate "Deploying to PRODUCTION org <alias>. Confirm again?" and wait for a second yes.
   Why: most accidental prod deploys happen because the wrong default org was set. The second confirmation forces both of us to look at the alias.
   How to apply: any deploy where the target alias is not clearly a sandbox or scratch org gets the double-confirm.

4. Never assume my local file matches the org. When I ask you to modify a flow, permset, profile, Apex class, or any metadata, your first step is to retrieve the live version from the target org and work from that. Do not edit the local file blind.
   Why: I run multiple Claude sessions and have collaborators editing in Setup. Local is a snapshot, not a source of truth.
   How to apply: applies to every modify-existing-metadata request. Greenfield new files are fine to write directly.

5. Ask who needs access after any access-controlled deploy. After deploying anything that involves permissions — new Apex classes, new fields, new objects, new permission sets, new Lightning components — ask me which users, profiles, or permission sets need access before I move on. Don't wait for a user to report being locked out.
   Why: missing permissions are the #1 silent failure after a Salesforce deploy. Catching it at deploy time saves an hour of "why doesn't this work" later.
   How to apply: end every access-controlled deploy summary with the question "Who needs access to this?"

6. "Don't change anything" means describe-only until I explicitly approve. If I tell you to investigate, audit, plan, or describe something without making changes, stay in read-only mode until I give an explicit go-ahead. Follow-up clarifying questions from me are NOT approval to start editing.
   Why: I often want to think through a change before letting code touch the org. Premature edits force me to revert and rebuild context.
   How to apply: when in describe-only mode, end responses with "Ready to implement when you give the word" rather than starting to edit.

Save each of these as a separate file under feedback memory, link them from MEMORY.md, and confirm when done.
```

### What happens after you paste it

Claude writes six files into `~/.claude/projects/<your-project>/memory/` — one per rule — plus a one-line index entry for each in `MEMORY.md`. From then on, every new Claude session in that directory automatically loads `MEMORY.md` and pulls the rules into context.

### Tweaks to consider

- Adjust rule #2's list to match your workflow. If you don't use `sf data delete`, drop it. If you use VS Code's deploy button, add it.
- Rule #3's "production" detection is heuristic. If your prod org alias isn't obviously named, hardcode it: "if target alias is `acme-prod`, double-confirm."
- Add a rule #7 if you work in a team: "Before any deploy, run `git status` and `git stash list` to detect work from other parallel sessions or collaborators." This is the parallel-session-safety rule learned the hard way.
- **Test it.** After Claude saves the memories, open a new session and ask Claude to do a small deploy. If Claude doesn't pause and ask for confirmation, the rules aren't loading — check that `MEMORY.md` has the entries and the files exist.

The rules are only as good as the org hygiene around them. If you start typing "yes" reflexively, the safety net stops working. Read what Claude is about to do every time, not skim it.

---

## 2. Salesforce + Claude Code install walkthrough

The shortest path from "nothing installed" to "Claude can read and write my Salesforce org."

### Install the two CLIs

```bash
# Claude Code
curl -fsSL https://claude.ai/install.sh | bash

# Salesforce CLI
npm install -g @salesforce/cli
```

Or on Mac with Homebrew:

```bash
brew install --cask claude-code
brew install salesforcedx/cli/sf
```

### Authenticate `sf` to your Salesforce org

```bash
sf org login web --alias myorg --set-default
```

A browser pops up, you log in, done. `sf org list` confirms it stuck.

**Tip**: use a sandbox alias on day one — don't point Claude at production until you've watched it work for a week.

### Get an SFDX project on disk

Two options:

- **Existing repo**: `git clone <your-sf-repo>` and `cd` into it.
- **Fresh from org**:
  ```bash
  sf project generate -n myorg-metadata
  cd myorg-metadata
  sf project retrieve start --metadata ApexClass Flow CustomObject
  ```

The folder needs an `sfdx-project.json` for `sf` commands to work cleanly.

### Launch Claude in that directory

```bash
cd ~/myorg-metadata
claude
```

That's it — Claude inherits the authenticated `sf` session, so it can run `sf project retrieve`, `sf project deploy`, `sf data query`, `sf apex run`, etc. on your behalf. First thing to ask it: `run /init` so it writes a `CLAUDE.md` with project context.

### Optional but huge — add the Salesforce MCP

Gives Claude structured tools instead of shelling out to `sf` for everything:

```bash
claude mcp add salesforce -- npx -y @salesforce/mcp --orgs DEFAULT_TARGET_ORG --toolsets all
```

Restart Claude, type `/mcp` to confirm it's connected.

### What to try first

- "Retrieve the Lead object and all its flows, then explain how leads are routed."
- "Run a SOQL query for the 10 most recent Opportunities."
- "Create a new Apex class that does X, deploy it to my scratch org."

The "aha" moment is usually the first one — watching Claude pull metadata and read it back to you in plain English.

### What you need to know before doing real work

Claude amplifies whatever Salesforce skill you have. It doesn't replace the fundamentals. Don't turn Claude loose on a production org until you have:

**Non-negotiable baseline**

1. **Salesforce admin fluency.** You need to know what an object, field, record type, validation rule, flow, permission set, and profile actually are. Claude will produce metadata XML that looks plausible but is subtly wrong — if you can't read a `<field>` block or spot a missing `permissionSet` reference, you'll deploy broken stuff. Trailhead's Admin Beginner + Intermediate trails are the floor.
2. **Sandbox discipline.** Have a dev sandbox or scratch org. Never point Claude at production on day one. Set the sandbox as the default target: `sf config set target-org=mysandbox`.
3. **Git basics.** `status`, `diff`, `commit`, `revert`, `stash`. Claude edits files; git is how you see what changed and roll back when it goes sideways.
4. **SFDX source format.** `force-app/main/default/` mirrors the org's metadata tree — `flows/`, `objects/`, `classes/`, `permissionsets/`. Thirty minutes clicking through an existing SFDX repo on GitHub teaches this.

**Strongly recommended**

5. **Reading metadata XML.** You don't need to write it, but you need to skim a `.flow-meta.xml` or `.permissionset-meta.xml` and tell whether it matches what you asked for.
6. **Apex + SOQL literacy** if you're touching code at all. At minimum: what a trigger is, what `@AuraEnabled` means, what `[SELECT ... FROM Account]` does, what a governor limit is.
7. **The retrieve-before-deploy reflex.** This is the single biggest source of broken deploys. Local files drift from the org constantly. Ask Claude "retrieve this first, then diff against my local, then deploy" every single time.

**Experience that pays off later**

- Build one flow by hand in Flow Builder, end to end.
- Write one Apex class + test by hand, deploy it, fix the inevitable 0% coverage error.
- Break something in a sandbox and roll it back. The lesson "I can recover from this" makes everything downstream less scary.
- Read one painful debug log. When Claude says "the deploy failed," you need to be able to skim the error block.

The ramp is days, not months — but skipping it costs more than it saves.

---

## 3. Build your own marketing CLI from scratch

If you want to fork the architecture of this repo for your own business — different platforms, different focus — paste the following into a fresh Claude Code session in an empty directory. It treats Claude like a 30-minute intake call instead of telling it what to build up front.

```
I want to build a personal marketing CLI in Python that I'll use with you to audit and manage my paid ads, SEO, and analytics across all my marketing platforms. I'm modeling it after a CLI a friend built — the architecture I want is:

- One Python subpackage per platform (Google Ads, GA4, Search Console, Meta, Google Business Profile, CallRail, etc.)
- Each platform has `pull` commands that are read-only and output JSON or Rich tables, and `apply` commands that are mutations gated by per-change y/N/q confirmation plus an `audit.log`
- All credentials live in a single `~/.marketing-cli/credentials.yaml` file (chmod 600, gitignored)
- Python 3.9+ compatible, Rich for terminal tables, Click or Typer for the CLI framework

Before we start writing any code, I want you to:

1. Ask me which marketing platforms I actually use today. We'll only build CLIs for those.
2. For each platform, ask whether I already have API access (developer token, OAuth app, API key) or whether I need to set that up first.
3. Walk me through getting API credentials for the highest-leverage platform, step by step, like I've never done this before. Include screenshots of where to click if you have to describe them in words.
4. Once I have credentials for at least one platform, scaffold the project structure: `pyproject.toml`, the credentials file, a shared `core/` module for auth + audit logging, and the first platform's subpackage with empty `cli.py`, `client.py`, `pull.py`, and `format.py` files.
5. Then implement ONE `pull` command end-to-end so I can see data flowing.

Do NOT make assumptions. Do NOT write code before step 4. Do NOT install anything without telling me what it does. Treat this like a paid intake call where the goal is to understand my actual setup before doing anything.

Also: save the following as feedback memory before we start so it persists into every future session in this project:
"For this project, never write code without my explicit go-ahead. Always describe what you're about to build, list the files that will be touched, and wait for me to type 'yes' before touching the filesystem."
```

### What that prompt gets you

A scaffolded project structure compatible with this repo's patterns — same pull/apply split, same credentials layout, same audit log discipline — but tailored to your platforms. If you later want to copy a specific platform package from this repo into yours, the interfaces will line up.
