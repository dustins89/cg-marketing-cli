"""Pending-changes YAML schema + validation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

VALID_TYPES = {
    "add_negative_keyword",
    "pause_keyword",
    "pause_ad",
    "pause_ad_group",
    "adjust_budget",
    "adjust_bid",
}

VALID_MATCH_TYPES = {"EXACT", "PHRASE", "BROAD"}

REQUIRED_FIELDS: dict[str, set[str]] = {
    "add_negative_keyword": {"scope", "text", "match_type"},
    "pause_keyword": {"ad_group_id", "criterion_id"},
    "pause_ad": {"ad_group_id", "ad_id"},
    "pause_ad_group": {"ad_group_id"},
    "adjust_budget": {"campaign_id", "new_daily_budget_usd"},
    "adjust_bid": {"ad_group_id", "criterion_id", "new_cpc_usd"},
}


@dataclass
class Change:
    raw: dict[str, Any]

    @property
    def type(self) -> str:
        return self.raw["type"]

    @property
    def rationale(self) -> str:
        return self.raw.get("rationale", "")

    def get(self, key, default=None):
        return self.raw.get(key, default)


def load_changes(path: str | Path) -> tuple[str, list[Change]]:
    """Parse + validate. Returns (account, changes). Raises ValueError on invalid."""
    p = Path(path)
    with p.open() as f:
        doc = yaml.safe_load(f)

    if not isinstance(doc, dict):
        raise ValueError("Top-level YAML must be a mapping.")
    if doc.get("version") != 1:
        raise ValueError("Missing or unsupported `version: 1`.")
    account = str(doc.get("account", "")).replace("-", "")
    if not account:
        raise ValueError("Missing `account` (customer ID).")
    raw_changes = doc.get("changes")
    if not isinstance(raw_changes, list) or not raw_changes:
        raise ValueError("`changes` must be a non-empty list.")

    changes: list[Change] = []
    for i, c in enumerate(raw_changes):
        _validate(c, i)
        changes.append(Change(raw=c))
    return account, changes


def _validate(c: dict, idx: int) -> None:
    where = f"changes[{idx}]"
    if not isinstance(c, dict):
        raise ValueError(f"{where} must be a mapping.")
    t = c.get("type")
    if t not in VALID_TYPES:
        raise ValueError(f"{where}.type = {t!r} not in {sorted(VALID_TYPES)}")

    missing = REQUIRED_FIELDS[t] - c.keys()
    if missing:
        raise ValueError(f"{where} ({t}) missing required fields: {sorted(missing)}")

    if t == "add_negative_keyword":
        if c["scope"] not in {"campaign", "ad_group"}:
            raise ValueError(f"{where}.scope must be 'campaign' or 'ad_group'")
        if c["scope"] == "campaign" and not c.get("campaign_id"):
            raise ValueError(f"{where} needs campaign_id when scope=campaign")
        if c["scope"] == "ad_group" and not c.get("ad_group_id"):
            raise ValueError(f"{where} needs ad_group_id when scope=ad_group")
        if c["match_type"] not in VALID_MATCH_TYPES:
            raise ValueError(f"{where}.match_type must be one of {sorted(VALID_MATCH_TYPES)}")


def describe(c: Change) -> str:
    """One-line human description used in the confirmation prompt."""
    t = c.type
    if t == "add_negative_keyword":
        return (f"Add negative keyword [{c.get('match_type')}] {c.get('text')!r} "
                f"to {c.get('scope')} {c.get('campaign_id') or c.get('ad_group_id')}")
    if t == "pause_keyword":
        return f"Pause keyword criterion {c.get('criterion_id')} in ad group {c.get('ad_group_id')}"
    if t == "pause_ad":
        return f"Pause ad {c.get('ad_id')} in ad group {c.get('ad_group_id')}"
    if t == "pause_ad_group":
        return f"Pause ad group {c.get('ad_group_id')}"
    if t == "adjust_budget":
        prev = c.get('previous_daily_budget_usd')
        new = c.get('new_daily_budget_usd')
        return (f"Set daily budget on campaign {c.get('campaign_id')} to ${new}"
                + (f" (from ${prev})" if prev else ""))
    if t == "adjust_bid":
        prev = c.get('previous_cpc_usd')
        new = c.get('new_cpc_usd')
        return (f"Set CPC bid on criterion {c.get('criterion_id')} to ${new}"
                + (f" (from ${prev})" if prev else ""))
    return f"<{t}>"
