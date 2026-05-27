"""OAuth refresh-token flow + whoami.

`gads auth init` walks the user through the OAuth desktop flow and writes the
refresh token into google-ads.yaml. Uses the loopback redirect (recommended
since Google deprecated the OOB/copy-paste flow).

`gads whoami` lists customer IDs the configured refresh token can access.
"""
from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from .client import get_client, load_config, save_config

SCOPES = [
    # Google Ads — single scope covers read + write + delete
    "https://www.googleapis.com/auth/adwords",

    # GA4 Analytics — Data API needs `.readonly` explicitly (`.edit` does NOT subsume it).
    # Admin API needs `.edit`. Both required for full Data + Admin coverage.
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/analytics.edit",
    "https://www.googleapis.com/auth/analytics.manage.users",  # property user-permission edits

    # Search Console — full (read + submit + delete sitemaps; URL inspection)
    "https://www.googleapis.com/auth/webmasters",

    # Tag Manager — full container lifecycle (read + write + publish + delete)
    "https://www.googleapis.com/auth/tagmanager.edit.containers",
    "https://www.googleapis.com/auth/tagmanager.edit.containerversions",
    "https://www.googleapis.com/auth/tagmanager.publish",
    "https://www.googleapis.com/auth/tagmanager.delete.containers",
    "https://www.googleapis.com/auth/tagmanager.manage.accounts",
    "https://www.googleapis.com/auth/tagmanager.manage.users",

    # Google Business Profile — full management (locations, posts, replies)
    "https://www.googleapis.com/auth/business.manage",

    # YouTube Data API — full (read + upload + edit + delete videos/playlists/captions)
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",        # required for some destructive ops + comments

    # YouTube Analytics — readonly (no write scope exists for analytics data)
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    # NOTE: youtubepartner + yt-analytics-monetary.readonly intentionally omitted —
    # they require YouTube Content Owner / monetized-channel status (DBH is neither).
    # Re-add only if DBH joins YouTube Partner Program.
]
console = Console()


def run_oauth_flow(client_id: str, client_secret: str) -> str:
    """Run the loopback OAuth flow and return a refresh token."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:
        raise click.ClickException(
            "google-auth-oauthlib is required for `gads auth init`. "
            "It ships as a transitive dep of google-ads; reinstall with `pip install -e .`."
        ) from e

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    creds = flow.run_local_server(
        port=0,
        prompt="consent",
        access_type="offline",
        open_browser=True,
    )
    if not creds.refresh_token:
        raise click.ClickException(
            "No refresh token returned. Re-run; if Google skips consent, "
            "revoke the app at https://myaccount.google.com/permissions and retry."
        )
    return creds.refresh_token


def init_auth() -> None:
    """Interactive: collect creds, run OAuth, write google-ads.yaml."""
    cfg = {}
    try:
        cfg = load_config()
    except FileNotFoundError:
        pass

    console.print("[bold]gads auth init[/bold] — set up Google Ads API credentials.\n")

    cfg["developer_token"] = click.prompt(
        "Developer token (Google Ads → Tools & Settings → API Center)",
        default=cfg.get("developer_token", ""),
    ).strip()
    cfg["client_id"] = click.prompt(
        "OAuth client ID (ends in .apps.googleusercontent.com)",
        default=cfg.get("client_id", ""),
    ).strip()
    cfg["client_secret"] = click.prompt(
        "OAuth client secret",
        default=cfg.get("client_secret", ""),
        hide_input=False,
    ).strip()
    customer_id = click.prompt(
        "Customer ID — the account you want to query (10 digits, dashes optional)",
        default=cfg.get("customer_id", ""),
    ).strip().replace("-", "")
    cfg["customer_id"] = customer_id

    login_default = cfg.get("login_customer_id") or ""
    login_in = click.prompt(
        "Manager (MCC) ID — required since developer tokens are MCC-only. "
        "Leave blank only if customer_id IS the MCC.",
        default=login_default or "",
    ).strip().replace("-", "")
    cfg["login_customer_id"] = login_in or None

    cfg.setdefault("use_proto_plus", True)

    console.print("\nOpening browser for Google OAuth consent…")
    refresh_token = run_oauth_flow(cfg["client_id"], cfg["client_secret"])
    cfg["refresh_token"] = refresh_token

    save_config(cfg)
    console.print(f"\n[green]✓[/green] Saved credentials to google-ads.yaml (chmod 600).")
    console.print("Next: run [bold]gads whoami[/bold] to verify.")


def whoami() -> None:
    """List customer IDs accessible to the configured refresh token."""
    client = get_client()
    cs = client.get_service("CustomerService")
    resource_names = cs.list_accessible_customers().resource_names

    if not resource_names:
        console.print("[yellow]No accessible customers found.[/yellow]")
        return

    table = Table(title="Accessible customers", show_lines=False)
    table.add_column("Customer ID")
    table.add_column("Resource name")
    for rn in resource_names:
        cid = rn.split("/")[-1]
        table.add_row(cid, rn)
    console.print(table)
