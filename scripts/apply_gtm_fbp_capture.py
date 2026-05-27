#!/usr/bin/env python3
"""GTM mutation: Custom HTML tag that reads the _fbp cookie and writes the value
into hidden form fields named `fb_fbp` or carrying CSS class `fb-fbp-field`.

Feeds Lead.FB_FBP__c via Carrot → Make → SF, which then propagates to the
Meta CAPI Queueable's user_data.fbp parameter for stronger match quality.

Companion to apply_gtm_ga4_cid_capture.py — same architecture.

Usage:
  python3 apply_gtm_fbp_capture.py            # dry-run
  python3 apply_gtm_fbp_capture.py --apply    # mutate
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

# Resolve Default Workspace dynamically
cont_path = f'accounts/{ACCT}/containers/{CONT}'
workspaces = svc.accounts().containers().workspaces().list(parent=cont_path).execute().get('workspace', [])
default_ws = next((w for w in workspaces if w['name'] == 'Default Workspace'), None)
if not default_ws:
    sys.exit('No Default Workspace found')
WS = default_ws['workspaceId']
ws_path = f'accounts/{ACCT}/containers/{CONT}/workspaces/{WS}'
print(f'Workspace: {ws_path}  Mode: {"APPLY" if APPLY else "DRY-RUN"}', file=sys.stderr)

# Reuse the All Pages trigger we created in the ga4_client_id deploy
triggers = svc.accounts().containers().workspaces().triggers().list(parent=ws_path).execute().get('trigger', [])
all_pages = next((t for t in triggers if t.get('name') == 'All Pages'), None)
if not all_pages:
    # Create one if missing
    if APPLY:
        all_pages = svc.accounts().containers().workspaces().triggers().create(
            parent=ws_path, body={'name': 'All Pages', 'type': 'pageview'}
        ).execute()
        print(f'  [CREATED] All Pages trigger id={all_pages["triggerId"]}', file=sys.stderr)
    else:
        all_pages = {'triggerId': '(dry-run)'}
        print('  DRY-RUN: would create All Pages trigger', file=sys.stderr)
else:
    print(f'  Using existing trigger id={all_pages["triggerId"]}', file=sys.stderr)

CUSTOM_HTML = '''<script>
(function(){
  function getFbp(){
    var m = document.cookie.match(/_fbp=(fb\\.\\d+\\.\\d+\\.\\d+)/);
    return m ? m[1] : '';
  }
  function fill(){
    var fbp = getFbp();
    if (!fbp) return;
    var sel = 'input[name="fb_fbp"], input[name*="fb_fbp"], input.fb-fbp-field';
    var els = document.querySelectorAll(sel);
    for (var i = 0; i < els.length; i++) { els[i].value = fbp; }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', fill);
  } else { fill(); }
  setTimeout(fill, 1500);
  setTimeout(fill, 4000);
})();
</script>'''


tags = svc.accounts().containers().workspaces().tags().list(parent=ws_path).execute().get('tag', [])
existing = next((t for t in tags if t['name'] == 'FB - Capture _fbp cookie into form field'), None)

tag_body = {
    'name': 'FB - Capture _fbp cookie into form field',
    'type': 'html',
    'parameter': [
        {'type': 'template', 'key': 'html', 'value': CUSTOM_HTML},
        {'type': 'boolean', 'key': 'supportDocumentWrite', 'value': 'false'},
    ],
    'firingTriggerId': [all_pages['triggerId']],
    'notes': 'Reads _fbp cookie and populates hidden form fields (fb_fbp / class fb-fbp-field). '
             'Feeds the SF Meta CAPI fan-out — see project_meta_capi.md / OCI_ACTIVATED.md.',
}

if existing:
    print(f'  [EXISTS] Tag id={existing["tagId"]}', file=sys.stderr)
    if APPLY:
        updated = svc.accounts().containers().workspaces().tags().update(
            path=existing['path'], body={**existing, **tag_body}
        ).execute()
        print(f'  [UPDATED] tag id={updated["tagId"]}', file=sys.stderr)
else:
    if APPLY:
        created = svc.accounts().containers().workspaces().tags().create(
            parent=ws_path, body=tag_body
        ).execute()
        print(f'  [CREATED] tag id={created["tagId"]} name={created["name"]}', file=sys.stderr)
    else:
        print(f'  DRY-RUN: would create tag "{tag_body["name"]}"', file=sys.stderr)
