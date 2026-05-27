"""GTM read commands — list accounts, containers, workspaces, tags, triggers, variables.

By default reads from the LIVE published version of the container (what's
actually firing on the site). Pass --workspace to read from an unpublished
workspace instead.

Reference: https://developers.google.com/tag-platform/tag-manager/api/v2/reference
"""
from __future__ import annotations

from .client import container_path, workspace_path


# ─── Account / container / workspace listings ─────────────────────────────────

def pull_accounts(service) -> list[dict]:
    resp = service.accounts().list().execute()
    return [
        {
            "account_id": a["accountId"],
            "name": a.get("name"),
            "fingerprint": a.get("fingerprint"),
        }
        for a in resp.get("account", [])
    ]


def pull_containers(service, account_id: str) -> list[dict]:
    resp = service.accounts().containers().list(parent=f"accounts/{account_id}").execute()
    return [
        {
            "container_id": c["containerId"],
            "name": c.get("name"),
            "public_id": c.get("publicId"),
            "usage_context": ",".join(c.get("usageContext", []) or []),
            "domain_name": ",".join(c.get("domainName", []) or []),
        }
        for c in resp.get("container", [])
    ]


def pull_workspaces(service, account_id: str, container_id: str) -> list[dict]:
    parent = container_path(account_id, container_id)
    resp = service.accounts().containers().workspaces().list(parent=parent).execute()
    return [
        {
            "workspace_id": w["workspaceId"],
            "name": w.get("name"),
            "description": w.get("description"),
        }
        for w in resp.get("workspace", [])
    ]


# ─── Live container reads (what's actually firing) ────────────────────────────

def _get_live_version(service, account_id: str, container_id: str) -> dict:
    parent = container_path(account_id, container_id)
    return service.accounts().containers().versions().live(parent=parent).execute()


def pull_live_tags(service, account_id: str, container_id: str) -> list[dict]:
    v = _get_live_version(service, account_id, container_id)
    return [_tag_row(t) for t in v.get("tag", [])]


def pull_live_triggers(service, account_id: str, container_id: str) -> list[dict]:
    v = _get_live_version(service, account_id, container_id)
    return [_trigger_row(t) for t in v.get("trigger", [])]


def pull_live_variables(service, account_id: str, container_id: str) -> list[dict]:
    v = _get_live_version(service, account_id, container_id)
    return [_variable_row(va) for va in v.get("variable", [])]


# ─── Workspace reads (in-progress, unpublished) ───────────────────────────────

def pull_workspace_tags(service, account_id: str, container_id: str, workspace_id: str) -> list[dict]:
    parent = workspace_path(account_id, container_id, workspace_id)
    resp = service.accounts().containers().workspaces().tags().list(parent=parent).execute()
    return [_tag_row(t) for t in resp.get("tag", [])]


def pull_workspace_triggers(service, account_id: str, container_id: str, workspace_id: str) -> list[dict]:
    parent = workspace_path(account_id, container_id, workspace_id)
    resp = service.accounts().containers().workspaces().triggers().list(parent=parent).execute()
    return [_trigger_row(t) for t in resp.get("trigger", [])]


def pull_workspace_variables(service, account_id: str, container_id: str, workspace_id: str) -> list[dict]:
    parent = workspace_path(account_id, container_id, workspace_id)
    resp = service.accounts().containers().workspaces().variables().list(parent=parent).execute()
    return [_variable_row(v) for v in resp.get("variable", [])]


# ─── Conversion-tag diagnostic ────────────────────────────────────────────────

def pull_conversion_diagnostic(service, account_id: str, container_id: str) -> list[dict]:
    """Surface tags likely related to conversions (GA4 events, Ads conversions, etc.)
    so you can quickly answer: "is conversion X actually firing, and on what trigger?"
    """
    v = _get_live_version(service, account_id, container_id)
    triggers_by_id = {t["triggerId"]: t for t in v.get("trigger", [])}

    interesting_types = {
        "gaawe",       # GA4 event
        "gaawc",       # GA4 configuration
        "awct",        # Google Ads conversion tracking
        "sp",          # Google Ads remarketing
        "ua",          # legacy Universal Analytics
        "html",        # custom HTML — often used for conversion pixels
    }

    rows = []
    for t in v.get("tag", []):
        if t.get("type") not in interesting_types:
            continue
        params = {p["key"]: p.get("value") for p in t.get("parameter", []) if "key" in p}
        trigger_names = [
            triggers_by_id.get(tid, {}).get("name", f"<unknown:{tid}>")
            for tid in t.get("firingTriggerId", [])
        ]
        rows.append({
            "tag_id": t.get("tagId"),
            "name": t.get("name"),
            "type": t.get("type"),
            "paused": t.get("paused", False),
            "event_name": params.get("eventName"),
            "measurement_id": params.get("measurementId") or params.get("measurementIdOverride"),
            "conversion_id": params.get("conversionId"),
            "firing_triggers": ", ".join(trigger_names),
        })
    return rows


# ─── Row shapers ──────────────────────────────────────────────────────────────

def _tag_row(t: dict) -> dict:
    return {
        "tag_id": t.get("tagId"),
        "name": t.get("name"),
        "type": t.get("type"),
        "paused": t.get("paused", False),
        "firing_trigger_ids": ", ".join(t.get("firingTriggerId", []) or []),
        "blocking_trigger_ids": ", ".join(t.get("blockingTriggerId", []) or []),
    }


def _trigger_row(t: dict) -> dict:
    return {
        "trigger_id": t.get("triggerId"),
        "name": t.get("name"),
        "type": t.get("type"),
    }


def _variable_row(v: dict) -> dict:
    return {
        "variable_id": v.get("variableId"),
        "name": v.get("name"),
        "type": v.get("type"),
    }


# ─── New resources: folders / built-ins / templates / environments / zones / clients / versions ─

def pull_folders(service, account_id: str, container_id: str,
                workspace_id: str) -> list[dict]:
    """List Folders inside a workspace (organizational grouping for tags/triggers/vars)."""
    parent = workspace_path(account_id, container_id, workspace_id)
    resp = service.accounts().containers().workspaces().folders().list(parent=parent).execute()
    return [{
        "folder_id": f.get("folderId"),
        "name": f.get("name"),
        "notes": (f.get("notes") or "")[:200],
    } for f in resp.get("folder", [])]


def pull_builtin_variables(service, account_id: str, container_id: str,
                          workspace_id: str) -> list[dict]:
    """List Built-In Variables enabled in a workspace."""
    parent = workspace_path(account_id, container_id, workspace_id)
    resp = service.accounts().containers().workspaces().built_in_variables().list(
        parent=parent
    ).execute()
    return [{
        "name": v.get("name"),
        "type": v.get("type"),
    } for v in resp.get("builtInVariable", [])]


def pull_templates(service, account_id: str, container_id: str,
                  workspace_id: str) -> list[dict]:
    """List Custom Templates in a workspace."""
    parent = workspace_path(account_id, container_id, workspace_id)
    resp = service.accounts().containers().workspaces().templates().list(parent=parent).execute()
    return [{
        "template_id": t.get("templateId"),
        "name": t.get("name"),
        "gallery_reference_host": (t.get("galleryReference") or {}).get("host"),
        "gallery_repository": (t.get("galleryReference") or {}).get("repository"),
        "gallery_version": (t.get("galleryReference") or {}).get("version"),
        "gallery_owner": (t.get("galleryReference") or {}).get("owner"),
        "gallery_signature": (t.get("galleryReference") or {}).get("signature"),
    } for t in resp.get("template", [])]


def pull_environments(service, account_id: str, container_id: str) -> list[dict]:
    """List Environments (preview, latest, custom) for a container."""
    parent = container_path(account_id, container_id)
    resp = service.accounts().containers().environments().list(parent=parent).execute()
    return [{
        "environment_id": e.get("environmentId"),
        "name": e.get("name"),
        "type": e.get("type"),
        "description": (e.get("description") or "")[:200],
        "url": e.get("url"),
        "container_version_id": e.get("containerVersionId"),
        "enable_debug": e.get("enableDebug"),
    } for e in resp.get("environment", [])]


def pull_zones(service, account_id: str, container_id: str,
              workspace_id: str) -> list[dict]:
    """List Zones (multi-container delegation rules) in a workspace."""
    parent = workspace_path(account_id, container_id, workspace_id)
    resp = service.accounts().containers().workspaces().zones().list(parent=parent).execute()
    return [{
        "zone_id": z.get("zoneId"),
        "name": z.get("name"),
        "child_containers": ", ".join(
            (c.get("publicId") or "")
            for c in (z.get("childContainer") or [])
        ),
        "boundary_count": len((z.get("boundary") or {}).get("customEvaluationTriggerId") or []),
    } for z in resp.get("zone", [])]


def pull_clients(service, account_id: str, container_id: str,
                workspace_id: str) -> list[dict]:
    """List server-side GTM Clients (sGTM only)."""
    parent = workspace_path(account_id, container_id, workspace_id)
    resp = service.accounts().containers().workspaces().clients().list(parent=parent).execute()
    return [{
        "client_id": c.get("clientId"),
        "name": c.get("name"),
        "type": c.get("type"),
        "priority": c.get("priority"),
        "paused": c.get("paused", False),
    } for c in resp.get("client", [])]


def pull_version_headers(service, account_id: str, container_id: str,
                        max_pages: int = 5) -> list[dict]:
    """Container Version headers — publish history (one row per published version)."""
    parent = container_path(account_id, container_id)
    rows = []
    page_token = None
    for _ in range(max_pages):
        params = {"parent": parent}
        if page_token:
            params["pageToken"] = page_token
        resp = service.accounts().containers().version_headers().list(**params).execute()
        for v in resp.get("containerVersionHeader", []):
            rows.append({
                "container_version_id": v.get("containerVersionId"),
                "name": v.get("name"),
                "deleted": v.get("deleted", False),
                "tag_count": int(v.get("numTags", 0) or 0),
                "trigger_count": int(v.get("numTriggers", 0) or 0),
                "variable_count": int(v.get("numVariables", 0) or 0),
                "macro_count": int(v.get("numMacros", 0) or 0),
                "rule_count": int(v.get("numRules", 0) or 0),
                "zone_count": int(v.get("numZones", 0) or 0),
                "transformation_count": int(v.get("numTransformations", 0) or 0),
                "custom_template_count": int(v.get("numCustomTemplates", 0) or 0),
                "client_count": int(v.get("numClients", 0) or 0),
                "gtag_config_count": int(v.get("numGtagConfigs", 0) or 0),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return rows


def pull_version_detail(service, account_id: str, container_id: str,
                       version_id: str) -> dict:
    """Detail of a specific container version (for diffing)."""
    path = (f"accounts/{account_id}/containers/{container_id}/versions/{version_id}")
    return service.accounts().containers().versions().get(path=path).execute()


def pull_workspace_status(service, account_id: str, container_id: str,
                         workspace_id: str) -> dict:
    """Workspace change-set status — what's pending publish, sync conflicts."""
    parent = workspace_path(account_id, container_id, workspace_id)
    resp = service.accounts().containers().workspaces().getStatus(path=parent).execute()
    return {
        "workspace_path": parent,
        "merge_conflicts": resp.get("mergeConflict") or [],
        "workspace_changes": resp.get("workspaceChange") or [],
        "sync_status": resp.get("syncStatus") or {},
    }


def pull_user_permissions(service, account_id: str) -> list[dict]:
    """List users with access to the account + their per-container permissions."""
    parent = f"accounts/{account_id}"
    resp = service.accounts().user_permissions().list(parent=parent).execute()
    rows = []
    for u in resp.get("userPermission", []):
        per_container = u.get("containerAccess") or []
        rows.append({
            "email": u.get("emailAddress"),
            "account_access": (u.get("accountAccess") or {}).get("permission"),
            "container_count": len(per_container),
            "container_permissions": ", ".join(
                f"{c.get('containerId')}:{c.get('permission')}"
                for c in per_container[:5]
            ),
            "path": u.get("path"),
        })
    return rows


COLUMNS = {
    "accounts": ["account_id", "name", "fingerprint"],
    "containers": ["container_id", "name", "public_id", "usage_context", "domain_name"],
    "workspaces": ["workspace_id", "name", "description"],
    "tags": ["tag_id", "name", "type", "paused", "firing_trigger_ids", "blocking_trigger_ids"],
    "triggers": ["trigger_id", "name", "type"],
    "variables": ["variable_id", "name", "type"],
    "conversions": ["tag_id", "name", "type", "paused", "event_name", "measurement_id",
                    "conversion_id", "firing_triggers"],
    "folders": ["folder_id", "name", "notes"],
    "builtin-variables": ["name", "type"],
    "templates": ["template_id", "name", "gallery_repository", "gallery_owner",
                  "gallery_version", "gallery_signature"],
    "environments": ["environment_id", "name", "type", "url",
                     "container_version_id", "enable_debug", "description"],
    "zones": ["zone_id", "name", "child_containers", "boundary_count"],
    "clients": ["client_id", "name", "type", "priority", "paused"],
    "version-headers": ["container_version_id", "name", "deleted",
                        "tag_count", "trigger_count", "variable_count",
                        "client_count", "transformation_count",
                        "custom_template_count", "zone_count"],
    "user-permissions": ["email", "account_access", "container_count",
                         "container_permissions"],
}
