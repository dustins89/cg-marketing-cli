#!/usr/bin/env python3
"""GTM mutation: rewrite the GA4 client_id + FB fbp cookie-capture tags so they
find the hidden Gravity Forms input via the WRAPPING `.gfield` div's cssClass
(GF puts custom classes on the wrapper, not the input itself).

New matching strategy (in order):
  1. `input[name|id|admin-label]` contains keyword (existing)
  2. `.gfield.X-class input[type=hidden]` (NEW — matches GF wrapper cssClass)
  3. `input.X-class` direct (existing CSS class fallback)

Re-publishes container as the next version.

Usage:
  python3 update_gtm_cookie_capture_selectors.py             # dry-run (shows diff)
  python3 update_gtm_cookie_capture_selectors.py --apply     # mutate + publish
"""
import sys, yaml, warnings
warnings.filterwarnings('ignore', category=FutureWarning)
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

cont_path = f'accounts/{ACCT}/containers/{CONT}'
workspaces = svc.accounts().containers().workspaces().list(parent=cont_path).execute().get('workspace', [])
default_ws = next((w for w in workspaces if w['name'] == 'Default Workspace'), None)
if not default_ws:
    sys.exit('No Default Workspace found')
WS = default_ws['workspaceId']
ws_path = f'accounts/{ACCT}/containers/{CONT}/workspaces/{WS}'
print(f'Workspace: {ws_path}  Mode: {"APPLY" if APPLY else "DRY-RUN"}', file=sys.stderr)


def build_html(cookie_regex_js: str, keywords: list, css_class: str) -> str:
    """Build the cookie-capture HTML body.

    cookie_regex_js: JS regex literal e.g. /_fbp=(fb\\.\\d+\\.\\d+\\.\\d+)/
    keywords: list of keyword strings to fuzzy-match in name/id/label
    css_class: the .gfield wrapper class added in Gravity Forms admin
    """
    keywords_js = ','.join(f'"{k}"' for k in keywords)
    return f'''<script>
(function(){{
  function fill(){{
    var m = document.cookie.match({cookie_regex_js});
    if (!m) return;
    var val = m[1];
    var keys = [{keywords_js}];
    var found = [];

    // Strategy 1 — name/id/admin-label/label keyword match
    var hiddens = document.querySelectorAll('input[type="hidden"]');
    for (var i=0; i<hiddens.length; i++) {{
      var el = hiddens[i];
      var name = (el.getAttribute('name')||'').toLowerCase();
      var id   = (el.getAttribute('id')||'').toLowerCase();
      var lbl  = '';
      var gf = el.closest && el.closest('.gfield');
      if (gf) {{
        var l = gf.querySelector('.gfield_label, .gfield_admin_label, label');
        if (l) lbl = (l.textContent||'').toLowerCase();
      }}
      for (var k=0; k<keys.length; k++) {{
        var kw = keys[k].toLowerCase();
        if (name.indexOf(kw)!==-1 || id.indexOf(kw)!==-1 || lbl.indexOf(kw)!==-1) {{
          found.push(el); break;
        }}
      }}
    }}

    // Strategy 2 — Gravity Forms wrapper cssClass match (NEW)
    // GF puts the field's "CSS Class Name" on the wrapping .gfield, not the input
    var gWrappers = document.querySelectorAll('.gfield.{css_class}');
    for (var j=0; j<gWrappers.length; j++) {{
      var inputs = gWrappers[j].querySelectorAll('input[type="hidden"]');
      for (var x=0; x<inputs.length; x++) found.push(inputs[x]);
    }}

    // Strategy 3 — direct class on input (fallback for non-GF or custom forms)
    var direct = document.querySelectorAll('input.{css_class}');
    for (var d=0; d<direct.length; d++) found.push(direct[d]);

    // De-dupe + write value
    var seen = {{}};
    for (var v=0; v<found.length; v++) {{
      var el = found[v];
      if (!seen[el.id || ('_'+v)]) {{
        seen[el.id || ('_'+v)] = true;
        el.value = val;
      }}
    }}
  }}
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fill);
  else fill();
  setTimeout(fill, 1500);
  setTimeout(fill, 4000);
}})();
</script>'''


GA4_HTML = build_html(
    cookie_regex_js=r'/_ga=GA1\.\d+\.([\d\.]+)/',
    keywords=['ga4_client_id', 'ga4-client-id', 'ga4_cid', 'ga4-cid'],
    css_class='ga4-cid-field',
)
FBP_HTML = build_html(
    cookie_regex_js=r'/_fbp=(fb\.\d+\.\d+\.\d+)/',
    keywords=['fb_fbp', 'fb-fbp', 'fb-fbp-field'],
    css_class='fb-fbp-field',
)


# List existing tags + find the two cookie-capture tags by name
tags = svc.accounts().containers().workspaces().tags().list(parent=ws_path).execute().get('tag', [])

def find_tag(name_contains: str):
    for t in tags:
        if name_contains.lower() in t.get('name', '').lower():
            return t
    return None


def get_html_param(tag):
    for p in tag.get('parameter', []):
        if p.get('key') == 'html':
            return p.get('value', '')
    return ''


def set_html_param(tag, html):
    for p in tag.get('parameter', []):
        if p.get('key') == 'html':
            p['value'] = html
            return
    tag.setdefault('parameter', []).append({'type':'template','key':'html','value':html})


ga4_tag = find_tag('Capture client_id')
fbp_tag = find_tag('Capture _fbp')

if not ga4_tag or not fbp_tag:
    print('Could not find both tags. Available tags:', file=sys.stderr)
    for t in tags:
        print(f'  [{t.get("tagId")}] {t.get("name","?")} ({t.get("type","?")})', file=sys.stderr)
    sys.exit(1)

print(f'GA4 tag: [{ga4_tag["tagId"]}] {ga4_tag["name"]}')
print(f'FBP tag: [{fbp_tag["tagId"]}] {fbp_tag["name"]}')
print()

for label, tag, new_html in [('GA4', ga4_tag, GA4_HTML), ('FBP', fbp_tag, FBP_HTML)]:
    old_html = get_html_param(tag)
    print(f'=== {label} OLD HTML ({len(old_html)} chars) ===')
    print(old_html[:400] + ('...' if len(old_html) > 400 else ''))
    print(f'=== {label} NEW HTML ({len(new_html)} chars) ===')
    print(new_html[:400] + ('...' if len(new_html) > 400 else ''))
    print()
    if APPLY:
        set_html_param(tag, new_html)
        svc.accounts().containers().workspaces().tags().update(path=tag['path'], body=tag).execute()
        print(f'✓ Updated {label} tag {tag["tagId"]}')

if APPLY:
    # Publish a new version
    print()
    print('Publishing new container version...')
    ver = svc.accounts().containers().workspaces().create_version(
        path=ws_path,
        body={'name': 'GTM cookie-capture: GF-wrapper-aware selectors',
              'notes': 'Adds .gfield.{X}-field input[type=hidden] selector strategy. CSS class on the GF wrapper now matches.'}
    ).execute()
    cv = ver.get('containerVersion', {})
    cvid = cv.get('containerVersionId')
    print(f'Created version {cvid}')
    pub = svc.accounts().containers().versions().publish(
        path=f'{cont_path}/versions/{cvid}'
    ).execute()
    print(f'Published: {pub.get("containerVersion", {}).get("name", "?")}')
else:
    print('(dry-run — no changes made. Run with --apply to mutate + publish.)')
