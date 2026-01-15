from typing import Optional, Dict, Any
import re
import logging
from bs4 import BeautifulSoup

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class EbayScraper(BaseScraper):
    """Scraper for eBay (targeting Japanese products)"""

    SEARCH_URL_TEMPLATE = (
        "https://www.ebay.com/sch/i.html?"
        "LH_ItemCondition=1000&"  # New items only
        "_nkw={query}&"
        "LH_PrefLoc=3&"  # Worldwide
        "_sacat=0&"
        "LH_BIN=1&"  # Buy It Now only
        "_sop=15"  # Sort by Price + Shipping: lowest first
    )

    def __init__(self, retailer_config: Dict[str, Any]):
        super().__init__(retailer_config)
        self.selectors.update({
            'listing': '.s-item',
            'title': '.s-item__title',
            'price': '.s-item__price',
            'shipping': '.s-item__shipping',
            'location': '.s-item__location',
        })

    def build_search_url(self, product) -> str:
        """Build eBay search URL"""
        query_parts = [
            "One Piece Card Game",
            product.set_code,
            "Japanese",
        ]

        if product.product_type == 'box':
            query_parts.append("Booster Box")
        elif product.product_type == 'case':
            query_parts.append("Case")

        query = "+".join(query_parts)
        return self.SEARCH_URL_TEMPLATE.format(query=query)

    def parse_price(self, soup: BeautifulSoup, product) -> Optional[Dict[str, Any]]:
        """Parse lowest price from eBay listings"""
        try:
            listings = soup.select('.s-item')

            valid_prices = []

            for listing in listings[1:11]:  # Skip first (ad), check next 10
                title_elem = listing.select_one('.s-item__title')
                if not title_elem:
                    continue

                title = title_elem.get_text().upper()

                # Verify product match
                if product.set_code.upper() not in title:
                    continue

                # Verify it's Japanese
                if 'JAPANESE' not in title and 'JP' not in title and 'JPN' not in title:
                    continue

                # Extract price
                price_elem = listing.select_one('.s-item__price')
                if price_elem:
                    price_text = price_elem.get_text()
                    price_match = re.search(r'\$([\d,]+\.?\d*)', price_text)
                    if price_match:
                        price = float(price_match.group(1).replace(',', ''))
                        valid_prices.append(price)

            if valid_prices:
                # Return median price to avoid outliers
                valid_prices.sort()
                median_idx = len(valid_prices) // 2
                return {
                    'price': valid_prices[median_idx],
                    'currency': 'USD',
                }

            return None

        except Exception as e:
            logger.error(f"Error parsing eBay price: {e}")
            return None

    def parse_stock_status(self, soup: BeautifulSoup) -> bool:
        """eBay listings are always in stock if visible"""
        return True
