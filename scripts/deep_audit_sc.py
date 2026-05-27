#!/usr/bin/env python3
"""Deep SC-side per-page audit. Fetches each top-impr URL, extracts title/meta/canonical/
schema/heading structure/internal links. Writes /tmp/sc_deep_pages.json."""
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from urllib.parse import urlparse

HOST = "https://www.your-domain.com"
ua = "Mozilla/5.0 (Macintosh; deep_audit_bot; +https://www.your-domain.com)"
HEADERS = {"User-Agent": ua}

def get_top_urls():
    pages = json.load(open("/tmp/sc_pages.json"))
    pages.sort(key=lambda p: -p.get("impressions", 0))
    urls = [p["page"] for p in pages[:30]]
    if HOST + "/cash-for-house/" not in urls:
        urls.append(HOST + "/cash-for-house/")
    if HOST + "/as-seen-on-tv/" not in urls:
        urls.append(HOST + "/as-seen-on-tv/")
    return urls

def parse_page(html, url):
    out = {"url": url}
    # Title
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    out["title"] = m.group(1).strip() if m else None
    out["title_len"] = len(out["title"]) if out["title"] else 0
    # Meta description
    m = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
    if not m:
        m = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']description["\']', html, re.I)
    out["meta_desc"] = m.group(1).strip() if m else None
    out["meta_desc_len"] = len(out["meta_desc"]) if out["meta_desc"] else 0
    # Canonical
    m = re.search(r'<link[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']', html, re.I)
    if not m:
        m = re.search(r'<link[^>]*href=["\']([^"\']+)["\'][^>]*rel=["\']canonical["\']', html, re.I)
    out["canonical"] = m.group(1).strip() if m else None
    out["canonical_self"] = (out["canonical"] == url) if out["canonical"] else None
    # noindex / robots meta
    m = re.search(r'<meta[^>]*name=["\']robots["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
    if not m:
        m = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']robots["\']', html, re.I)
    out["robots_meta"] = m.group(1).strip().lower() if m else None
    out["noindex"] = "noindex" in (out["robots_meta"] or "")
    # OG tags presence
    out["has_og_title"] = bool(re.search(r'property=["\']og:title["\']', html, re.I))
    out["has_og_desc"] = bool(re.search(r'property=["\']og:description["\']', html, re.I))
    out["has_og_image"] = bool(re.search(r'property=["\']og:image["\']', html, re.I))
    # Schema (JSON-LD)
    schemas = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>([\s\S]+?)</script>', html, re.I)
    schema_types = []
    for s in schemas:
        try:
            d = json.loads(s.strip())
            items = d if isinstance(d, list) else [d]
            for it in items:
                if isinstance(it, dict):
                    t = it.get("@type")
                    if isinstance(t, list):
                        schema_types.extend(t)
                    elif t:
                        schema_types.append(t)
                    # Handle @graph
                    if "@graph" in it:
                        for g in it["@graph"]:
                            t2 = g.get("@type") if isinstance(g, dict) else None
                            if isinstance(t2, list):
                                schema_types.extend(t2)
                            elif t2:
                                schema_types.append(t2)
        except Exception:
            pass
    out["schema_types"] = sorted(set(schema_types))
    out["schema_count"] = len(schemas)
    # Headings
    h1s = re.findall(r"<h1[^>]*>([\s\S]+?)</h1>", html, re.I)
    h2s = re.findall(r"<h2[^>]*>([\s\S]+?)</h2>", html, re.I)
    out["h1_count"] = len(h1s)
    out["h1_text"] = [re.sub(r"<[^>]+>", "", h).strip()[:120] for h in h1s]
    out["h2_count"] = len(h2s)
    # Internal links
    links = re.findall(r'<a[^>]*href=["\']([^"\']+)["\']', html, re.I)
    internal = [l for l in links if (HOST in l or (l.startswith("/") and not l.startswith("//")))]
    out["link_count"] = len(links)
    out["internal_link_count"] = len(internal)
    # Word count (approx)
    text = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    out["word_count_approx"] = len(text.split())
    # Has WordPress generator?
    m = re.search(r'<meta[^>]*name=["\']generator["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
    out["generator"] = m.group(1).strip() if m else None
    # Detect Carrot vs WP indicator
    out["is_carrot"] = "carrot" in html.lower() or "investorcarrot" in html.lower()
    return out

def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        return {"url": url, "status": r.status_code, "final_url": r.url, "size_bytes": len(r.content), "html": r.text}
    except Exception as e:
        return {"url": url, "status": 0, "error": str(e)}

def main():
    urls = get_top_urls()
    print(f"Fetching {len(urls)} URLs...", file=sys.stderr)
    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(fetch, u): u for u in urls}
        for fut in as_completed(futs):
            r = fut.result()
            if r.get("html"):
                parsed = parse_page(r["html"], r["url"])
                parsed["status"] = r["status"]
                parsed["final_url"] = r["final_url"]
                parsed["size_bytes"] = r["size_bytes"]
                # Don't keep raw html
                results.append(parsed)
                print(f"  ok {r['status']} {r['url']}", file=sys.stderr)
            else:
                results.append({"url": r["url"], "error": r.get("error"), "status": r.get("status",0)})
                print(f"  ERR {r['url']}: {r.get('error')}", file=sys.stderr)
    # Robots.txt
    try:
        rb = requests.get(HOST + "/robots.txt", headers=HEADERS, timeout=10).text
    except Exception:
        rb = None
    # Sitemap
    sm = {}
    for path in ("/sitemap.xml", "/sitemap_index.xml"):
        try:
            r = requests.get(HOST + path, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                sm[path] = {"status": 200, "size": len(r.content), "head": r.text[:600]}
        except Exception:
            pass

    with open("/tmp/sc_deep_pages.json", "w") as f:
        json.dump({"pages": results, "robots_txt": rb, "sitemaps": sm}, f, indent=2)
    print(f"\n[done] wrote /tmp/sc_deep_pages.json ({len(results)} pages)", file=sys.stderr)

if __name__ == "__main__":
    main()
