"""
app/scrapers/rarecardsjapan_scraper.py

Scraper for rarecardsjapan.com using Shopify's JSON product API.
No HTML scraping needed — the store exposes clean JSON endpoints.

Currency: all prices are stored and compared in USD.
The store's base currency is fetched from /shop.json; if it's not USD,
prices are converted via app.utils.currency.convert_to_usd.
"""

from __future__ import annotations

import logging
import re
import time
from typing import List, Optional

from app.scrapers.base_scraper import BaseScraper
from app.utils.currency import convert_to_usd

logger = logging.getLogger(__name__)

BASE_URL = "https://www.rarecardsjapan.com"

# Set codes to detect in product titles
SET_PATTERNS = {
    "OP-01": r"OP-?01|romance\s*dawn",
    "OP-02": r"OP-?02|paramount\s*war",
    "OP-03": r"OP-?03|pillars\s*of\s*strength",
    "OP-04": r"OP-?04|kingdoms\s*of\s*intrigue",
    "OP-05": r"OP-?05|awakening\s*of\s*the\s*new\s*era",
    "OP-06": r"OP-?06|wings\s*of\s*the\s*captain",
    "OP-07": r"OP-?07|500\s*years",
    "OP-08": r"OP-?08|two\s*legends",
    "OP-09": r"OP-?09|emperors",
    "OP-10": r"OP-?10|royal\s*blood",
    "OP-11": r"OP-?11|fist\s*of\s*divine|divine\s*speed",
    "OP-12": r"OP-?12|legacy\s*of\s*the\s*master",
    "OP-13": r"OP-?13|carrying\s*on\s*his\s*will",
    "OP-14": r"OP-?14|azure\s*sea",
    "EB-01": r"EB-?01|memorial\s*collection",
    "EB-02": r"EB-?02|anime\s*25th",
    "EB-03": r"EB-?03|heroines",
    "EB-04": r"EB-?04",
    "PRB-01": r"PRB-?01|the\s*best",
    "PRB-02": r"PRB-?02|premium\s*vol\s*2",
}

COLLECTION_PATHS = [
    "/collections/booster-boxes/products.json",
    "/collections/all/products.json",
]


class RareCardsJapanScraper(BaseScraper):
    """Scraper for rarecardsjapan.com — Shopify JSON API."""

    # Override Accept header: Shopify JSON API needs application/json.
    # Explicitly exclude brotli (br) from Accept-Encoding — the requests library
    # cannot decompress brotli responses, so we force gzip/deflate only.
    EXTRA_HEADERS = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }

    @property
    def retailer_name(self) -> str:
        return "RareCardsJapan"

    @property
    def retailer_slug(self) -> str:
        return "rarecardsjapan"

    def _get_store_currency(self) -> str:
        """Fetch the store's base currency from Shopify's /shop.json endpoint."""
        try:
            resp = self.fetch(f"{BASE_URL}/shop.json")
            data = resp.json()
            return data.get("shop", {}).get("currency", "USD")
        except Exception as exc:
            logger.warning("RareCardsJapan: could not fetch shop currency (%s); assuming USD", exc)
            return "USD"

    def _fetch_products_page(self, path: str, page: int) -> list:
        """Fetch one page of products from a Shopify collection JSON endpoint."""
        url = f"{BASE_URL}{path}?limit=250"
        if page > 1:
            url += f"&page={page}"
        try:
            resp = self.fetch(url)
            return resp.json().get("products", [])
        except Exception as exc:
            logger.error("RareCardsJapan: error fetching %s (page %d): %s", path, page, exc)
            return []

    def _fetch_all_products(self) -> List[dict]:
        """Fetch all products across all configured collection paths."""
        seen_ids: set = set()
        all_products: List[dict] = []

        for path in COLLECTION_PATHS:
            page = 1
            while True:
                products = self._fetch_products_page(path, page)
                if not products:
                    break
                for p in products:
                    if p["id"] not in seen_ids:
                        seen_ids.add(p["id"])
                        all_products.append(p)
                if len(products) < 250:
                    break
                page += 1
                time.sleep(0.5)

        return all_products

    def _detect_set_code(self, title: str) -> Optional[str]:
        """Return the first matching set code found in the product title."""
        for set_code, pattern in SET_PATTERNS.items():
            if re.search(pattern, title, re.IGNORECASE):
                return set_code
        return None

    def _detect_product_type(self, title: str) -> str:
        """Detect whether the product is a 'case' or 'box' from the title."""
        if re.search(r"\bcase\b", title, re.IGNORECASE):
            return "case"
        return "box"

    def scrape(self) -> List[dict]:
        """Scrape all One Piece booster products from rarecardsjapan.com."""
        store_currency = self._get_store_currency()
        products = self._fetch_all_products()
        results: List[dict] = []

        for product in products:
            title = product.get("title", "")
            set_code = self._detect_set_code(title)
            if not set_code:
                continue

            product_type = self._detect_product_type(title)
            product_handle = product.get("handle", "")
            source_url = f"{BASE_URL}/products/{product_handle}" if product_handle else BASE_URL

            for variant in product.get("variants", []):
                price_str = variant.get("price", "0")
                try:
                    price = float(price_str)
                except (ValueError, TypeError):
                    continue

                if price <= 0:
                    continue

                price_usd = convert_to_usd(price, store_currency)
                in_stock = (
                    variant.get("available", False)
                    and variant.get("inventory_policy") != "deny"
                )

                results.append({
                    "set_code": set_code,
                    "product_type": product_type,
                    "price": price,
                    "price_usd": price_usd,
                    "currency": store_currency,
                    "in_stock": in_stock,
                    "source_url": source_url,
                })

        logger.info("RareCardsJapan: found %d price records", len(results))
        return results
