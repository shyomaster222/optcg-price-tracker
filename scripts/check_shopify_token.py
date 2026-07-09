#!/usr/bin/env python3
"""
Read-only check that the Shopify Admin token works and has the right scopes.
Changes NOTHING on the store. Run after setting SHOPIFY_ADMIN_TOKEN.

Usage:
    python scripts/check_shopify_token.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import requests

shop = os.environ.get("SHOPIFY_SHOP", "rare-cards-japan.myshopify.com")
token = os.environ.get("SHOPIFY_ADMIN_TOKEN")
version = os.environ.get("SHOPIFY_API_VERSION", "2025-01")

if not token:
    print("FAIL: SHOPIFY_ADMIN_TOKEN is not set (add it to .env or the environment).")
    sys.exit(1)

url = f"https://{shop}/admin/api/{version}/graphql.json"
query = """
{
  shop { name currencyCode myshopifyDomain }
  currentAppInstallation { accessScopes { handle } }
}
"""
resp = requests.post(
    url,
    headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
    json={"query": query},
    timeout=20,
)
print(f"HTTP {resp.status_code}")
try:
    body = resp.json()
except Exception:
    print("FAIL: non-JSON response:", resp.text[:300]); sys.exit(1)

if body.get("errors"):
    print("FAIL: token rejected or query error:", body["errors"]); sys.exit(1)

data = body.get("data") or {}
shop_info = data.get("shop") or {}
scopes = [s["handle"] for s in (data.get("currentAppInstallation") or {}).get("accessScopes", [])]

print(f"Store:    {shop_info.get('name')} ({shop_info.get('myshopifyDomain')})")
print(f"Currency: {shop_info.get('currencyCode')}   (price sync assumes USD)")
print(f"Scopes:   {', '.join(scopes) or '(none)'}")

ok = True
for need in ("write_products", "read_products"):
    have = need in scopes
    print(f"  {'OK ' if have else 'MISSING'}  {need}")
    ok = ok and have
if shop_info.get("currencyCode") != "USD":
    print("  WARNING: store currency is not USD; price writes go in the store's base currency.")

print("\n" + ("READY: token works and has product write access." if ok
              else "NOT READY: add the missing scope(s) and reinstall the app."))
sys.exit(0 if ok else 1)
