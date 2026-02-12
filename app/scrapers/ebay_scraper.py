import base64
import os
import re
import time
import logging
from typing import Optional, Dict, Any, List
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

# Module-level token cache (eBay tokens last ~2 hours)
_ebay_token_cache: Optional[Dict[str, Any]] = None


class EbayScraper(BaseScraper):
    """Scraper for eBay - uses Browse API when credentials are set, otherwise falls back to HTML scraping.

    Set EBAY_APP_ID + EBAY_CERT_ID for auto token refresh (recommended), or EBAY_ACCESS_TOKEN for manual token.
    Get credentials from: developer.ebay.com
    """

    API_BASE = "https://api.ebay.com/buy/browse/v1"
    TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
    SCOPE = "https://api.ebay.com/oauth/api_scope"

    def __init__(self, retailer_config: Dict[str, Any]):
        super().__init__(retailer_config)
        self.app_id = os.environ.get("EBAY_APP_ID")
        self.cert_id = os.environ.get("EBAY_CERT_ID")
        self.access_token = os.environ.get("EBAY_ACCESS_TOKEN")
        self.selectors.update({
            'listing': '.s-item, li.s-item',
            'title': '.s-item__title',
            'price': '.s-item__price',
        })

    def build_search_url(self, product) -> str:
        """Build eBay search URL (for HTML fallback)"""
        query_parts = ["One Piece Card Game", product.set_code, "Japanese"]
        if product.product_type == 'box':
            query_parts.append("Booster Box")
        elif product.product_type == 'case':
            query_parts.append("Case")
        query = quote_plus(" ".join(query_parts))
        return (
            f"https://www.ebay.com/sch/i.html?"
            f"_nkw={query}&LH_ItemCondition=1000&LH_BIN=1&_sop=15"
        )

    def _get_access_token(self) -> Optional[str]:
        """Get OAuth token via client credentials or use cached/manual token"""
        if self.access_token:
            return self.access_token

        if not self.app_id or not self.cert_id:
            return None

        global _ebay_token_cache
        if _ebay_token_cache and _ebay_token_cache.get("expires_at", 0) > time.time():
            return _ebay_token_cache.get("token")

        creds = base64.b64encode(f"{self.app_id}:{self.cert_id}".encode()).decode()
        try:
            resp = requests.post(
                self.TOKEN_URL,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Authorization": f"Basic {creds}",
                },
                data={
                    "grant_type": "client_credentials",
                    "scope": self.SCOPE,
                },
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error(f"eBay OAuth failed {resp.status_code}: {resp.text[:200]}")
                return None

            data = resp.json()
            token = data.get("access_token")
            expires_in = data.get("expires_in", 7200)  # default 2 hours

            _ebay_token_cache = {  # noqa: PLW0603
                "token": token,
                "expires_at": time.time() + expires_in - 60,  # refresh 1 min early
            }
            return token
        except Exception as e:
            logger.error(f"eBay OAuth error: {e}")
            return None

    def _fetch_via_api(self, product) -> Optional[Dict[str, Any]]:
        """Use eBay Browse API to search and get lowest price"""
        token = self._get_access_token()
        if not token:
            return None

        self.rate_limiter.wait()

        query_parts = ["One Piece Card Game", product.set_code, "Japanese"]
        if product.product_type == 'box':
            query_parts.append("Booster Box")
        elif product.product_type == 'case':
            query_parts.append("Case")
        q = " ".join(query_parts)

        url = f"{self.API_BASE}/item_summary/search"
        params = {
            "q": q,
            "filter": "buyingOptions:{FIXED_PRICE},conditionIds:{1000}",  # Buy It Now, New
            "sort": "price",  # Lowest first
            "limit": 20,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        }

        try:
            resp = self.session.get(url, params=params, headers=headers, timeout=30)
            if resp.status_code == 401:
                global _ebay_token_cache
                _ebay_token_cache = None  # force refresh
                logger.warning("eBay API: Invalid/expired token. Check EBAY_APP_ID/EBAY_CERT_ID or EBAY_ACCESS_TOKEN.")
                return None
            if resp.status_code != 200:
                logger.error(f"eBay API error {resp.status_code}: {resp.text[:200]}")
                return None

            data = resp.json()
            items = data.get("itemSummaries", [])

            valid_prices = []
            for item in items:
                title = (item.get("title") or "").upper()
                if product.set_code.upper() not in title:
                    continue
                if "JAPANESE" not in title and "JP" not in title and "JPN" not in title:
                    continue

                price_node = item.get("price") or item.get("currentBidPrice")
                if price_node:
                    value = price_node.get("value")
                    if value:
                        try:
                            price = float(value)
                            if 10 < price < 1000:
                                valid_prices.append(price)
                        except (ValueError, TypeError):
                            pass

            if valid_prices:
                valid_prices.sort()
                median_idx = len(valid_prices) // 2
                item_url = items[0].get("itemWebUrl") or self.build_search_url(product)
                return {
                    "price": valid_prices[median_idx],
                    "currency": "USD",
                    "source_url": item_url,
                }
            return None

        except requests.RequestException as e:
            logger.error(f"eBay API request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"eBay API parse error: {e}")
            return None

    def scrape_product(self, product) -> Optional[Dict[str, Any]]:
        """Try API first, fall back to HTML scraping"""
        result = self._fetch_via_api(product)
        if result:
            result["in_stock"] = True
            return result

        # Fallback to HTML scraping (often blocked)
        return super().scrape_product(product)

    def scrape_all_products(self, products: List) -> List[Dict[str, Any]]:
        """Scrape all products, respecting rate limits"""
        results = []
        for product in products:
            result = self.scrape_product(product)
            if result:
                result["product_id"] = product.id
                results.append(result)
            time.sleep(self.get_random_delay())
        return results

    def fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """Override to detect eBay bot-blocking"""
        soup = super().fetch_page(url)
        if soup and "Service Unavailable" in soup.get_text():
            logger.warning("eBay HTML blocked. Set EBAY_ACCESS_TOKEN for API-based scraping.")
            return None
        return soup

    def parse_price(self, soup: BeautifulSoup, product) -> Optional[Dict[str, Any]]:
        """Parse price from HTML (fallback when API not used)"""
        try:
            listings = soup.select(".s-item, li.s-item")
            if not listings:
                return None

            valid_prices = []
            for listing in listings[1:11]:
                title_elem = listing.select_one(".s-item__title")
                if not title_elem:
                    continue
                title = title_elem.get_text().upper()
                if product.set_code.upper() not in title:
                    continue
                if "JAPANESE" not in title and "JP" not in title and "JPN" not in title:
                    continue

                price_elem = listing.select_one(".s-item__price")
                if price_elem:
                    price_match = re.search(r"\$([\d,]+\.?\d*)", price_elem.get_text())
                    if price_match:
                        price = float(price_match.group(1).replace(",", ""))
                        if 10 < price < 1000:
                            valid_prices.append(price)

            if valid_prices:
                valid_prices.sort()
                return {"price": valid_prices[len(valid_prices) // 2], "currency": "USD"}
            return None
        except Exception as e:
            logger.error(f"Error parsing eBay HTML: {e}")
            return None

    def parse_stock_status(self, soup: BeautifulSoup) -> bool:
        return True
