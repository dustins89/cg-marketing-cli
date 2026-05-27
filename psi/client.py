"""PageSpeed Insights API client.

PSI is unauthenticated for low rate limits (1 query/sec, 25k/day) and accepts
an API key for higher quota. We support both — if `psi_api_key` exists in
google-ads.yaml, we send it; otherwise the call goes anonymous.

Reference:
  https://developers.google.com/speed/docs/insights/v5/get-started
  https://developers.google.com/speed/docs/insights/v5/reference/pagespeedapi/runpagespeed
"""
from __future__ import annotations

import requests

from gads.client import load_config


PSI_ENDPOINT = "https://pagespeedonline.googleapis.com/pagespeedonline/v5/runPagespeed"


def get_api_key() -> str | None:
    return load_config().get("psi_api_key")


def run_pagespeed(
    url: str,
    strategy: str = "MOBILE",
    categories: list[str] | None = None,
    locale: str = "en_US",
    timeout: int = 60,
) -> dict:
    """Run a PSI audit for one URL.

    strategy: "MOBILE" or "DESKTOP"
    categories: subset of ["PERFORMANCE", "ACCESSIBILITY", "BEST_PRACTICES", "SEO", "PWA"]
                Defaults to all five.
    """
    if categories is None:
        categories = ["PERFORMANCE", "ACCESSIBILITY", "BEST_PRACTICES", "SEO"]
    params = [
        ("url", url),
        ("strategy", strategy),
        ("locale", locale),
    ]
    for c in categories:
        params.append(("category", c))
    api_key = get_api_key()
    if api_key:
        params.append(("key", api_key))
    resp = requests.get(PSI_ENDPOINT, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()
