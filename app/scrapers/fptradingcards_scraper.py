from typing import Optional, Dict, Any, List
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
        'OP-09': r'OP-?09|emperors\s*in\s*the\s*new\s*world',
        'OP-10': r'OP-?10|royal\s*blood',
        'OP-11': r'OP-?11|fist\s*of\s*divine',
        'OP-12': r'OP-?12|legacy\s*of\s*the\s*master',
        'OP-13': r'OP-?13|carrying\s*on\s*his\s*will',
        'OP-14': r'OP-?14|azure\s*sea',
        'EB-01': r'EB-?01|memorial',
        'EB-02': r'EB-?02|anime\s*25th',
        'EB-03': r'EB-?03|heroines',
        'PRB-01': r'PRB-?01|the\s*best(?!\s*vol)',
        'PRB-02': r'PRB-?02|the\s*best\s*vol\.?\s*2',
    }

    @property
    def retailer_name(self) -> str:
        return "FPTradingCards"

    def scrape(self) -> List[dict]:
        """Scrape all One Piece sealed products from FP Trading Cards."""
        try:
            response = self.fetch(self.SHOP_URL)
            soup = BeautifulSoup(response.text, "lxml")
            return list(self._parse_products(soup))
        except Exception as e:
            logger.error("Error scraping FP Trading Cards: %s", e)
            return []

    def _parse_products(self, soup: BeautifulSoup):
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
                                yield {
                                    'set_code': set_code,
                                    'product_type': product_type,
                                    'price': price,
                                    'price_usd': price,
                                    'currency': 'USD',
                                    'in_stock': 'out of stock' not in item.get_text().lower(),
                                    'source_url': link.get('href', self.SHOP_URL) if link else self.SHOP_URL,
                                }
                    break
