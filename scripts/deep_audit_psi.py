#!/usr/bin/env python3
"""Deep PSI audit — top opportunities + diagnostics per page, mobile + desktop."""
import json
import sys
import time
import requests
import yaml
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
cfg = yaml.safe_load((HERE / "google-ads.yaml").read_text())
KEY = cfg.get("psi_api_key")

urls = [u.strip() for u in open("/tmp/top10_pages.txt").read().splitlines() if u.strip()]

results = []
for i, u in enumerate(urls):
    for strategy in ("mobile", "desktop"):
        params = {
            "url": u,
            "strategy": strategy,
            "category": ["performance", "accessibility", "best-practices", "seo"],
        }
        if KEY:
            params["key"] = KEY
        try:
            r = requests.get(
                "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                params=params,
                timeout=120,
            )
            r.raise_for_status()
            data = r.json()
            lh = data.get("lighthouseResult", {})
            audits = lh.get("audits", {})
            cats = lh.get("categories", {})
            # Get top opportunities (impact >= 100ms or savings > 0)
            opps = []
            for k, a in audits.items():
                details = a.get("details", {})
                if details.get("type") == "opportunity":
                    saving = details.get("overallSavingsMs", 0)
                    if saving and saving >= 50:
                        opps.append(
                            {
                                "id": k,
                                "title": a.get("title"),
                                "savings_ms": saving,
                                "display_value": a.get("displayValue", ""),
                            }
                        )
                elif a.get("score") is not None and a["score"] < 0.9 and a.get("scoreDisplayMode") in ("numeric","binary"):
                    opps.append(
                        {
                            "id": k,
                            "title": a.get("title"),
                            "score": a["score"],
                            "display_value": a.get("displayValue", ""),
                        }
                    )
            opps.sort(key=lambda o: -(o.get("savings_ms") or (1 - o.get("score", 0)) * 1000))
            # Resource breakdown
            res = audits.get("resource-summary", {}).get("details", {}).get("items", [])
            res_summary = {r.get("resourceType"): {"size_kb": round(r.get("transferSize",0)/1024,1), "count": r.get("requestCount",0)} for r in res}
            results.append(
                {
                    "url": u,
                    "strategy": strategy.upper(),
                    "performance": int((cats.get("performance",{}).get("score") or 0)*100),
                    "accessibility": int((cats.get("accessibility",{}).get("score") or 0)*100),
                    "best_practices": int((cats.get("best-practices",{}).get("score") or 0)*100),
                    "seo": int((cats.get("seo",{}).get("score") or 0)*100),
                    "lab_lcp_ms": int(audits.get("largest-contentful-paint",{}).get("numericValue",0) or 0),
                    "lab_fcp_ms": int(audits.get("first-contentful-paint",{}).get("numericValue",0) or 0),
                    "lab_tbt_ms": int(audits.get("total-blocking-time",{}).get("numericValue",0) or 0),
                    "lab_cls": round(audits.get("cumulative-layout-shift",{}).get("numericValue",0) or 0,3),
                    "lab_si_ms": int(audits.get("speed-index",{}).get("numericValue",0) or 0),
                    "lab_tti_ms": int(audits.get("interactive",{}).get("numericValue",0) or 0),
                    "top_opportunities": opps[:8],
                    "resources": res_summary,
                }
            )
            print(f"  [{i+1}/{len(urls)}] {strategy:7} perf={results[-1]['performance']:3} {u}", file=sys.stderr)
        except Exception as e:
            print(f"  ERR {strategy:7} {u}: {e}", file=sys.stderr)
        time.sleep(1.5)

with open("/tmp/psi_deep.json", "w") as f:
    json.dump(results, f, indent=2)
print(f"\n[done] /tmp/psi_deep.json ({len(results)} runs)", file=sys.stderr)
