#!/usr/bin/env python3
"""GTM mutations for the /thank-you/ redirect pattern (user-confirmed 2026-05-16):

Creates in the Default Workspace (id=50):
  1. URL variable: "URL - page" (component=query, key=page)
  2. Trigger "Thank You — Contact Us" — Page View, fires when:
     Page Path = /thank-you/ AND {{URL - page}} = contact-us
  3. Trigger "Thank You — Default Lead" — Page View, fires when:
     Page Path = /thank-you/ AND {{URL - page}} does NOT equal contact-us
     (catches step 2 form + sell-your-house form + any future lead form
      that redirects to /thank-you/ without a page= override)

Re-points existing GA4 event tags:
  4. "GA4 — Step 2 Form Complete" → Thank You — Default Lead
  5. "GA4 — Contact Us Form Complete" → Thank You — Contact Us

Does NOT auto-publish. After running with --apply, user verifies in GTM
Preview Mode + clicks Submit in UI to publish the workspace.
"""
import sys
import yaml
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

APPLY = "--apply" in sys.argv

cfg = yaml.safe_load((Path.home()/'marketing-cli/google-ads.yaml').read_text())
creds = Credentials(
    token=None, refresh_token=cfg['refresh_token'],
    client_id=cfg['client_id'], client_secret=cfg['client_secret'],
    token_uri='https://oauth2.googleapis.com/token',
)
svc = build('tagmanager', 'v2', credentials=creds, cache_discovery=False)
ACCT = cfg['gtm_account_id']
CONT = cfg['gtm_container_id']
WS = '50'  # Default Workspace

ws_path = f'accounts/{ACCT}/containers/{CONT}/workspaces/{WS}'
print(f'Workspace: {ws_path}  Mode: {"APPLY" if APPLY else "DRY-RUN"}', file=sys.stderr)


def list_things(kind):
    """kind in ('variables', 'triggers', 'tags')"""
    resource = getattr(svc.accounts().containers().workspaces(), kind)()
    res = resource.list(parent=ws_path).execute()
    return res.get(kind[:-1], [])  # singular key


# ============ 1. URL variable "URL - page" ============
print('\n--- [1/5] URL variable "URL - page" ---', file=sys.stderr)
existing_vars = list_things('variables')
existing_var = next((v for v in existing_vars if v['name'] == 'URL - page'), None)
if existing_var:
    print(f'  [SKIP] Variable "URL - page" already exists: id={existing_var["variableId"]}', file=sys.stderr)
    var_id = existing_var['variableId']
else:
    var_body = {
        'name': 'URL - page',
        'type': 'u',  # URL variable type
        'parameter': [
            {'type': 'template', 'key': 'component', 'value': 'QUERY'},
            {'type': 'template', 'key': 'queryKey', 'value': 'page'},
        ],
    }
    if APPLY:
        created = svc.accounts().containers().workspaces().variables().create(
            parent=ws_path, body=var_body).execute()
        var_id = created['variableId']
        print(f'  [CREATED] Variable id={var_id} name={created["name"]}', file=sys.stderr)
    else:
        print(f'  DRY-RUN: would create variable "URL - page" (component=QUERY, queryKey=page)', file=sys.stderr)
        var_id = '(dry-run)'


# ============ 2. Trigger "Thank You — Contact Us" ============
print('\n--- [2/5] Trigger "Thank You — Contact Us" ---', file=sys.stderr)
existing_triggers = list_things('triggers')
trigger_a = next((t for t in existing_triggers if t['name'] == 'Thank You — Contact Us'), None)
if trigger_a:
    print(f'  [SKIP] Trigger already exists: id={trigger_a["triggerId"]}', file=sys.stderr)
    trigger_a_id = trigger_a['triggerId']
else:
    body_a = {
        'name': 'Thank You — Contact Us',
        'type': 'pageview',
        'filter': [
            {
                'type': 'equals',
                'parameter': [
                    {'type': 'template', 'key': 'arg0', 'value': '{{Page Path}}'},
                    {'type': 'template', 'key': 'arg1', 'value': '/thank-you/'},
                ],
            },
            {
                'type': 'equals',
                'parameter': [
                    {'type': 'template', 'key': 'arg0', 'value': '{{URL - page}}'},
                    {'type': 'template', 'key': 'arg1', 'value': 'contact-us'},
                ],
            },
        ],
    }
    if APPLY:
        created = svc.accounts().containers().workspaces().triggers().create(
            parent=ws_path, body=body_a).execute()
        trigger_a_id = created['triggerId']
        print(f'  [CREATED] Trigger id={trigger_a_id} name={created["name"]}', file=sys.stderr)
    else:
        print(f'  DRY-RUN: would create pageview trigger w/ 2 AND filters', file=sys.stderr)
        trigger_a_id = '(dry-run-A)'


# ============ 3. Trigger "Thank You — Default Lead" ============
print('\n--- [3/5] Trigger "Thank You — Default Lead" ---', file=sys.stderr)
trigger_b = next((t for t in existing_triggers if t['name'] == 'Thank You — Default Lead'), None)
if trigger_b:
    print(f'  [SKIP] Trigger already exists: id={trigger_b["triggerId"]}', file=sys.stderr)
    trigger_b_id = trigger_b['triggerId']
else:
    body_b = {
        'name': 'Thank You — Default Lead',
        'type': 'pageview',
        'filter': [
            {
                'type': 'equals',
                'parameter': [
                    {'type': 'template', 'key': 'arg0', 'value': '{{Page Path}}'},
                    {'type': 'template', 'key': 'arg1', 'value': '/thank-you/'},
                ],
            },
            {
                # NOT equal contact-us — catches everything else (step 2, sell, etc.)
                'type': 'equals',
                'parameter': [
                    {'type': 'template', 'key': 'arg0', 'value': '{{URL - page}}'},
                    {'type': 'template', 'key': 'arg1', 'value': 'contact-us'},
                ],
                'negate': True,
            },
        ],
    }
    if APPLY:
        created = svc.accounts().containers().workspaces().triggers().create(
            parent=ws_path, body=body_b).execute()
        trigger_b_id = created['triggerId']
        print(f'  [CREATED] Trigger id={trigger_b_id} name={created["name"]}', file=sys.stderr)
    else:
        print(f'  DRY-RUN: would create pageview trigger w/ Page Path equals + URL-page notEquals contact-us', file=sys.stderr)
        trigger_b_id = '(dry-run-B)'


# ============ 4. Re-point "GA4 — Step 2 Form Complete" → Trigger B ============
print('\n--- [4/5] Re-point "GA4 — Step 2 Form Complete" → Thank You — Default Lead ---', file=sys.stderr)
existing_tags = list_things('tags')
step2_tag = next((t for t in existing_tags if t['name'] == 'GA4 — Step 2 Form Complete'), None)
if not step2_tag:
    print(f'  [ERROR] Tag "GA4 — Step 2 Form Complete" not found in workspace', file=sys.stderr)
    sys.exit(1)
print(f'  Found tag id={step2_tag["tagId"]} current_triggers={step2_tag.get("firingTriggerId", [])}', file=sys.stderr)
if APPLY:
    new_tag = dict(step2_tag)
    new_tag['firingTriggerId'] = [str(trigger_b_id)]
    updated = svc.accounts().containers().workspaces().tags().update(
        path=f'{ws_path}/tags/{step2_tag["tagId"]}',
        body=new_tag,
        fingerprint=step2_tag.get('fingerprint'),
    ).execute()
    print(f'  [UPDATED] tag id={updated["tagId"]} new_triggers={updated.get("firingTriggerId", [])}', file=sys.stderr)
else:
    print(f'  DRY-RUN: would update tag {step2_tag["tagId"]} firingTriggerId=[{trigger_b_id}]', file=sys.stderr)


# ============ 5. Re-point "GA4 — Contact Us Form Complete" → Trigger A ============
print('\n--- [5/5] Re-point "GA4 — Contact Us Form Complete" → Thank You — Contact Us ---', file=sys.stderr)
contact_tag = next((t for t in existing_tags if t['name'] == 'GA4 — Contact Us Form Complete'), None)
if not contact_tag:
    print(f'  [ERROR] Tag "GA4 — Contact Us Form Complete" not found in workspace', file=sys.stderr)
    sys.exit(1)
print(f'  Found tag id={contact_tag["tagId"]} current_triggers={contact_tag.get("firingTriggerId", [])}', file=sys.stderr)
if APPLY:
    new_tag = dict(contact_tag)
    new_tag['firingTriggerId'] = [str(trigger_a_id)]
    updated = svc.accounts().containers().workspaces().tags().update(
        path=f'{ws_path}/tags/{contact_tag["tagId"]}',
        body=new_tag,
        fingerprint=contact_tag.get('fingerprint'),
    ).execute()
    print(f'  [UPDATED] tag id={updated["tagId"]} new_triggers={updated.get("firingTriggerId", [])}', file=sys.stderr)
else:
    print(f'  DRY-RUN: would update tag {contact_tag["tagId"]} firingTriggerId=[{trigger_a_id}]', file=sys.stderr)


print(f'\n[DONE] Workspace 50 modified but NOT published.', file=sys.stderr)
print(f'Next step: open GTM UI → Preview Mode → submit a test form → verify the GA4 tags fire on /thank-you/.', file=sys.stderr)
print(f'Then click Submit in GTM to publish the version.', file=sys.stderr)
