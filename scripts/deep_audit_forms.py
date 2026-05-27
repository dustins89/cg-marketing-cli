#!/usr/bin/env python3
"""Deep form audit: render every form-bearing page via headless Chrome,
let JS hydrate, then extract every <input> on every <form> — including
hidden inputs that are JS-injected after page load. Captures values too
when a test URL with params is provided.

This is what `curl | grep` missed."""
import json
import subprocess
import sys
import tempfile
import os

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Pages with lead-capture forms + the test URL with all attribution params
TEST_PARAMS = (
    "?gclid=DEEP_AUDIT_GCLID_20260516"
    "&fbclid=DEEP_AUDIT_FBCLID"
    "&gbraid=DEEP_AUDIT_GBRAID"
    "&wbraid=DEEP_AUDIT_WBRAID"
    "&utm_source=audit_deep"
    "&utm_medium=test"
    "&utm_campaign=form_field_inspection"
    "&utm_term=deep_term"
    "&utm_content=deep_content"
)

PAGES = [
    "https://www.your-domain.com/cash-for-house/",
    "https://www.your-domain.com/as-seen-on-tv/",
    "https://www.your-domain.com/contact-us/",
    "https://www.your-domain.com/sell-your-house/",
    "https://www.your-domain.com/",  # homepage form
    "https://www.your-domain.com/get-a-cash-offer-today/",
]

JS_EXTRACTOR = r"""
(() => {
    const forms = [...document.querySelectorAll('form')];
    return forms.map((f, i) => ({
        index: i,
        id: f.id,
        name: f.name,
        action: f.action,
        method: f.method,
        class_list: [...f.classList],
        inputs: [...f.querySelectorAll('input,select,textarea')].map(inp => ({
            tag: inp.tagName.toLowerCase(),
            type: inp.type,
            name: inp.name,
            id: inp.id,
            value: inp.value,
            placeholder: inp.placeholder,
            required: inp.required,
            hidden: inp.type === 'hidden' || inp.hidden || getComputedStyle(inp).display === 'none',
        })),
    }));
})()
"""


def render_and_extract(url):
    """Render URL via headless Chrome and extract all form inputs via evaluated JS."""
    # Chrome --headless doesn't support arbitrary --evaluate-script in the simple flow.
    # Workaround: dump DOM after JS hydration, then parse for forms+inputs ourselves.
    cmd = [
        CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
        "--virtual-time-budget=10000",  # 10s for JS to hydrate
        "--run-all-compositor-stages-before-draw",
        "--dump-dom", url,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=30)
        return r.stdout.decode("utf-8", errors="ignore")
    except subprocess.TimeoutExpired:
        return ""


def parse_forms(html, url):
    """Extract forms + inputs from rendered HTML."""
    import re
    forms = []
    # Match each <form ...>...</form> block
    form_pattern = re.compile(r'<form\b([^>]*)>([\s\S]*?)</form>', re.I)
    for m in form_pattern.finditer(html):
        attrs = m.group(1)
        body = m.group(2)
        form = {
            "id": re.search(r'\bid=["\']([^"\']*)["\']', attrs).group(1) if re.search(r'\bid=["\']([^"\']*)["\']', attrs) else "",
            "class": re.search(r'\bclass=["\']([^"\']*)["\']', attrs).group(1) if re.search(r'\bclass=["\']([^"\']*)["\']', attrs) else "",
            "action": re.search(r'\baction=["\']([^"\']*)["\']', attrs).group(1) if re.search(r'\baction=["\']([^"\']*)["\']', attrs) else "",
            "method": re.search(r'\bmethod=["\']([^"\']*)["\']', attrs).group(1) if re.search(r'\bmethod=["\']([^"\']*)["\']', attrs) else "",
            "inputs": [],
        }
        # Find inputs
        for inp in re.finditer(r'<input\b([^>]*)/?>', body, re.I):
            ia = inp.group(1)
            input_info = {
                "type": (re.search(r'\btype=["\']([^"\']*)["\']', ia).group(1) if re.search(r'\btype=["\']([^"\']*)["\']', ia) else "text"),
                "name": (re.search(r'\bname=["\']([^"\']*)["\']', ia).group(1) if re.search(r'\bname=["\']([^"\']*)["\']', ia) else ""),
                "id": (re.search(r'\bid=["\']([^"\']*)["\']', ia).group(1) if re.search(r'\bid=["\']([^"\']*)["\']', ia) else ""),
                "value": (re.search(r'\bvalue=["\']([^"\']*)["\']', ia).group(1) if re.search(r'\bvalue=["\']([^"\']*)["\']', ia) else ""),
                "placeholder": (re.search(r'\bplaceholder=["\']([^"\']*)["\']', ia).group(1) if re.search(r'\bplaceholder=["\']([^"\']*)["\']', ia) else ""),
            }
            form["inputs"].append(input_info)
        forms.append(form)
    return forms


def audit_page(url, with_test_params=True):
    test_url = url + (TEST_PARAMS if with_test_params else "")
    html = render_and_extract(test_url)
    if not html:
        return {"url": test_url, "error": "render failed"}
    forms = parse_forms(html, test_url)
    # Summary
    attribution_fields = ["gclid", "fbclid", "gbraid", "wbraid", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"]
    attribution_present = {}
    for f in forms:
        for inp in f["inputs"]:
            n = inp["name"].lower().lstrip("_").replace("-", "_")
            if n in attribution_fields:
                attribution_present[n] = {"value": inp["value"], "form_id": f["id"] or "(no id)"}
    return {
        "url": test_url,
        "html_size": len(html),
        "form_count": len(forms),
        "forms": forms,
        "attribution_fields_present": attribution_present,
        "attribution_fields_missing": [f for f in attribution_fields if f not in attribution_present],
    }


def main():
    print(f"Auditing {len(PAGES)} pages with test attribution params...", file=sys.stderr)
    results = []
    for i, u in enumerate(PAGES):
        print(f"  [{i+1}/{len(PAGES)}] {u}", file=sys.stderr)
        r = audit_page(u, with_test_params=True)
        results.append(r)
    with open("/tmp/forms_deep.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[done] /tmp/forms_deep.json", file=sys.stderr)

if __name__ == "__main__":
    main()
