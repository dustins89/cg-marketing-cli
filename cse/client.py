"""Google Custom Search JSON API client.

Requires:
  - cse_api_key (Cloud Console API key, restricted to Custom Search API)
  - cse_engine_id (Programmable Search Engine ID — create at programmablesearchengine.google.com)

The Programmable Search Engine can be configured to "Search the entire web"
which makes this effectively a programmatic Google search (with quirks).

Reference: https://developers.google.com/custom-search/v1/overview
Quotas: 100 free queries/day. Beyond that, $5/1000 queries up to 10k/day.
"""
from __future__ import annotations

import requests

from gads.client import load_config


CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"


def get_credentials() -> tuple[str, str]:
    cfg = load_config()
    key = cfg.get("cse_api_key")
    engine = cfg.get("cse_engine_id")
    if not key or not engine:
        raise RuntimeError(
            "cse_api_key and/or cse_engine_id missing from google-ads.yaml. "
            "Get the API key from Cloud Console; create an engine at "
            "https://programmablesearchengine.google.com/."
        )
    return key, engine


def search(query: str, *, num: int = 10, start: int = 1, gl: str = "us",
           lr: str = "lang_en", site: str | None = None,
           site_filter: str = "i",
           date_restrict: str | None = None,
           exact_terms: str | None = None,
           exclude_terms: str | None = None,
           file_type: str | None = None,
           search_type: str | None = None,
           img_type: str | None = None,
           img_size: str | None = None,
           img_color_type: str | None = None,
           cr: str | None = None,
           safe: str = "off",
           rights: str | None = None,
           sort: str | None = None) -> dict:
    """Run a CSE search.

    Standard:
      num: results per page (max 10)
      start: 1-based offset (paginate by 10, max start=91 for 100-result cap)
      gl: country bias (e.g., 'us')
      lr: language restriction (e.g., 'lang_en')
      cr: country restriction (e.g., 'countryUS')

    Filters:
      site: limit to / exclude a domain
      site_filter: 'i' = include only --site, 'e' = exclude --site
      date_restrict: d[N], w[N], m[N], y[N] (e.g., 'd7' for last 7 days)
      exact_terms: phrase that must appear
      exclude_terms: words that must not appear
      file_type: pdf, doc, xls, etc.
      rights: usage rights filter (e.g., 'cc_publicdomain')
      sort: 'date' to sort by recency

    Image search (requires the engine to allow image search):
      search_type: 'image'
      img_type: clipart, face, lineart, news, photo
      img_size: huge, large, medium, small, xlarge, xxlarge, icon
      img_color_type: color, gray, mono, trans
    """
    key, engine = get_credentials()
    params = {
        "q": query,
        "key": key,
        "cx": engine,
        "num": min(10, num),
        "start": start,
        "gl": gl,
        "lr": lr,
        "safe": safe,
    }
    if site:
        params["siteSearch"] = site
        params["siteSearchFilter"] = site_filter
    if date_restrict:
        params["dateRestrict"] = date_restrict
    if exact_terms:
        params["exactTerms"] = exact_terms
    if exclude_terms:
        params["excludeTerms"] = exclude_terms
    if file_type:
        params["fileType"] = file_type
    if cr:
        params["cr"] = cr
    if rights:
        params["rights"] = rights
    if sort:
        params["sort"] = sort
    if search_type:
        params["searchType"] = search_type
    if img_type:
        params["imgType"] = img_type
    if img_size:
        params["imgSize"] = img_size
    if img_color_type:
        params["imgColorType"] = img_color_type
    resp = requests.get(CSE_ENDPOINT, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()
