#!/usr/bin/env python3
"""GTM mutation: deploy a Custom HTML tag that reads the _ga cookie and writes
the GA4 client_id into form fields named ga4_client_id or carrying the CSS
class ga4-cid-field.

This is the front-end piece of the SF GA4 Measurement Protocol fan-out
(see ~/.claude/projects/.../memory/project_ga4_measurement_protocol.md):
the captured client_id flows through hidden form field → Carrot/Gravity Forms
webhook → Make scenario → SF Lead.GA4_Client_Id__c → Opp → Tx → Queue → GA4
MP event. Without this tag, GA4 events still land but with synthesized
'sfid-{LeadId}' client_ids (no real session attribution).

Creates in the Default Workspace:
  - Custom HTML tag "GA4 - Capture client_id into form field" (All Pages, document ready)

Does NOT auto-publish. After running with --apply, user verifies in GTM
Preview Mode + clicks Submit in UI to publish.

Usage:
  python3 apply_gtm_ga4_cid_capture.py             # dry-run
  python3 apply_gtm_ga4_cid_capture.py --apply     # mutate
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

# Find the Default Workspace dynamically (id changes after each publish)
cont_path = f'accounts/{ACCT}/containers/{CONT}'
res = svc.accounts().containers().workspaces().list(parent=cont_path).execute()
workspaces = res.get('workspace', [])
default_ws = next((w for w in workspaces if w['name'] == 'Default Workspace'), None)
if not default_ws:
    print(f'ERROR: No Default Workspace found. Existing workspaces: {[w["name"] for w in workspaces]}', file=sys.stderr)
    sys.exit(1)
WS = default_ws['workspaceId']
ws_path = f'accounts/{ACCT}/containers/{CONT}/workspaces/{WS}'
print(f'Workspace: {ws_path}  Mode: {"APPLY" if APPLY else "DRY-RUN"}', file=sys.stderr)


def list_tags():
    res = svc.accounts().containers().workspaces().tags().list(parent=ws_path).execute()
    return res.get('tag', [])


def list_triggers():
    res = svc.accounts().containers().workspaces().triggers().list(parent=ws_path).execute()
    return res.get('trigger', [])


# Find or create a "DOM Ready - All Pages" trigger.
# GTM 'pageview' = DOM-Ready custom trigger fires once per page load on all pages.
# Built-in All Pages trigger (id 2147479553) is not always usable via API — safer to create custom.
print('\n--- Finding or creating All-Pages pageview trigger ---', file=sys.stderr)
triggers = list_triggers()
all_pages = next((t for t in triggers
                  if t.get('type') in ('pageview', 'domReady') and not t.get('filter') and not t.get('autoEventFilter')),
                 None)
if not all_pages:
    all_pages = next((t for t in triggers if t.get('name') in ('All Pages', 'All Pageviews', 'DOM Ready - All Pages')), None)

if not all_pages:
    trigger_body = {
        'name': 'All Pages',
        'type': 'pageview',
    }
    if APPLY:
        all_pages = svc.accounts().containers().workspaces().triggers().create(
            parent=ws_path, body=trigger_body).execute()
        print(f'  [CREATED] trigger id={all_pages["triggerId"]} name={all_pages["name"]}', file=sys.stderr)
    else:
        print(f'  DRY-RUN: would create "All Pages" pageview trigger', file=sys.stderr)
        all_pages = {'triggerId': '(dry-run)'}
else:
    print(f'  [REUSE] trigger id={all_pages["triggerId"]} name="{all_pages["name"]}"', file=sys.stderr)


CUSTOM_HTML = '''<script>
(function(){
  function getGaCid(){
    var m = document.cookie.match(/_ga=GA1\\.\\d+\\.([\\d.]+)/);
    return m ? m[1] : '';
  }
  function fill(){
    var cid = getGaCid();
    if (!cid) return;
    var sel = 'input[name="ga4_client_id"], input[name*="ga4_client_id"], input.ga4-cid-field';
    var els = document.querySelectorAll(sel);
    for (var i = 0; i < els.length; i++) { els[i].value = cid; }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', fill);
  } else { fill(); }
  // Catch lazily-injected forms (Gravity Forms ajax, page builders, etc)
  setTimeout(fill, 1500);
  setTimeout(fill, 4000);
})();
</script>'''


print('\n--- Custom HTML tag: GA4 - Capture client_id into form field ---', file=sys.stderr)
tags = list_tags()
existing = next((t for t in tags if t['name'] == 'GA4 - Capture client_id into form field'), None)
tag_body = {
    'name': 'GA4 - Capture client_id into form field',
    'type': 'html',
    'parameter': [
        {'type': 'template', 'key': 'html', 'value': CUSTOM_HTML},
        {'type': 'boolean', 'key': 'supportDocumentWrite', 'value': 'false'},
    ],
    'firingTriggerId': [all_pages['triggerId']],
    'notes': 'Reads _ga cookie and populates hidden form fields (ga4_client_id) on every pageview. '
             'Feeds the SF GA4 Measurement Protocol fan-out — see project_ga4_measurement_protocol.md.',
}
if existing:
    print(f'  [SKIP/UPDATE] Tag already exists: id={existing["tagId"]}', file=sys.stderr)
    if APPLY:
        updated = svc.accounts().containers().workspaces().tags().update(
            path=existing['path'], body={**existing, **tag_body}).execute()
        print(f'  [UPDATED] tag id={updated["tagId"]}', file=sys.stderr)
    else:
        print(f'  DRY-RUN: would update tag id={existing["tagId"]}', file=sys.stderr)
else:
    if APPLY:
        created = svc.accounts().containers().workspaces().tags().create(
            parent=ws_path, body=tag_body).execute()
        print(f'  [CREATED] tag id={created["tagId"]} name={created["name"]}', file=sys.stderr)
    else:
        print(f'  DRY-RUN: would create tag "{tag_body["name"]}" firing on All Pages', file=sys.stderr)


print('\n--- Done ---', file=sys.stderr)
print('Next steps:', file=sys.stderr)
print('  1. Open GTM UI → Workspace → Preview Mode → load any DBH page → confirm tag fires', file=sys.stderr)
print('  2. In GTM UI → Submit/Publish the workspace as a new container version', file=sys.stderr)
print('  3. Dustin: in Carrot/Gravity Forms editor, add hidden field with', file=sys.stderr)
print('     dynamic-population parameter name "ga4_client_id" to forms 1/4/6/9', file=sys.stderr)
