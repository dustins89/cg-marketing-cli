#!/usr/bin/env python3
"""Deep schema audit: render each top SC page via headless Chrome, capture the
final rendered HTML (after JS hydration), extract all JSON-LD blocks, and
recursively walk @graph / mainEntity / hasPart / isPartOf to find every schema
type that actually appears on the page.

Replaces the regex-based parser that missed Yoast's nested @graph output."""
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

def get_urls():
    pages = json.load(open("/tmp/sc_pages.json"))
    pages.sort(key=lambda p: -p.get("impressions", 0))
    urls = [p["page"] for p in pages[:30]]
    for u in [
        "https://www.your-domain.com/cash-for-house/",
        "https://www.your-domain.com/as-seen-on-tv/",
        "https://www.your-domain.com/reviews/",
        "https://www.your-domain.com/faq/",
    ]:
        if u not in urls:
            urls.append(u)
    return urls


def render(url):
    """Use Chrome headless to dump the fully-rendered DOM as HTML."""
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        out = f.name
    try:
        # Use --dump-dom and capture to file
        cmd = [
            CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--virtual-time-budget=8000",  # let JS run for 8s
            "--run-all-compositor-stages-before-draw",
            "--dump-dom", url,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=30)
        return r.stdout.decode("utf-8", errors="ignore")
    except subprocess.TimeoutExpired:
        return ""
    finally:
        try: os.unlink(out)
        except: pass


def extract_schemas(html):
    """Return every @type that appears anywhere in any JSON-LD block.
    Recurses through @graph, mainEntity, hasPart, isPartOf, itemReviewed, etc."""
    import re
    blocks = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>([\s\S]+?)</script>',
        html, re.I
    )
    found = []
    def walk(node, path=""):
        if isinstance(node, dict):
            t = node.get("@type")
            if t:
                tlist = t if isinstance(t, list) else [t]
                for tt in tlist:
                    found.append({"type": tt, "path": path, "id": node.get("@id", ""), "name": node.get("name", "")[:80] if node.get("name") else ""})
            for k, v in node.items():
                if k.startswith("@") and k not in ("@graph",): continue
                walk(v, f"{path}/{k}")
        elif isinstance(node, list):
            for i, it in enumerate(node):
                walk(it, f"{path}[{i}]")
    for b in blocks:
        try:
            d = json.loads(b.strip())
            walk(d)
        except Exception as e:
            found.append({"type": "PARSE_ERROR", "path": "", "id": "", "name": str(e)[:80]})
    return found, len(blocks)


def audit_url(url):
    html = render(url)
    if not html:
        return {"url": url, "error": "render failed"}
    schemas, block_count = extract_schemas(html)
    types = sorted(set(s["type"] for s in schemas))
    return {
        "url": url,
        "html_size": len(html),
        "jsonld_blocks": block_count,
        "schema_types": types,
        "schema_count_total": len(schemas),
        "entities": [{"type": s["type"], "name": s["name"]} for s in schemas[:30]],
    }


def main():
    urls = get_urls()
    print(f"Auditing {len(urls)} URLs with headless Chrome...", file=sys.stderr)
    results = []
    # Serial because headless Chrome processes are heavy
    for i, u in enumerate(urls):
        print(f"  [{i+1}/{len(urls)}] {u}", file=sys.stderr)
        r = audit_url(u)
        results.append(r)
    with open("/tmp/sc_schema_deep.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[done] /tmp/sc_schema_deep.json ({len(results)} pages)", file=sys.stderr)

if __name__ == "__main__":
    main()
