"""Mutation handlers + interactive apply flow."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import click
from rich.console import Console

from .changes import Change, describe, load_changes
from .client import PROJECT_ROOT

AUDIT_LOG = PROJECT_ROOT / "audit.log"
console = Console()


def _log(entry: dict) -> None:
    entry["ts"] = dt.datetime.now(dt.timezone.utc).isoformat()
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def apply_file(client, path: str, dry_run: bool, assume_yes: bool) -> None:
    account, changes = load_changes(path)
    applied = skipped = failed = 0

    console.print(f"\n[bold]{len(changes)}[/bold] change(s) loaded for account {account}. "
                  f"{'DRY RUN' if dry_run else 'LIVE'}\n")

    for i, c in enumerate(changes, 1):
        header = f"[{i}/{len(changes)}] {describe(c)}"
        console.print(f"\n{header}")
        if c.rationale:
            console.print(f"  [dim]rationale:[/dim] {c.rationale}")

        if dry_run:
            console.print(f"  [dim](dry-run — would call {c.type})[/dim]")
            continue

        if not assume_yes:
            choice = click.prompt("  Apply? [y/N/q]", default="N", show_default=False).lower()
            if choice == "q":
                console.print("  [yellow]Aborting batch.[/yellow]")
                break
            if choice != "y":
                console.print("  [yellow]Skipped.[/yellow]")
                skipped += 1
                _log({"action": "skip", "change": c.raw})
                continue

        try:
            _dispatch(client, account, c)
            applied += 1
            console.print("  [green]✓ applied[/green]")
            _log({"action": "apply", "change": c.raw, "status": "ok"})
        except Exception as e:
            failed += 1
            console.print(f"  [red]✗ failed:[/red] {e}")
            _log({"action": "apply", "change": c.raw, "status": "error", "error": str(e)})

    console.print(f"\nSummary: [green]{applied} applied[/green], "
                  f"[yellow]{skipped} skipped[/yellow], [red]{failed} failed[/red]")


def _dispatch(client, customer_id: str, c: Change) -> None:
    handlers = {
        "add_negative_keyword": _add_negative_keyword,
        "pause_keyword": _pause_keyword,
        "pause_ad": _pause_ad,
        "pause_ad_group": _pause_ad_group,
        "adjust_budget": _adjust_budget,
        "adjust_bid": _adjust_bid,
    }
    handlers[c.type](client, customer_id, c)


def _add_negative_keyword(client, customer_id: str, c: Change) -> None:
    match_enum = client.enums.KeywordMatchTypeEnum[c.get("match_type")]
    if c.get("scope") == "campaign":
        service = client.get_service("CampaignCriterionService")
        op = client.get_type("CampaignCriterionOperation")
        crit = op.create
        crit.campaign = client.get_service("CampaignService").campaign_path(
            customer_id, c.get("campaign_id")
        )
        crit.negative = True
        crit.keyword.text = c.get("text")
        crit.keyword.match_type = match_enum
        service.mutate_campaign_criteria(customer_id=customer_id, operations=[op])
    else:
        service = client.get_service("AdGroupCriterionService")
        op = client.get_type("AdGroupCriterionOperation")
        crit = op.create
        crit.ad_group = client.get_service("AdGroupService").ad_group_path(
            customer_id, c.get("ad_group_id")
        )
        crit.negative = True
        crit.keyword.text = c.get("text")
        crit.keyword.match_type = match_enum
        service.mutate_ad_group_criteria(customer_id=customer_id, operations=[op])


def _pause_keyword(client, customer_id: str, c: Change) -> None:
    service = client.get_service("AdGroupCriterionService")
    op = client.get_type("AdGroupCriterionOperation")
    crit = op.update
    crit.resource_name = service.ad_group_criterion_path(
        customer_id, c.get("ad_group_id"), c.get("criterion_id")
    )
    crit.status = client.enums.AdGroupCriterionStatusEnum.PAUSED
    client.copy_from(op.update_mask, _field_mask(["status"]))
    service.mutate_ad_group_criteria(customer_id=customer_id, operations=[op])


def _pause_ad(client, customer_id: str, c: Change) -> None:
    service = client.get_service("AdGroupAdService")
    op = client.get_type("AdGroupAdOperation")
    ad = op.update
    ad.resource_name = service.ad_group_ad_path(
        customer_id, c.get("ad_group_id"), c.get("ad_id")
    )
    ad.status = client.enums.AdGroupAdStatusEnum.PAUSED
    client.copy_from(op.update_mask, _field_mask(["status"]))
    service.mutate_ad_group_ads(customer_id=customer_id, operations=[op])


def _pause_ad_group(client, customer_id: str, c: Change) -> None:
    service = client.get_service("AdGroupService")
    op = client.get_type("AdGroupOperation")
    ag = op.update
    ag.resource_name = service.ad_group_path(customer_id, c.get("ad_group_id"))
    ag.status = client.enums.AdGroupStatusEnum.PAUSED
    client.copy_from(op.update_mask, _field_mask(["status"]))
    service.mutate_ad_groups(customer_id=customer_id, operations=[op])


def _adjust_budget(client, customer_id: str, c: Change) -> None:
    """Updates the budget resource that the campaign points at."""
    ga_service = client.get_service("GoogleAdsService")
    campaign_id = c.get("campaign_id")
    rows = list(ga_service.search(
        customer_id=customer_id,
        query=f"SELECT campaign_budget.resource_name FROM campaign WHERE campaign.id = {campaign_id}",
    ))
    if not rows:
        raise RuntimeError(f"Campaign {campaign_id} not found")
    budget_rn = rows[0].campaign_budget.resource_name

    service = client.get_service("CampaignBudgetService")
    op = client.get_type("CampaignBudgetOperation")
    budget = op.update
    budget.resource_name = budget_rn
    budget.amount_micros = int(round(float(c.get("new_daily_budget_usd")) * 1_000_000))
    client.copy_from(op.update_mask, _field_mask(["amount_micros"]))
    service.mutate_campaign_budgets(customer_id=customer_id, operations=[op])


def _adjust_bid(client, customer_id: str, c: Change) -> None:
    service = client.get_service("AdGroupCriterionService")
    op = client.get_type("AdGroupCriterionOperation")
    crit = op.update
    crit.resource_name = service.ad_group_criterion_path(
        customer_id, c.get("ad_group_id"), c.get("criterion_id")
    )
    crit.cpc_bid_micros = int(round(float(c.get("new_cpc_usd")) * 1_000_000))
    client.copy_from(op.update_mask, _field_mask(["cpc_bid_micros"]))
    service.mutate_ad_group_criteria(customer_id=customer_id, operations=[op])


def _field_mask(paths: list[str]):
    """Build a google.protobuf.FieldMask from string paths."""
    from google.protobuf.field_mask_pb2 import FieldMask
    return FieldMask(paths=paths)
