"""gtm — Click CLI entrypoint for Google Tag Manager."""
from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning, module="google.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")

import click
from rich.console import Console

from . import __version__
from . import pull as pull_mod
from . import apply as apply_mod
from .client import get_account_id, get_container_id, get_service
from .format import emit

console = Console()


@click.group(help="Personal Google Tag Manager CLI — read containers + apply reviewed changes.")
@click.version_option(__version__, prog_name="gtm")
def cli() -> None:
    pass


def _format_opt(f):
    return click.option(
        "--format", "fmt", type=click.Choice(["table", "json"]), default="table",
        help="Output format.",
    )(f)


# ─── account / container discovery ────────────────────────────────────────────

@cli.command("accounts")
@_format_opt
def accounts_cmd(fmt):
    """List GTM accounts you have access to."""
    rows = pull_mod.pull_accounts(get_service())
    emit(rows, pull_mod.COLUMNS["accounts"], fmt, title=f"GTM accounts ({len(rows)})")


@cli.command("containers")
@click.option("--account", "account_id", default=None,
              help="Account ID (defaults to gtm_account_id from yaml).")
@_format_opt
def containers_cmd(account_id, fmt):
    """List containers in an account."""
    aid = account_id or get_account_id()
    rows = pull_mod.pull_containers(get_service(), aid)
    emit(rows, pull_mod.COLUMNS["containers"], fmt, title=f"Containers in account {aid} ({len(rows)})")


@cli.command("workspaces")
@click.option("--account", "account_id", default=None)
@click.option("--container", "container_id", default=None)
@_format_opt
def workspaces_cmd(account_id, container_id, fmt):
    """List workspaces in a container."""
    aid = account_id or get_account_id()
    cid = container_id or get_container_id()
    rows = pull_mod.pull_workspaces(get_service(), aid, cid)
    emit(rows, pull_mod.COLUMNS["workspaces"], fmt, title=f"Workspaces ({len(rows)})")


# ─── pull (live by default, or from a workspace) ──────────────────────────────

@cli.group("pull")
def pull_group() -> None:
    """Read tags / triggers / variables from the live container or a workspace."""


def _common_pull_opts(f):
    f = click.option("--container", "container_id", default=None)(f)
    f = click.option("--account", "account_id", default=None)(f)
    f = click.option("--workspace", "workspace_id", default=None,
                     help="If set, read from this workspace instead of the live published version.")(f)
    f = _format_opt(f)
    return f


def _resolve(account_id, container_id):
    return account_id or get_account_id(), container_id or get_container_id()


@pull_group.command("tags")
@_common_pull_opts
def pull_tags_cmd(account_id, container_id, workspace_id, fmt):
    aid, cid = _resolve(account_id, container_id)
    service = get_service()
    rows = (
        pull_mod.pull_workspace_tags(service, aid, cid, workspace_id)
        if workspace_id else
        pull_mod.pull_live_tags(service, aid, cid)
    )
    src = f"workspace {workspace_id}" if workspace_id else "LIVE"
    emit(rows, pull_mod.COLUMNS["tags"], fmt, title=f"Tags ({len(rows)}) — {src}")


@pull_group.command("triggers")
@_common_pull_opts
def pull_triggers_cmd(account_id, container_id, workspace_id, fmt):
    aid, cid = _resolve(account_id, container_id)
    service = get_service()
    rows = (
        pull_mod.pull_workspace_triggers(service, aid, cid, workspace_id)
        if workspace_id else
        pull_mod.pull_live_triggers(service, aid, cid)
    )
    src = f"workspace {workspace_id}" if workspace_id else "LIVE"
    emit(rows, pull_mod.COLUMNS["triggers"], fmt, title=f"Triggers ({len(rows)}) — {src}")


@pull_group.command("variables")
@_common_pull_opts
def pull_variables_cmd(account_id, container_id, workspace_id, fmt):
    aid, cid = _resolve(account_id, container_id)
    service = get_service()
    rows = (
        pull_mod.pull_workspace_variables(service, aid, cid, workspace_id)
        if workspace_id else
        pull_mod.pull_live_variables(service, aid, cid)
    )
    src = f"workspace {workspace_id}" if workspace_id else "LIVE"
    emit(rows, pull_mod.COLUMNS["variables"], fmt, title=f"Variables ({len(rows)}) — {src}")


@pull_group.command("conversions")
@click.option("--account", "account_id", default=None)
@click.option("--container", "container_id", default=None)
@_format_opt
def pull_conversions_cmd(account_id, container_id, fmt):
    """Diagnostic: surface live tags related to GA4/Ads conversion tracking."""
    aid, cid = _resolve(account_id, container_id)
    rows = pull_mod.pull_conversion_diagnostic(get_service(), aid, cid)
    emit(rows, pull_mod.COLUMNS["conversions"], fmt,
         title=f"Conversion-related tags ({len(rows)}) — LIVE")


def _resolve_with_ws(account_id, container_id, workspace_id):
    """Some endpoints need a workspace; default to highest-id (usually 'Default')."""
    aid, cid = _resolve(account_id, container_id)
    wid = workspace_id
    if not wid:
        ws = pull_mod.pull_workspaces(get_service(), aid, cid)
        if not ws:
            raise click.ClickException("No workspaces found.")
        # Pick the lowest workspace_id (the default workspace) — most users only have one.
        wid = sorted(ws, key=lambda w: int(w["workspace_id"]))[0]["workspace_id"]
    return aid, cid, wid


@pull_group.command("folders")
@click.option("--account", "account_id", default=None)
@click.option("--container", "container_id", default=None)
@click.option("--workspace", "workspace_id", default=None)
@_format_opt
def pull_folders_cmd(account_id, container_id, workspace_id, fmt):
    """List Folders in a workspace."""
    aid, cid, wid = _resolve_with_ws(account_id, container_id, workspace_id)
    rows = pull_mod.pull_folders(get_service(), aid, cid, wid)
    emit(rows, pull_mod.COLUMNS["folders"], fmt,
         title=f"Folders ({len(rows)}) — workspace {wid}")


@pull_group.command("builtin-variables")
@click.option("--account", "account_id", default=None)
@click.option("--container", "container_id", default=None)
@click.option("--workspace", "workspace_id", default=None)
@_format_opt
def pull_builtin_variables_cmd(account_id, container_id, workspace_id, fmt):
    """List Built-In Variables enabled in a workspace."""
    aid, cid, wid = _resolve_with_ws(account_id, container_id, workspace_id)
    rows = pull_mod.pull_builtin_variables(get_service(), aid, cid, wid)
    emit(rows, pull_mod.COLUMNS["builtin-variables"], fmt,
         title=f"Built-in variables ({len(rows)}) — workspace {wid}")


@pull_group.command("templates")
@click.option("--account", "account_id", default=None)
@click.option("--container", "container_id", default=None)
@click.option("--workspace", "workspace_id", default=None)
@_format_opt
def pull_templates_cmd(account_id, container_id, workspace_id, fmt):
    """List Custom Templates in a workspace."""
    aid, cid, wid = _resolve_with_ws(account_id, container_id, workspace_id)
    rows = pull_mod.pull_templates(get_service(), aid, cid, wid)
    emit(rows, pull_mod.COLUMNS["templates"], fmt,
         title=f"Templates ({len(rows)}) — workspace {wid}")


@pull_group.command("environments")
@click.option("--account", "account_id", default=None)
@click.option("--container", "container_id", default=None)
@_format_opt
def pull_environments_cmd(account_id, container_id, fmt):
    """List Environments (preview, latest, custom)."""
    aid, cid = _resolve(account_id, container_id)
    rows = pull_mod.pull_environments(get_service(), aid, cid)
    emit(rows, pull_mod.COLUMNS["environments"], fmt,
         title=f"Environments ({len(rows)})")


@pull_group.command("zones")
@click.option("--account", "account_id", default=None)
@click.option("--container", "container_id", default=None)
@click.option("--workspace", "workspace_id", default=None)
@_format_opt
def pull_zones_cmd(account_id, container_id, workspace_id, fmt):
    """List Zones (multi-container delegation)."""
    aid, cid, wid = _resolve_with_ws(account_id, container_id, workspace_id)
    rows = pull_mod.pull_zones(get_service(), aid, cid, wid)
    emit(rows, pull_mod.COLUMNS["zones"], fmt,
         title=f"Zones ({len(rows)}) — workspace {wid}")


@pull_group.command("clients")
@click.option("--account", "account_id", default=None)
@click.option("--container", "container_id", default=None)
@click.option("--workspace", "workspace_id", default=None)
@_format_opt
def pull_clients_cmd(account_id, container_id, workspace_id, fmt):
    """List server-side GTM Clients (sGTM only)."""
    aid, cid, wid = _resolve_with_ws(account_id, container_id, workspace_id)
    rows = pull_mod.pull_clients(get_service(), aid, cid, wid)
    emit(rows, pull_mod.COLUMNS["clients"], fmt,
         title=f"Clients ({len(rows)}) — workspace {wid}")


@pull_group.command("version-headers")
@click.option("--account", "account_id", default=None)
@click.option("--container", "container_id", default=None)
@click.option("--pages", "max_pages", default=5, type=int,
              help="Pagination cap (default 5).")
@_format_opt
def pull_version_headers_cmd(account_id, container_id, max_pages, fmt):
    """Container version publish history."""
    aid, cid = _resolve(account_id, container_id)
    rows = pull_mod.pull_version_headers(get_service(), aid, cid, max_pages=max_pages)
    emit(rows, pull_mod.COLUMNS["version-headers"], fmt,
         title=f"Version headers ({len(rows)})")


@pull_group.command("version")
@click.option("--account", "account_id", default=None)
@click.option("--container", "container_id", default=None)
@click.argument("version_id")
def pull_version_cmd(account_id, container_id, version_id):
    """Detail of a specific published container version (JSON for diffing)."""
    import json as _json
    aid, cid = _resolve(account_id, container_id)
    detail = pull_mod.pull_version_detail(get_service(), aid, cid, version_id)
    print(_json.dumps(detail, indent=2, default=str))


@pull_group.command("workspace-status")
@click.option("--account", "account_id", default=None)
@click.option("--container", "container_id", default=None)
@click.option("--workspace", "workspace_id", default=None)
def pull_workspace_status_cmd(account_id, container_id, workspace_id):
    """Pending changes + sync status for a workspace (JSON)."""
    import json as _json
    aid, cid, wid = _resolve_with_ws(account_id, container_id, workspace_id)
    detail = pull_mod.pull_workspace_status(get_service(), aid, cid, wid)
    print(_json.dumps(detail, indent=2, default=str))


@pull_group.command("user-permissions")
@click.option("--account", "account_id", default=None)
@_format_opt
def pull_user_permissions_cmd(account_id, fmt):
    """Users with access to the account + per-container permissions."""
    aid = account_id or get_account_id()
    rows = pull_mod.pull_user_permissions(get_service(), aid)
    emit(rows, pull_mod.COLUMNS["user-permissions"], fmt,
         title=f"User permissions ({len(rows)}) — account {aid}")


# ─── apply ────────────────────────────────────────────────────────────────────

@cli.command("apply")
@click.argument("changes_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--account", "account_id", default=None)
@click.option("--container", "container_id", default=None)
@click.option("--dry-run", is_flag=True, help="Print intended mutations without executing.")
@click.option("--yes", "assume_yes", is_flag=True, help="Skip per-change confirmation (use with care).")
def apply_cmd(changes_file, account_id, container_id, dry_run, assume_yes):
    """Apply changes from a pending-changes YAML file."""
    aid, cid = _resolve(account_id, container_id)
    apply_mod.apply_file(get_service(), aid, cid, changes_file,
                         dry_run=dry_run, assume_yes=assume_yes)


def main():
    try:
        cli()
    except Exception as e:
        console.print(f"[red]error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
