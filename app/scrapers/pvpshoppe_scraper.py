from typing import Optional, Dict, Any
import re
import logging
from bs4 import BeautifulSoup

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class PVPShoppeScraper(BaseScraper):
    """Scraper for PVP Shoppe (pvpshoppe.com) - Shopify, prices in CAD"""

    COLLECTION_URL = "https://pvpshoppe.com/collections/one-piece-sealed-product-1"

    SET_PATTERNS = {
        'OP-06': r'OP-?06|wings\s*of\s*the\s*captain',
        'OP-08': r'OP-?08|two\s*legends',
        'OP-10': r'OP-?10|royal\s*blood',
        'OP-11': r'OP-?11|fist\s*of\s*divine',
        'OP-12': r'OP-?12|legacy\s*of\s*the\s*master',
        'OP-13': r'OP-?13|carrying\s*on\s*his\s*will',
        'OP-14': r'OP-?14|azure\s*sea',
        'EB-02': r'EB-?02|anime\s*25th',
        'EB-03': r'EB-?03|heroines',
        'PRB-02': r'PRB-?02|premium\s*vol\s*2',
    }

    # Approximate CAD to USD conversion (update periodically or use API)
    CAD_TO_USD = 0.74

    def __init__(self, retailer_config: Dict[str, Any]):
        super().__init__(retailer_config)
        self._products_cache = None

    def build_search_url(self, product) -> str:
        return self.COLLECTION_URL

    def _fetch_all_products(self, soup: BeautifulSoup) -> Dict[str, Dict]:
        products = {}
        cards = soup.select('.product-card, .card-wrapper, [class*="product-card"]')

        for card in cards:
            title_elem = card.select_one('.product-card__title, .card-information__text, [class*="title"]')
            price_elem = card.select_one('.price, .price__regular, [class*="price"]')
            link = card.select_one('a[href*="/products/"]')

            if not title_elem:
                continue

            title = title_elem.get_text().upper()
            if 'JAPANESE' not in title and 'JPN' not in title and 'JP' not in title:
                continue

            for set_code, pattern in self.SET_PATTERNS.items():
                if re.search(pattern, title, re.IGNORECASE):
                    is_case = 'CASE' in title
                    product_type = 'case' if is_case else 'box'

                    if price_elem:
                        price_text = price_elem.get_text()
                        price_match = re.search(r'[\d,]+\.?\d*', price_text)
                        if price_match:
                            price_cad = float(price_match.group().replace(',', ''))
                            price_usd = round(price_cad * self.CAD_TO_USD, 2)
                            if 10 < price_usd < 500:
                                key = f"{set_code}_{product_type}"
                                products[key] = {
                                    'price': price_usd,
                                    'currency': 'USD',
                                    'in_stock': 'sold out' not in card.get_text().lower() and 'out of stock' not in card.get_text().lower(),
                                    'source_url': 'https://pvpshoppe.com' + link.get('href', '') if link else self.COLLECTION_URL,
                                }
                    break

        return products

    def parse_price(self, soup: BeautifulSoup, product) -> Optional[Dict[str, Any]]:
        try:
            if self._products_cache is None:
                self._products_cache = self._fetch_all_products(soup)
            return self._products_cache.get(f"{product.set_code}_{product.product_type}")
        except Exception as e:
            logger.error(f"Error parsing PVP Shoppe: {e}")
            return None

    def parse_stock_status(self, soup: BeautifulSoup) -> bool:
        return True

    def scrape_all_products(self, products):
        self.rate_limiter.wait()
        try:
            soup = self.fetch_page(self.COLLECTION_URL)
            if not soup:
                return []
            self._products_cache = self._fetch_all_products(soup)
            results = []
            for product in products:
                data = self._products_cache.get(f"{product.set_code}_{product.product_type}")
                if data:
                    results.append({
                        'product_id': product.id,
                        'price': data['price'],
                        'currency': data['currency'],
                        'in_stock': data.get('in_stock', True),
                        'source_url': data.get('source_url', self.COLLECTION_URL),
                    })
            return results
        except Exception as e:
            logger.error(f"Error scraping PVP Shoppe: {e}")
            return []
