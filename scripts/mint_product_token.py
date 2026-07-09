#!/usr/bin/env python3
"""
Mint a Shopify Admin API token with product scopes via the same OAuth flow the
shipping scripts use, then write it to the repo .env as SHOPIFY_ADMIN_TOKEN and
verify the granted scopes. Opens a browser once for approval.

Usage:
    python scripts/mint_product_token.py --client-id XXX --client-secret YYY
"""
import argparse
import os
import re
import sys
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 52000
REDIRECT_PATH = "/callback"
REDIRECT_URI = f"http://localhost:{PORT}{REDIRECT_PATH}"
SCOPES = "write_products,read_products"


class Handler(BaseHTTPRequestHandler):
    auth_code = None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == REDIRECT_PATH:
            params = parse_qs(parsed.query)
            if "code" in params:
                Handler.auth_code = params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body><h2>Authorized. You can close this tab.</h2></body></html>")
            else:
                self.send_response(400); self.end_headers()
                self.wfile.write(b"<html><body><h2>Authorization error</h2></body></html>")
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, *a):
        pass


def mint(shop, client_id, client_secret):
    auth_url = (f"https://{shop}/admin/oauth/authorize?client_id={client_id}"
                f"&scope={SCOPES}&redirect_uri={REDIRECT_URI}")
    server = HTTPServer(("localhost", PORT), Handler)
    print(f"Opening browser to approve product scopes...\n  {auth_url}\n", flush=True)
    webbrowser.open(auth_url)
    print("Waiting for you to click Approve in the browser...", flush=True)
    while Handler.auth_code is None:
        server.handle_request()
    code = Handler.auth_code
    server.server_close()
    resp = requests.post(f"https://{shop}/admin/oauth/access_token",
                         json={"client_id": client_id, "client_secret": client_secret, "code": code},
                         timeout=20)
    resp.raise_for_status()
    return resp.json()["access_token"]


def write_env(token):
    env_path = os.path.join(REPO_ROOT, ".env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = [l for l in f.readlines() if not l.startswith("SHOPIFY_ADMIN_TOKEN=")]
    lines.append(f"SHOPIFY_ADMIN_TOKEN={token}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)
    os.chmod(env_path, 0o600)
    print(f"Saved SHOPIFY_ADMIN_TOKEN to {env_path} (gitignored, chmod 600)", flush=True)


def verify(shop, token, version="2025-01"):
    q = "{ shop { name currencyCode myshopifyDomain } currentAppInstallation { accessScopes { handle } } }"
    r = requests.post(f"https://{shop}/admin/api/{version}/graphql.json",
                      headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
                      json={"query": q}, timeout=20)
    body = r.json()
    if body.get("errors"):
        print("Verify error:", body["errors"], flush=True); return False
    data = body["data"]
    scopes = [s["handle"] for s in data["currentAppInstallation"]["accessScopes"]]
    print(f"\nStore:    {data['shop']['name']} ({data['shop']['myshopifyDomain']})", flush=True)
    print(f"Currency: {data['shop']['currencyCode']}", flush=True)
    print(f"Scopes:   {', '.join(scopes)}", flush=True)
    ok = all(s in scopes for s in ("write_products", "read_products"))
    print("\n" + ("READY: product write access confirmed." if ok else "MISSING product scopes."), flush=True)
    return ok


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--shop", default="rare-cards-japan.myshopify.com")
    p.add_argument("--client-id", required=True)
    p.add_argument("--client-secret", required=True)
    args = p.parse_args()
    token = mint(args.shop, args.client_id, args.client_secret)
    write_env(token)
    ok = verify(args.shop, token)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
