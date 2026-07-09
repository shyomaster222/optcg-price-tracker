"""
app/services/rcj_shopify.py

Thin Shopify Admin client for the Rare Cards Japan store, used by the price sync.

Two responsibilities:
  1. fetch_current_prices()  - read current variant prices from the public
     products.json (no token needed) so we know the "before" price.
  2. update_variant_price()  - write a new price via the GraphQL Admin API
     `productVariantsBulkUpdate` mutation (needs a token with write_products).

Writes respect PRICE_SYNC_DRY_RUN: when true, the mutation is logged and skipped.

Config (app/config.py):
  SHOPIFY_SHOP, SHOPIFY_ADMIN_TOKEN, SHOPIFY_API_VERSION, PRICE_SYNC_DRY_RUN
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

import requests
from flask import current_app

logger = logging.getLogger(__name__)

_STOREFRONT = "https://www.rarecardsjapan.com"
_COLLECTION_PATHS = [
    "/collections/booster-boxes/products.json",
    "/collections/all/products.json",
]
_HEADERS = {
    "Accept": "application/json",
    # requests can't decode brotli — force gzip/deflate (same trick as the scraper).
    "Accept-Encoding": "gzip, deflate",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}


class ShopifyConfigError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Read side (public products.json)
# ---------------------------------------------------------------------------

def fetch_current_prices() -> Dict[int, dict]:
    """Return {variant_id: {price, product_id, available, title}} for the whole catalog
    via the public products.json. NOTE: the storefront JSON is aggressively
    rate-limited (429) from shared/cloud IPs. Prefer fetch_prices_by_variant_ids()
    (authenticated Admin API) for the sync; this remains for local/offline use."""
    out: Dict[int, dict] = {}
    for path in _COLLECTION_PATHS:
        page = 1
        while True:
            url = f"{_STOREFRONT}{path}?limit=250&currency=USD"
            if page > 1:
                url += f"&page={page}"
            resp = requests.get(url, headers=_HEADERS, timeout=30)
            resp.raise_for_status()
            products = resp.json().get("products", [])
            if not products:
                break
            for p in products:
                for v in p.get("variants", []):
                    vid = v.get("id")
                    if vid is None:
                        continue
                    try:
                        price = float(v.get("price"))
                    except (TypeError, ValueError):
                        continue
                    out[int(vid)] = {
                        "price": price,
                        "product_id": p.get("id"),
                        "available": bool(v.get("available")),
                        "title": p.get("title"),
                    }
            if len(products) < 250:
                break
            page += 1
    return out


_VARIANTS_QUERY = """
query($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on ProductVariant { id price availableForSale inventoryQuantity product { id } }
  }
}
""".strip()


def fetch_prices_by_variant_ids(variant_ids) -> Dict[int, dict]:
    """Return {variant_id: {price, product_id, available}} via the authenticated
    Admin GraphQL API (not the rate-limited storefront JSON). Only fetches the
    given variants. Batches ids to stay well under node limits."""
    token = current_app.config.get("SHOPIFY_ADMIN_TOKEN")
    if not token:
        raise ShopifyConfigError("SHOPIFY_ADMIN_TOKEN is not configured")

    ids = [int(v) for v in variant_ids]
    out: Dict[int, dict] = {}
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        gids = [_gid("ProductVariant", v) for v in chunk]
        resp = requests.post(
            _graphql_endpoint(),
            headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
            json={"query": _VARIANTS_QUERY, "variables": {"ids": gids}},
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            raise RuntimeError(f"Admin API errors: {body['errors']}")
        for node in (body.get("data") or {}).get("nodes") or []:
            if not node or "id" not in node:
                continue
            try:
                vid = int(str(node["id"]).split("/")[-1])
                price = float(node["price"])
            except (TypeError, ValueError):
                continue
            out[vid] = {
                "price": price,
                "product_id": node.get("product", {}).get("id"),
                "available": bool(node.get("availableForSale")),
                "inventory": node.get("inventoryQuantity"),
            }
    return out


# ---------------------------------------------------------------------------
# Write side (GraphQL Admin API)
# ---------------------------------------------------------------------------

_MUTATION = """
mutation setPrice($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants { id price }
    userErrors { field message }
  }
}
""".strip()


def _gid(kind: str, numeric_id) -> str:
    s = str(numeric_id)
    if s.startswith("gid://"):
        return s
    return f"gid://shopify/{kind}/{s}"


def _graphql_endpoint() -> str:
    shop = current_app.config.get("SHOPIFY_SHOP")
    version = current_app.config.get("SHOPIFY_API_VERSION", "2025-01")
    if not shop:
        raise ShopifyConfigError("SHOPIFY_SHOP is not configured")
    return f"https://{shop}/admin/api/{version}/graphql.json"


def update_variant_price(product_id, variant_id, price: float,
                         force_live: bool = False) -> Tuple[bool, Optional[str]]:
    """Set a variant's price. Returns (ok, error_message).

    Honors PRICE_SYNC_DRY_RUN (logs and no-ops) UNLESS force_live=True, which is
    used for explicit manual applies from the review page — a human clicking Apply
    means the price should actually change even while the daily automation is dry."""
    price_str = f"{float(price):.2f}"

    if current_app.config.get("PRICE_SYNC_DRY_RUN", True) and not force_live:
        logger.info("[DRY_RUN] would set variant %s -> $%s", variant_id, price_str)
        return True, None

    token = current_app.config.get("SHOPIFY_ADMIN_TOKEN")
    if not token:
        return False, "SHOPIFY_ADMIN_TOKEN is not configured"

    variables = {
        "productId": _gid("Product", product_id),
        "variants": [{"id": _gid("ProductVariant", variant_id), "price": price_str}],
    }
    try:
        resp = requests.post(
            _graphql_endpoint(),
            headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
            json={"query": _MUTATION, "variables": variables},
            timeout=20,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        return False, f"request failed: {exc}"

    # Top-level GraphQL errors (bad query, auth, throttle)
    if body.get("errors"):
        return False, f"graphql errors: {body['errors']}"

    payload = (body.get("data") or {}).get("productVariantsBulkUpdate") or {}
    user_errors = payload.get("userErrors") or []
    if user_errors:
        return False, "; ".join(f"{e.get('field')}: {e.get('message')}" for e in user_errors)

    variants = payload.get("productVariants") or []
    if not variants:
        return False, "no variant returned; update may not have applied"

    logger.info("Shopify: set variant %s -> $%s (now %s)",
                variant_id, price_str, variants[0].get("price"))
    return True, None
