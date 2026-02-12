from typing import Optional, Dict, Any
import re
import logging
from bs4 import BeautifulSoup

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class FPTradingCardsScraper(BaseScraper):
    """Scraper for FP Trading Cards (fptradingcards.com) - WooCommerce store"""

    SHOP_URL = "https://www.fptradingcards.com/shop/"

    SET_PATTERNS = {
        'OP-01': r'OP-?01|romance\s*dawn',
        'OP-02': r'OP-?02|paramount\s*war',
        'OP-03': r'OP-?03|pillars\s*of\s*strength',
        'OP-04': r'OP-?04|kingdom\s*of\s*intrigue',
        'OP-05': r'OP-?05|awakening',
        'OP-06': r'OP-?06|wings\s*of\s*the\s*captain',
        'OP-07': r'OP-?07|500\s*years',
        'OP-08': r'OP-?08|two\s*legends',
        'EB-01': r'EB-?01|memorial',
    }

    def __init__(self, retailer_config: Dict[str, Any]):
        super().__init__(retailer_config)
        self._products_cache = None

    def build_search_url(self, product) -> str:
        return self.SHOP_URL

    def _fetch_all_products(self, soup: BeautifulSoup) -> Dict[str, Dict]:
        """Parse WooCommerce shop page"""
        products = {}
        items = soup.select('.product, .type-product, li.product')

        for item in items:
            title_elem = item.select_one('.woocommerce-loop-product__title, .product_title, h2, h3')
            price_elem = item.select_one('.price .amount, .woocommerce-Price-amount, bdi')
            link = item.select_one('a[href*="product"]')

            if not title_elem:
                continue

            title = title_elem.get_text().upper()
            if 'JAPANESE' not in title and 'JPN' not in title:
                continue

            for set_code, pattern in self.SET_PATTERNS.items():
                if re.search(pattern, title, re.IGNORECASE):
                    is_case = 'CASE' in title
                    product_type = 'case' if is_case else 'box'

                    if price_elem:
                        price_text = price_elem.get_text()
                        price_match = re.search(r'[\d,]+\.?\d*', price_text)
                        if price_match:
                            price = float(price_match.group().replace(',', ''))
                            if 10 < price < 500:
                                key = f"{set_code}_{product_type}"
                                products[key] = {
                                    'price': price,
                                    'currency': 'USD',
                                    'in_stock': 'out of stock' not in item.get_text().lower(),
                                    'source_url': link.get('href', self.SHOP_URL) if link else self.SHOP_URL,
                                }
                    break

        return products

    def parse_price(self, soup: BeautifulSoup, product) -> Optional[Dict[str, Any]]:
        try:
            if self._products_cache is None:
                self._products_cache = self._fetch_all_products(soup)
            return self._products_cache.get(f"{product.set_code}_{product.product_type}")
        except Exception as e:
            logger.error(f"Error parsing FP Trading Cards: {e}")
            return None

    def parse_stock_status(self, soup: BeautifulSoup) -> bool:
        return True

    def scrape_all_products(self, products):
        self.rate_limiter.wait()
        try:
            soup = self.fetch_page(self.SHOP_URL)
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
                        'source_url': data.get('source_url', self.SHOP_URL),
                    })
            return results
        except Exception as e:
            logger.error(f"Error scraping FP Trading Cards: {e}")
            return []
