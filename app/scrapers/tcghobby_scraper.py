from typing import Optional, Dict, Any
import re
import logging
from bs4 import BeautifulSoup

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class TCGHobbyScraper(BaseScraper):
    """Scraper for TCG Hobby (tcghobby.com) - Shopify store"""

    COLLECTION_URL = "https://tcghobby.com/collections/one-piece-booster-box"

    # Map set codes to product title patterns
    SET_PATTERNS = {
        'OP-01': r'OP-?01|romance\s*dawn',
        'OP-02': r'OP-?02|paramount\s*war',
        'OP-03': r'OP-?03|pillars\s*of\s*strength',
        'OP-04': r'OP-?04|kingdoms\s*of\s*intrigue',
        'OP-05': r'OP-?05|awakening\s*of\s*the\s*new\s*era',
        'OP-06': r'OP-?06|wings\s*of\s*the\s*captain|twin\s*champions',
        'OP-07': r'OP-?07|500\s*years\s*in\s*the\s*future',
        'OP-08': r'OP-?08|two\s*legends',
        'OP-09': r'OP-?09|four\s*emperors|emperors\s*in\s*the\s*new\s*world',
        'OP-10': r'OP-?10|royal\s*blood',
        'OP-11': r'OP-?11|fist\s*of\s*divine\s*speed|divine\s*speed',
        'OP-12': r'OP-?12|legacy\s*of\s*the\s*master',
        'OP-13': r'OP-?13|carrying\s*on\s*his\s*will',
        'OP-14': r'OP-?14|azure\s*sea|seven\s*heroes',
        'EB-01': r'EB-?01|EB01|memorial\s*collection',
        'EB-02': r'EB-?02|EB02|anime\s*25th',
        'EB-03': r'EB-?03|EB03|heroines',
        'EB-04': r'EB-?04|EB04|egghead',
        'PRB-01': r'PRB-?01|PRB01|the\s*best\s*premium',
    }

    def __init__(self, retailer_config: Dict[str, Any]):
        super().__init__(retailer_config)
        self._products_cache = None

    def build_search_url(self, product) -> str:
        return self.COLLECTION_URL

    def _fetch_all_products(self, soup: BeautifulSoup) -> Dict[str, Dict]:
        """Parse all products from Shopify collection page"""
        products = {}
        product_cards = soup.select('.product-card')

        for card in product_cards:
            link = card.select_one('a[href*="/products/"]')
            title_elem = card.select_one('h3, .product-card__title, .card-information__text')
            price_elem = card.select_one('.price, .price__regular')

            if not title_elem:
                continue

            title = title_elem.get_text().upper()
            # Skip non-Japanese/English booster boxes
            if 'CHINESE' in title or 'SIMPLIFIED' in title:
                continue

            for set_code, pattern in self.SET_PATTERNS.items():
                if re.search(pattern, title, re.IGNORECASE):
                    is_case = 'CASE' in title or '12 BOX' in title or 'CARTON' in title
                    product_type = 'case' if is_case else 'box'

                    if price_elem:
                        price_text = price_elem.get_text()
                        price_match = re.search(r'\$?([\d,]+\.?\d*)', price_text)
                        if price_match:
                            price = float(price_match.group(1).replace(',', ''))
                            if price < 1000:  # Sanity check
                                key = f"{set_code}_{product_type}"
                                if key not in products or price < products[key]['price']:
                                    products[key] = {
                                        'price': price,
                                        'currency': 'USD',
                                        'in_stock': True,
                                        'source_url': 'https://tcghobby.com' + link.get('href', ''),
                                    }
                    break

        return products

    def parse_price(self, soup: BeautifulSoup, product) -> Optional[Dict[str, Any]]:
        try:
            if self._products_cache is None:
                self._products_cache = self._fetch_all_products(soup)
            key = f"{product.set_code}_{product.product_type}"
            return self._products_cache.get(key)
        except Exception as e:
            logger.error(f"Error parsing TCG Hobby: {e}")
            return None

    def parse_stock_status(self, soup: BeautifulSoup) -> bool:
        return True

    def scrape_all_products(self, products):
        """Fetch collection once and parse all products"""
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
            logger.error(f"Error scraping TCG Hobby: {e}")
            return []
