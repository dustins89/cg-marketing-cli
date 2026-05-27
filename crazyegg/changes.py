"""Schema + validation for proposed Crazy Egg changes (YAML).

Supported types
───────────────
- create_snapshot   — create a new heatmap
- update_snapshot   — update an existing heatmap
- stop_snapshot     — stop tracking
- restart_snapshot  — restart tracking on a stopped heatmap
"""
from __future__ import annotations

from pathlib import Path

import yaml


_REQUIRED = {
    "create_snapshot":  {"name", "source_url", "reason"},
    "update_snapshot":  {"snapshot_id", "reason"},
    "stop_snapshot":    {"snapshot_id", "reason"},
    "restart_snapshot": {"snapshot_id", "reason"},
}

VALID_TYPES = set(_REQUIRED)


def load_changes(path: str | Path) -> list[dict]:
    path = Path(path)
    with path.open() as f:
        doc = yaml.safe_load(f) or []
    if not isinstance(doc, list):
        raise ValueError(f"{path}: expected a top-level YAML list, got {type(doc).__name__}")

    for i, change in enumerate(doc):
        if not isinstance(change, dict):
            raise ValueError(f"{path}[{i}]: each change must be a dict")
        t = change.get("type")
        if t not in VALID_TYPES:
            raise ValueError(
                f"{path}[{i}]: unknown change type {t!r}. "
                f"Valid types: {sorted(VALID_TYPES)}"
            )
        missing = _REQUIRED[t] - set(change)
        if missing:
            raise ValueError(f"{path}[{i}] ({t}): missing required keys: {sorted(missing)}")

    return doc


def describe(c: dict) -> str:
    t = c["type"]
    if t == "create_snapshot":
        return f"CREATE heatmap {c['name']!r} for {c['source_url']}"
    if t == "update_snapshot":
        return f"UPDATE heatmap {c['snapshot_id']}"
    if t == "stop_snapshot":
        return f"STOP heatmap {c['snapshot_id']}"
    if t == "restart_snapshot":
        return f"RESTART heatmap {c['snapshot_id']}"
    return f"unknown: {c}"
