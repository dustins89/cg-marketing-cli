"""GA4 output helpers — thin shim over gads.format with GA4-specific casters."""
from __future__ import annotations

from gads.format import emit  # re-export so cli.py can `from .format import emit`


def cast_metric(name: str, value: str):
    """GA4 returns every metric as a string. Cast to int/float by name."""
    if value is None or value == "":
        return None
    int_metrics = {"sessions", "screenPageViews", "eventCount", "activeUsers", "newUsers"}
    if name in int_metrics:
        try:
            return int(float(value))
        except ValueError:
            return value
    try:
        v = float(value)
        return round(v, 4) if name in {"bounceRate", "engagementRate"} else round(v, 2)
    except ValueError:
        return value


__all__ = ["emit", "cast_metric"]
