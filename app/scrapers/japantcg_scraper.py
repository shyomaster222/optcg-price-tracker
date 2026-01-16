from typing import Optional, Dict, Any
import re
import logging
from bs4 import BeautifulSoup

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class JapanTCGScraper(BaseScraper):
    """Scraper for Japan Trading Card Store (japantradingcardstore.com)"""

    SEARCH_URL = "https://japantradingcardstore.com/collections/one-piece-booster-box"

    def __init__(self, retailer_config: Dict[str, Any]):
        super().__init__(retailer_config)
        self._products_cache = None

    def build_search_url(self, product) -> str:
        """Return the collection URL - we'll parse all products at once"""
        return self.SEARCH_URL

    def _fetch_all_products(self, soup: BeautifulSoup) -> Dict[str, Dict]:
        """Parse all products from the collection page"""
        products = {}

        product_cards = soup.select('.product-card, .product-item, [class*="product"]')

        for card in product_cards:
            title_elem = card.select_one('.product-title, .product-card__title, a[href*="/products/"]')
            price_elem = card.select_one('.price, .product-price, [class*="price"]')

            if not title_elem:
                continue

            title = title_elem.get_text().upper()

            # Extract set code from title (e.g., "OP-01", "EB-01")
            set_match = re.search(r'(OP-\d{2}|EB-\d{2}|PRB-\d{2})', title)
            if not set_match:
                continue

            set_code = set_match.group(1)

            # Determine product type
            is_case = 'CASE' in title or 'CARTON' in title
            product_type = 'case' if is_case else 'box'

            # Extract price
            if price_elem:
                price_text = price_elem.get_text()
                price_match = re.search(r'\$([\d,]+\.?\d*)', price_text)
                if price_match:
                    price = float(price_match.group(1).replace(',', ''))

                    # Check stock status
                    card_text = card.get_text().lower()
                    in_stock = 'out of stock' not in card_text and 'sold out' not in card_text

                    key = f"{set_code}_{product_type}"
                    products[key] = {
                        'price': price,
                        'currency': 'USD',
                        'in_stock': in_stock
                    }

        return products

    def parse_price(self, soup: BeautifulSoup, product) -> Optional[Dict[str, Any]]:
        """Parse price for a specific product from the collection page"""
        try:
            if self._products_cache is None:
                self._products_cache = self._fetch_all_products(soup)

            key = f"{product.set_code}_{product.product_type}"
            return self._products_cache.get(key)

        except Exception as e:
            logger.error(f"Error parsing Japan TCG Store price: {e}")
            return None

    def parse_stock_status(self, soup: BeautifulSoup) -> bool:
        """Stock status is determined in parse_price"""
        return True

    def scrape_all_products(self, products):
        """Override to fetch collection page once and parse all products"""
        self.rate_limiter.wait()

        try:
            soup = self.fetch_page(self.SEARCH_URL)
            if not soup:
                return []

            self._products_cache = self._fetch_all_products(soup)

            results = []
            for product in products:
                key = f"{product.set_code}_{product.product_type}"
                price_data = self._products_cache.get(key)

                if price_data:
                    results.append({
                        'product_id': product.id,
                        'price': price_data['price'],
                        'currency': price_data['currency'],
                        'in_stock': price_data.get('in_stock', True),
                        'source_url': self.SEARCH_URL
                    })

            return results

        except Exception as e:
            logger.error(f"Error scraping Japan TCG Store: {e}")
            return []
