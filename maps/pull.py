"""Maps pullers — flatten Places API responses into rows for analysis."""
from __future__ import annotations


def parse_places(raw: dict) -> list[dict]:
    rows = []
    for p in raw.get("places", []):
        rows.append({
            "id": p.get("id"),
            "name": (p.get("displayName") or {}).get("text"),
            "primaryType": p.get("primaryTypeDisplayName", {}).get("text") if isinstance(p.get("primaryTypeDisplayName"), dict) else p.get("primaryTypeDisplayName"),
            "rating": p.get("rating"),
            "reviewCount": p.get("userRatingCount", 0),
            "businessStatus": p.get("businessStatus"),
            "address": p.get("formattedAddress"),
            "phone": p.get("nationalPhoneNumber"),
            "website": p.get("websiteUri"),
            "googleMapsUri": p.get("googleMapsUri"),
            "priceLevel": p.get("priceLevel"),
        })
    return rows


def parse_place_detail(raw: dict) -> dict:
    """Flatten one place detail with photo/review counts."""
    return {
        "id": raw.get("id"),
        "name": (raw.get("displayName") or {}).get("text"),
        "primaryType": (raw.get("primaryTypeDisplayName") or {}).get("text"),
        "rating": raw.get("rating"),
        "reviewCount": raw.get("userRatingCount", 0),
        "reviewsReturned": len(raw.get("reviews") or []),
        "photoCount": len(raw.get("photos") or []),
        "businessStatus": raw.get("businessStatus"),
        "address": raw.get("formattedAddress"),
        "phone": raw.get("nationalPhoneNumber"),
        "website": raw.get("websiteUri"),
        "googleMapsUri": raw.get("googleMapsUri"),
        "openNow": (raw.get("currentOpeningHours") or {}).get("openNow"),
    }


COLUMNS = {
    "search": ["name", "rating", "reviewCount", "primaryType", "address", "phone", "website", "businessStatus"],
    "detail": ["name", "rating", "reviewCount", "reviewsReturned", "photoCount", "businessStatus", "primaryType", "address", "website", "openNow"],
}
