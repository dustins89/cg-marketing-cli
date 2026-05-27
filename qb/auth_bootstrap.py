"""One-time QuickBooks Online OAuth bootstrap.

Run from a local machine (NOT GH Actions — needs interactive browser):

    python -m qb.auth_bootstrap

Steps performed:
  1. Validates qb_client_id / qb_client_secret are in google-ads.yaml
  2. Prints the Intuit authorization URL — you open it, sign in, approve
  3. Spins up a tiny local HTTP server on http://localhost:8765/callback
     to catch the auth code + realmId that Intuit redirects back with
  4. Exchanges the auth code for refresh+access tokens
  5. Persists everything to the qb_credentials table

Your QB connected app's Redirect URI MUST be exactly:
  http://localhost:8765/callback
"""
from __future__ import annotations

import base64
import datetime as dt
import http.server
import os
import secrets
import socketserver
import sys
import threading
import urllib.parse
import webbrowser

import requests

from qb.client import save_db_creds, _static_creds, ensure_table, TOKEN_ENDPOINT


CALLBACK_PORT = 8765
CALLBACK_PATH = "/callback"
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}"
AUTH_ENDPOINT = "https://appcenter.intuit.com/connect/oauth2"
SCOPE = "com.intuit.quickbooks.accounting"


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    captured: dict | None = None

    def do_GET(self):
        if not self.path.startswith(CALLBACK_PATH):
            self.send_response(404)
            self.end_headers()
            return
        qs = urllib.parse.urlparse(self.path).query
        params = dict(urllib.parse.parse_qsl(qs))
        _CallbackHandler.captured = params
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h1>QB auth captured.</h1><p>You can close this tab.</p>")

    def log_message(self, *_args):
        pass  # silence access log


def _wait_for_callback(timeout_sec: int = 300) -> dict:
    server = socketserver.TCPServer(("localhost", CALLBACK_PORT), _CallbackHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"Listening on {REDIRECT_URI} ... (timeout {timeout_sec}s)")
    try:
        start = dt.datetime.now()
        while _CallbackHandler.captured is None:
            if (dt.datetime.now() - start).total_seconds() > timeout_sec:
                raise SystemExit("Timed out waiting for OAuth callback.")
            t.join(0.5)
    finally:
        server.shutdown()
        server.server_close()
    return _CallbackHandler.captured or {}


def main() -> int:
    client_id, client_secret = _static_creds()

    state = secrets.token_urlsafe(16)
    auth_url = AUTH_ENDPOINT + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "scope": SCOPE,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "state": state,
    })

    print("\nOpen this URL in a browser and authorize:")
    print(f"  {auth_url}\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    cb = _wait_for_callback()
    if cb.get("state") != state:
        raise SystemExit(f"State mismatch — got {cb.get('state')!r}, expected {state!r}.")
    if "error" in cb:
        raise SystemExit(f"OAuth error: {cb['error']}")
    code = cb.get("code")
    realm_id = cb.get("realmId")
    if not code or not realm_id:
        raise SystemExit(f"Missing code or realmId in callback: {cb!r}")

    # Exchange code for tokens
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = requests.post(
        TOKEN_ENDPOINT,
        headers={
            "Authorization": f"Basic {basic}",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise SystemExit(f"Token exchange failed: {resp.status_code} {resp.text}")

    body = resp.json()
    now = dt.datetime.now(dt.timezone.utc)
    access_expires = now + dt.timedelta(seconds=int(body["expires_in"]) - 60)
    refresh_expires = now + dt.timedelta(seconds=int(body["x_refresh_token_expires_in"]) - 60)

    # Confirm DATABASE_URL is set before we attempt write
    if not os.environ.get("DATABASE_URL"):
        print("\n⚠  DATABASE_URL not set. Tokens received but NOT persisted.")
        print("Set DATABASE_URL and re-run, OR insert manually:")
        print(f"  realm_id      = {realm_id}")
        print(f"  refresh_token = {body['refresh_token']}")
        return 1

    ensure_table()
    save_db_creds(
        realm_id=realm_id,
        refresh_token=body["refresh_token"],
        access_token=body["access_token"],
        access_expires_at=access_expires,
        refresh_expires_at=refresh_expires,
    )
    print(f"\n✓ Persisted QB credentials for realm {realm_id}.")
    print(f"  Refresh token expires {refresh_expires:%Y-%m-%d}.")
    print(f"  Nightly ingest will rotate it automatically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
