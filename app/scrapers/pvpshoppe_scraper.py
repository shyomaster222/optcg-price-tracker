from typing import Optional, Dict, Any, List
import re
import logging
from bs4 import BeautifulSoup

from app.scrapers.base_scraper import BaseScraper
from app.utils.currency import convert_to_usd

logger = logging.getLogger(__name__)


class PVPShoppeScraper(BaseScraper):
    """Scraper for PVP Shoppe (pvpshoppe.com) - Shopify, prices in CAD"""

    COLLECTION_URL = "https://pvpshoppe.com/collections/one-piece-sealed-product-1"

    SET_PATTERNS = {
        'OP-06':  r'OP-?06|wings\s*of\s*the\s*captain',
        'OP-08':  r'OP-?08|two\s*legends',
        'OP-10':  r'OP-?10|royal\s*blood',
        'OP-11':  r'OP-?11|fist\s*of\s*divine',
        'OP-12':  r'OP-?12|legacy\s*of\s*the\s*master',
        'OP-13':  r'OP-?13|carrying\s*on\s*his\s*will',
        'OP-14':  r'OP-?14|azure\s*sea',
        'EB-02':  r'EB-?02|anime\s*25th',
        'EB-03':  r'EB-?03|heroines',
        'PRB-02': r'PRB-?02|premium\s*vol\s*2',
    }

    @property
    def retailer_name(self) -> str:
        return "PVPShoppe"

    def scrape(self) -> List[dict]:
        """Scrape all One Piece sealed products from PVP Shoppe."""
        try:
            response = self.fetch(self.COLLECTION_URL)
            soup = BeautifulSoup(response.text, "lxml")
            return list(self._parse_products(soup))
        except Exception as e:
            logger.error("Error scraping PVP Shoppe: %s", e)
            return []

    def _parse_products(self, soup: BeautifulSoup):
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
                            price_usd = convert_to_usd(price_cad, 'CAD')
                            if 10 < price_usd < 500:
                                yield {
                                    'set_code': set_code,
                                    'product_type': product_type,
                                    'price': price_cad,
                                    'price_usd': price_usd,
                                    'currency': 'CAD',
                                    'in_stock': (
                                        'sold out' not in card.get_text().lower()
                                        and 'out of stock' not in card.get_text().lower()
                                    ),
                                    'source_url': (
                                        'https://pvpshoppe.com' + link.get('href', '')
                                        if link else self.COLLECTION_URL
                                    ),
                                }
                    break
