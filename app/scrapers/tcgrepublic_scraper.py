from typing import Optional, Dict, Any
import re
import logging

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class TCGRepublicScraper(BaseScraper):
    """Scraper for TCGRepublic"""

    SEARCH_URL_TEMPLATE = "https://tcgrepublic.com/product/search.html?q={query}"

    def __init__(self, retailer_config: Dict[str, Any]):
        super().__init__(retailer_config)
        self.selectors.update({
            'product_card': '.product_unit',
            'product_title': '.product_name a',
            'price': '.figure',
            'stock_status': '.stock_status',
            'add_to_cart': '.add_to_cart_button',
        })

    def build_search_url(self, product) -> str:
        """Build TCGRepublic search URL"""
        query_parts = [
            "One Piece",
            product.set_code,
        ]

        if product.product_type == 'box':
            query_parts.append("Booster Box")
        elif product.product_type == 'case':
            query_parts.append("Case")

        query = "+".join(query_parts)
        return self.SEARCH_URL_TEMPLATE.format(query=query)

    def parse_price(self, page, product) -> Optional[Dict[str, Any]]:
        """Parse price from TCGRepublic"""
        try:
            page.wait_for_selector(self.selectors['product_card'], timeout=10000)
            products = page.query_selector_all(self.selectors['product_card'])

            for prod_elem in products[:10]:
                title_elem = prod_elem.query_selector(self.selectors['product_title'])
                if not title_elem:
                    continue

                title = title_elem.text_content().upper()

                # Match set code
                if product.set_code.upper() not in title:
                    continue

                # Match product type
                if product.product_type == 'box' and 'BOX' not in title:
                    continue
                if product.product_type == 'case' and 'CASE' not in title:
                    continue

                # Extract price (TCGRepublic shows USD)
                price_elem = prod_elem.query_selector(self.selectors['price'])
                if price_elem:
                    price_text = price_elem.text_content()
                    price_match = re.search(r'[\d,]+\.?\d*', price_text)
                    if price_match:
                        price = float(price_match.group().replace(',', ''))
                        return {
                            'price': price,
                            'currency': 'USD',
                        }

            return None

        except Exception as e:
            logger.error(f"Error parsing TCGRepublic price: {e}")
            return None

    def parse_stock_status(self, page) -> bool:
        """Check stock status on TCGRepublic"""
        add_to_cart = page.query_selector(self.selectors['add_to_cart'])
        return add_to_cart is not None
