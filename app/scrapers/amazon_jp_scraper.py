from typing import Optional, Dict, Any
import re
import logging
from bs4 import BeautifulSoup

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class AmazonJPScraper(BaseScraper):
    """Scraper for Amazon Japan (amazon.co.jp)"""

    SEARCH_URL_TEMPLATE = "https://www.amazon.co.jp/s?k={query}&i=toys"

    def __init__(self, retailer_config: Dict[str, Any]):
        super().__init__(retailer_config)
        self.selectors.update({
            'search_result': '[data-component-type="s-search-result"]',
            'product_title': 'h2 a span',
            'price_whole': '.a-price-whole',
            'price_fraction': '.a-price-fraction',
            'out_of_stock': '.a-color-price',
            'product_link': 'h2 a',
        })

    def build_search_url(self, product) -> str:
        """Build Amazon Japan search URL"""
        query_parts = [
            "ワンピースカードゲーム",  # One Piece Card Game in Japanese
            product.set_code,
        ]

        if product.product_type == 'box':
            query_parts.append("BOX")
        elif product.product_type == 'case':
            query_parts.append("カートン")  # "Carton" in Japanese

        query = "+".join(query_parts)
        return self.SEARCH_URL_TEMPLATE.format(query=query)

    def parse_price(self, soup: BeautifulSoup, product) -> Optional[Dict[str, Any]]:
        """Parse price from Amazon Japan search results"""
        try:
            results = soup.select('[data-component-type="s-search-result"]')

            for result in results[:5]:
                title_elem = result.select_one('h2 a span')
                if not title_elem:
                    continue

                title = title_elem.get_text().lower()

                # Verify this is the correct product
                if product.set_code.lower() not in title:
                    continue

                # Check product type matches
                is_box = 'box' in title or 'ボックス' in title
                is_case = 'カートン' in title or 'ケース' in title or 'case' in title

                if product.product_type == 'box' and not is_box:
                    continue
                if product.product_type == 'case' and not is_case:
                    continue

                # Extract price
                price_elem = result.select_one('.a-price-whole')
                if price_elem:
                    price_text = price_elem.get_text()
                    price = int(re.sub(r'[^\d]', '', price_text))

                    return {
                        'price': price,
                        'currency': 'JPY',
                    }

            return None

        except Exception as e:
            logger.error(f"Error parsing Amazon JP price: {e}")
            return None

    def parse_stock_status(self, soup: BeautifulSoup) -> bool:
        """Check if product is in stock"""
        out_of_stock_elem = soup.select_one('.a-color-price')
        if out_of_stock_elem:
            text = out_of_stock_elem.get_text().lower()
            if '在庫切れ' in text or 'out of stock' in text:
                return False
        return True
