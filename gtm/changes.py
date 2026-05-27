"""Schema + validation for proposed GTM changes (YAML).

Mirrors gads/changes.py: a list of dicts at the top level, each with `type` and
type-specific keys. apply.py routes by `type`. Keep change types narrow — add
new ones only when a real proposed_changes.yaml needs one.

Supported types
───────────────
- pause_tag           — set tag.paused = true
- unpause_tag         — set tag.paused = false
- update_tag_name     — rename a tag
- add_trigger         — create a new trigger in a workspace
- add_ga4_event_tag   — create a GA4 event tag wired to one or more triggers
- publish_workspace   — create a version from the workspace and publish it
"""
from __future__ import annotations

from pathlib import Path

import yaml


_REQUIRED = {
    "pause_tag":                 {"workspace_id", "tag_id", "reason"},
    "unpause_tag":               {"workspace_id", "tag_id", "reason"},
    "update_tag_name":           {"workspace_id", "tag_id", "new_name", "reason"},
    "update_tag_triggers":       {"workspace_id", "tag_id", "firing_trigger_ids", "reason"},
    "add_trigger":               {"workspace_id", "name", "trigger_type", "reason"},
    "add_custom_event_trigger":  {"workspace_id", "name", "event_name", "reason"},
    "add_html_tag":              {"workspace_id", "name", "html", "firing_trigger_ids", "reason"},
    "add_ga4_event_tag":         {"workspace_id", "name", "measurement_id", "event_name",
                                  "firing_trigger_ids", "reason"},
    "publish_workspace":         {"workspace_id", "name", "reason"},
}

VALID_TYPES = set(_REQUIRED)


def load_changes(path: str | Path) -> list[dict]:
    """Read + validate a YAML changes file. Returns the list of changes."""
    path = Path(path)
    with path.open() as f:
        doc = yaml.safe_load(f) or []
    if not isinstance(doc, list):
        raise ValueError(f"{path}: expected a top-level YAML list, got {type(doc).__name__}")

    for i, change in enumerate(doc):
        if not isinstance(change, dict):
            raise ValueError(f"{path}[{i}]: each change must be a dict, got {type(change).__name__}")
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


def describe(change: dict) -> str:
    """One-line human description for the per-change confirmation prompt."""
    t = change["type"]
    if t == "pause_tag":
        return f"PAUSE tag {change['tag_id']} in workspace {change['workspace_id']}"
    if t == "unpause_tag":
        return f"UNPAUSE tag {change['tag_id']} in workspace {change['workspace_id']}"
    if t == "update_tag_name":
        return f"RENAME tag {change['tag_id']} → {change['new_name']!r}"
    if t == "update_tag_triggers":
        triggers = ",".join(str(x) for x in change["firing_trigger_ids"])
        return f"REPOINT tag {change['tag_id']} → triggers=[{triggers}]"
    if t == "add_trigger":
        return f"ADD trigger {change['name']!r} (type={change['trigger_type']}) in workspace {change['workspace_id']}"
    if t == "add_custom_event_trigger":
        return f"ADD custom-event trigger {change['name']!r} (event={change['event_name']!r}) in workspace {change['workspace_id']}"
    if t == "add_html_tag":
        return f"ADD Custom HTML tag {change['name']!r} in workspace {change['workspace_id']} ({len(change['html'])} chars of JS)"
    if t == "add_ga4_event_tag":
        triggers = ",".join(str(x) for x in change["firing_trigger_ids"])
        return (f"ADD GA4 event tag {change['name']!r} → event={change['event_name']!r} "
                f"measurement_id={change['measurement_id']} triggers=[{triggers}]")
    if t == "publish_workspace":
        return f"PUBLISH workspace {change['workspace_id']} as version {change['name']!r}"
    return f"unknown: {change}"
