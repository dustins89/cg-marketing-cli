"""CSE pullers — flatten search results + paginate."""
from __future__ import annotations

from typing import Callable


def parse_results(raw: dict, query: str, offset: int = 0) -> list[dict]:
    rows = []
    for i, item in enumerate(raw.get("items", []) or []):
        pagemap = item.get("pagemap") or {}
        metatags = (pagemap.get("metatags") or [{}])[0]
        rows.append({
            "rank": offset + i + 1,
            "query": query,
            "title": item.get("title"),
            "link": item.get("link"),
            "displayLink": item.get("displayLink"),
            "snippet": (item.get("snippet") or "").replace("\n", " ")[:200],
            "formattedUrl": item.get("formattedUrl"),
            "mime": item.get("mime"),
            "fileFormat": item.get("fileFormat"),
            "image_src": (pagemap.get("cse_image") or [{}])[0].get("src"),
            "og_title": metatags.get("og:title"),
            "og_description": metatags.get("og:description"),
            "og_type": metatags.get("og:type"),
            "twitter_card": metatags.get("twitter:card"),
            "article_published_time": metatags.get("article:published_time"),
        })
    return rows


def paginate(search_fn: Callable, query: str, max_results: int = 100, **kwargs) -> list[dict]:
    """Walk through CSE pagination. Hard cap of 100 results per CSE API limits.

    search_fn: typically `cse.client.search` — receives kwargs incl. start/num.
    """
    rows = []
    start = kwargs.pop("start", 1)
    while len(rows) < max_results and start <= 91:
        raw = search_fn(query, num=10, start=start, **kwargs)
        batch = parse_results(raw, query, offset=start - 1)
        rows.extend(batch)
        if len(batch) < 10:
            break
        start += 10
    return rows[:max_results]


def parse_search_info(raw: dict) -> dict:
    """Extract metadata from a CSE response (total results, search time, spelling)."""
    info = raw.get("searchInformation") or {}
    spelling = raw.get("spelling") or {}
    return {
        "totalResults": info.get("totalResults"),
        "formattedTotalResults": info.get("formattedTotalResults"),
        "searchTime": info.get("searchTime"),
        "formattedSearchTime": info.get("formattedSearchTime"),
        "corrected_query": spelling.get("correctedQuery"),
        "html_corrected_query": spelling.get("htmlCorrectedQuery"),
    }


COLUMNS = ["rank", "query", "displayLink", "title", "snippet"]
COLUMNS_FULL = ["rank", "query", "displayLink", "title", "snippet",
                "og_type", "og_description", "article_published_time"]
COLUMNS_IMAGES = ["rank", "query", "title", "displayLink", "image_src"]
