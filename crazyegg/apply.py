"""Crazy Egg mutation handlers + interactive apply flow."""
from __future__ import annotations

import datetime as dt
import json

import click
from rich.console import Console

from gads.client import PROJECT_ROOT

from .changes import describe, load_changes
from .client import request

AUDIT_LOG = PROJECT_ROOT / "audit.log"
console = Console()


def _log(entry: dict) -> None:
    entry["ts"] = dt.datetime.now(dt.timezone.utc).isoformat()
    entry["tool"] = "cegg"
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def apply_file(path: str, dry_run: bool, assume_yes: bool) -> None:
    changes = load_changes(path)
    applied = skipped = failed = 0

    console.print(f"\n[bold]{len(changes)}[/bold] change(s) loaded. "
                  f"{'DRY RUN' if dry_run else 'LIVE'}\n")

    for i, c in enumerate(changes, 1):
        console.print(f"\n[{i}/{len(changes)}] {describe(c)}")
        if c.get("reason"):
            console.print(f"  [dim]reason:[/dim] {c['reason']}")

        if dry_run:
            console.print(f"  [dim](dry-run — would call {c['type']})[/dim]")
            continue

        if not assume_yes:
            choice = click.prompt("  Apply? [y/N/q]", default="N", show_default=False).lower()
            if choice == "q":
                console.print("  [yellow]Aborting batch.[/yellow]")
                break
            if choice != "y":
                console.print("  [yellow]Skipped.[/yellow]")
                skipped += 1
                _log({"action": "skip", "change": c})
                continue

        try:
            result = _dispatch(c)
            applied += 1
            console.print("  [green]✓ applied[/green]")
            _log({"action": "apply", "change": c, "status": "ok", "result": result})
        except Exception as e:
            failed += 1
            console.print(f"  [red]✗ failed:[/red] {e}")
            _log({"action": "apply", "change": c, "status": "error", "error": str(e)})

    console.print(f"\nSummary: [green]{applied} applied[/green], "
                  f"[yellow]{skipped} skipped[/yellow], [red]{failed} failed[/red]")


def _dispatch(c: dict) -> dict:
    handlers = {
        "create_snapshot":  _create_snapshot,
        "update_snapshot":  _update_snapshot,
        "stop_snapshot":    _stop_snapshot,
        "restart_snapshot": _restart_snapshot,
    }
    return handlers[c["type"]](c)


def _snapshot_payload(c: dict) -> dict:
    """Build the `snapshot[…]` form fields the Crazy Egg API expects."""
    candidate_fields = (
        "name", "source_url", "max_visits", "expires_at", "starts_at",
        "description", "url_matching_rules", "sampling_ratio", "device",
    )
    payload = {}
    for key in candidate_fields:
        if key in c and c[key] is not None:
            payload[f"snapshot[{key}]"] = c[key]
    return payload


def _create_snapshot(c: dict) -> dict:
    return request("POST", "/snapshots.json", data=_snapshot_payload(c))


def _update_snapshot(c: dict) -> dict:
    return request("PUT", f"/snapshot/{c['snapshot_id']}.json",
                   data={"id": c["snapshot_id"], **_snapshot_payload(c)})


def _stop_snapshot(c: dict) -> dict:
    return request("PUT", f"/snapshot/{c['snapshot_id']}/stop.json",
                   data={"id": c["snapshot_id"]})


def _restart_snapshot(c: dict) -> dict:
    return request("PUT", f"/snapshot/{c['snapshot_id']}/restart.json",
                   data={"id": c["snapshot_id"]})
