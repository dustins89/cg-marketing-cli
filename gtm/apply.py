"""GTM mutation handlers + interactive apply flow.

Mirrors gads/apply.py: load + validate the YAML, walk each change, prompt y/N/q,
dispatch to a handler, log every attempt to ~/marketing-cli/audit.log.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import click
from rich.console import Console

from gads.client import PROJECT_ROOT

from .changes import describe, load_changes
from .client import workspace_path

AUDIT_LOG = PROJECT_ROOT / "audit.log"
console = Console()


def _log(entry: dict) -> None:
    entry["ts"] = dt.datetime.now(dt.timezone.utc).isoformat()
    entry["tool"] = "gtm"
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def apply_file(service, account_id: str, container_id: str, path: str,
               dry_run: bool, assume_yes: bool) -> None:
    changes = load_changes(path)
    applied = skipped = failed = 0

    console.print(
        f"\n[bold]{len(changes)}[/bold] change(s) loaded for "
        f"account {account_id} / container {container_id}. "
        f"{'DRY RUN' if dry_run else 'LIVE'}\n"
    )

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
            result = _dispatch(service, account_id, container_id, c)
            applied += 1
            console.print("  [green]✓ applied[/green]")
            _log({"action": "apply", "change": c, "status": "ok", "result": result})
        except Exception as e:
            failed += 1
            console.print(f"  [red]✗ failed:[/red] {e}")
            _log({"action": "apply", "change": c, "status": "error", "error": str(e)})

    console.print(
        f"\nSummary: [green]{applied} applied[/green], "
        f"[yellow]{skipped} skipped[/yellow], [red]{failed} failed[/red]"
    )


def _dispatch(service, account_id: str, container_id: str, c: dict) -> dict:
    handlers = {
        "pause_tag":                _pause_tag,
        "unpause_tag":              _unpause_tag,
        "update_tag_name":          _update_tag_name,
        "update_tag_triggers":      _update_tag_triggers,
        "add_trigger":              _add_trigger,
        "add_custom_event_trigger": _add_custom_event_trigger,
        "add_html_tag":             _add_html_tag,
        "add_ga4_event_tag":        _add_ga4_event_tag,
        "publish_workspace":        _publish_workspace,
    }
    _resolve_trigger_refs(service, account_id, container_id, c)
    return handlers[c["type"]](service, account_id, container_id, c)


def _resolve_trigger_refs(service, account_id, container_id, c) -> None:
    """Resolve `@trigger:NAME` references in firing_trigger_ids by looking up
    triggers in the target workspace. Mutates c in place."""
    refs = c.get("firing_trigger_ids")
    if not refs or not isinstance(refs, list):
        return
    if not any(isinstance(r, str) and r.startswith("@trigger:") for r in refs):
        return
    parent = workspace_path(account_id, container_id, c["workspace_id"])
    triggers = service.accounts().containers().workspaces().triggers().list(parent=parent).execute()
    by_name = {t["name"]: t["triggerId"] for t in triggers.get("trigger", [])}
    resolved = []
    for r in refs:
        if isinstance(r, str) and r.startswith("@trigger:"):
            name = r.split(":", 1)[1]
            if name not in by_name:
                raise RuntimeError(f"Could not resolve @trigger:{name} — no trigger with that name in workspace {c['workspace_id']}. "
                                   f"Available: {sorted(by_name)}")
            resolved.append(by_name[name])
        else:
            resolved.append(r)
    c["firing_trigger_ids"] = resolved


# ─── Tag mutations ────────────────────────────────────────────────────────────

def _tag_path(account_id, container_id, workspace_id, tag_id) -> str:
    return f"{workspace_path(account_id, container_id, workspace_id)}/tags/{tag_id}"


def _set_tag_field(service, account_id, container_id, c, field, value) -> dict:
    path = _tag_path(account_id, container_id, c["workspace_id"], c["tag_id"])
    tag = service.accounts().containers().workspaces().tags().get(path=path).execute()
    tag[field] = value
    updated = service.accounts().containers().workspaces().tags().update(
        path=path, body=tag, fingerprint=tag.get("fingerprint"),
    ).execute()
    return {"tag_id": updated.get("tagId"), "name": updated.get("name"), field: updated.get(field)}


def _pause_tag(service, account_id, container_id, c) -> dict:
    return _set_tag_field(service, account_id, container_id, c, "paused", True)


def _unpause_tag(service, account_id, container_id, c) -> dict:
    return _set_tag_field(service, account_id, container_id, c, "paused", False)


def _update_tag_name(service, account_id, container_id, c) -> dict:
    return _set_tag_field(service, account_id, container_id, c, "name", c["new_name"])


def _update_tag_triggers(service, account_id, container_id, c) -> dict:
    triggers = [str(t) for t in c["firing_trigger_ids"]]
    return _set_tag_field(service, account_id, container_id, c, "firingTriggerId", triggers)


# ─── Trigger creation ─────────────────────────────────────────────────────────

def _add_custom_event_trigger(service, account_id, container_id, c) -> dict:
    """Create a Custom Event trigger that fires when a dataLayer push has the
    given event name. Optional `page_url_contains` adds a Page URL filter so
    the trigger only fires on matching URLs."""
    parent = workspace_path(account_id, container_id, c["workspace_id"])
    body = {
        "name": c["name"],
        "type": "customEvent",
        "customEventFilter": [
            {
                "type": "equals",
                "parameter": [
                    {"type": "template", "key": "arg0", "value": "{{_event}}"},
                    {"type": "template", "key": "arg1", "value": c["event_name"]},
                ],
            }
        ],
    }
    if c.get("page_url_contains"):
        body["filter"] = [
            {
                "type": "contains",
                "parameter": [
                    {"type": "template", "key": "arg0", "value": "{{Page URL}}"},
                    {"type": "template", "key": "arg1", "value": c["page_url_contains"]},
                ],
            }
        ]
    created = service.accounts().containers().workspaces().triggers().create(
        parent=parent, body=body,
    ).execute()
    return {"trigger_id": created.get("triggerId"), "name": created.get("name")}


def _add_html_tag(service, account_id, container_id, c) -> dict:
    """Create a Custom HTML tag with arbitrary JS, fired by the given triggers."""
    parent = workspace_path(account_id, container_id, c["workspace_id"])
    body = {
        "name": c["name"],
        "type": "html",
        "parameter": [
            {"type": "template", "key": "html", "value": c["html"]},
            {"type": "boolean", "key": "supportDocumentWrite", "value": "false"},
        ],
        "firingTriggerId": [str(tid) for tid in c["firing_trigger_ids"]],
    }
    created = service.accounts().containers().workspaces().tags().create(
        parent=parent, body=body,
    ).execute()
    return {"tag_id": created.get("tagId"), "name": created.get("name")}


def _add_trigger(service, account_id, container_id, c) -> dict:
    parent = workspace_path(account_id, container_id, c["workspace_id"])
    body = {
        "name": c["name"],
        "type": c["trigger_type"],
    }
    # Optional GTM trigger fields the proposer can pass through
    for key in ("filter", "autoEventFilter", "customEventFilter",
                "selector", "uniqueTriggerId", "waitForTags",
                "checkValidation", "waitForTagsTimeout"):
        if key in c:
            body[key] = c[key]
    created = service.accounts().containers().workspaces().triggers().create(
        parent=parent, body=body,
    ).execute()
    return {"trigger_id": created.get("triggerId"), "name": created.get("name")}


# ─── GA4 event tag creation ───────────────────────────────────────────────────

def _add_ga4_event_tag(service, account_id, container_id, c) -> dict:
    """Create a GA4 event tag wired to one or more existing triggers."""
    parent = workspace_path(account_id, container_id, c["workspace_id"])
    parameters = [
        {"type": "template", "key": "eventName", "value": c["event_name"]},
        {"type": "template", "key": "measurementIdOverride", "value": c["measurement_id"]},
    ]
    # Pass-through event parameters: list of {name, value}
    extra = c.get("event_parameters") or []
    if extra:
        parameters.append({
            "type": "list",
            "key": "eventParameters",
            "list": [
                {"type": "map", "map": [
                    {"type": "template", "key": "name", "value": ep["name"]},
                    {"type": "template", "key": "value", "value": str(ep["value"])},
                ]}
                for ep in extra
            ],
        })
    body = {
        "name": c["name"],
        "type": "gaawe",
        "parameter": parameters,
        "firingTriggerId": [str(tid) for tid in c["firing_trigger_ids"]],
    }
    created = service.accounts().containers().workspaces().tags().create(
        parent=parent, body=body,
    ).execute()
    return {"tag_id": created.get("tagId"), "name": created.get("name")}


# ─── Workspace publish ────────────────────────────────────────────────────────

def _publish_workspace(service, account_id, container_id, c) -> dict:
    """Create a version from the workspace, then publish it."""
    parent = workspace_path(account_id, container_id, c["workspace_id"])
    create_resp = service.accounts().containers().workspaces().create_version(
        path=parent,
        body={"name": c["name"], "notes": c.get("reason")},
    ).execute()
    version = create_resp.get("containerVersion") or {}
    if not version:
        raise RuntimeError(f"create_version returned no containerVersion: {create_resp}")
    version_path = version.get("path")
    publish_resp = service.accounts().containers().versions().publish(path=version_path).execute()
    return {
        "version_id": version.get("containerVersionId"),
        "version_path": version_path,
        "compiler_error": publish_resp.get("compilerError"),
    }
