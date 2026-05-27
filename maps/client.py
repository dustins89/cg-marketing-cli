"""Google Maps Platform — Places API (New) client.

Uses an API key from `maps_api_key` in google-ads.yaml. The Places API (New)
uses HTTP POST + a header-based field mask, distinct from the legacy Places API.

Reference:
  https://developers.google.com/maps/documentation/places/web-service/op-overview
  https://developers.google.com/maps/documentation/places/web-service/text-search
"""
from __future__ import annotations

import requests

from gads.client import load_config


PLACES_BASE = "https://places.googleapis.com/v1"


def get_api_key() -> str:
    cfg = load_config()
    key = cfg.get("maps_api_key")
    if not key:
        raise RuntimeError(
            "maps_api_key missing from google-ads.yaml. Add the API key from "
            "Cloud Console → APIs & Services → Credentials."
        )
    return key


def _headers(field_mask: str) -> dict:
    return {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": get_api_key(),
        "X-Goog-FieldMask": field_mask,
    }


def text_search(query: str, *, location_bias: dict | None = None, max_results: int = 20,
                field_mask: str | None = None) -> dict:
    """Search places by free-text query (e.g., 'we buy houses <your-city>')."""
    fm = field_mask or (
        "places.id,places.displayName,places.formattedAddress,places.location,"
        "places.rating,places.userRatingCount,places.businessStatus,places.types,"
        "places.websiteUri,places.nationalPhoneNumber,places.googleMapsUri,"
        "places.regularOpeningHours,places.priceLevel,places.editorialSummary,"
        "places.primaryTypeDisplayName,places.iconBackgroundColor"
    )
    body = {"textQuery": query, "pageSize": min(20, max_results)}
    if location_bias:
        body["locationBias"] = location_bias
    resp = requests.post(
        f"{PLACES_BASE}/places:searchText",
        headers=_headers(fm),
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def place_details(place_id: str, field_mask: str | None = None) -> dict:
    """Fetch full details for one place. place_id format: 'ChIJ...' (no 'places/' prefix)."""
    fm = field_mask or (
        "id,displayName,formattedAddress,location,rating,userRatingCount,"
        "businessStatus,types,websiteUri,nationalPhoneNumber,googleMapsUri,"
        "regularOpeningHours,currentOpeningHours,priceLevel,editorialSummary,"
        "primaryTypeDisplayName,reviews,photos,attributions"
    )
    resp = requests.get(
        f"{PLACES_BASE}/places/{place_id}",
        headers=_headers(fm),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
