from typing import Optional, Dict, Any
import re
import logging
from bs4 import BeautifulSoup

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class PriceChartingScraper(BaseScraper):
    """Scraper for PriceCharting.com - tracks historical market prices"""

    # Map set codes to PriceCharting URL slugs
    SET_SLUGS = {
        'OP-01': 'one-piece-japanese-romance-dawn',
        'OP-02': 'one-piece-japanese-paramount-war',
        'OP-03': 'one-piece-japanese-pillars-of-strength',
        'OP-04': 'one-piece-japanese-kingdoms-of-intrigue',
        'OP-05': 'one-piece-japanese-awakening-of-the-new-era',
        'OP-06': 'one-piece-japanese-wings-of-the-captain',
        'OP-07': 'one-piece-japanese-500-years-in-the-future',
        'OP-08': 'one-piece-japanese-two-legends',
        'OP-09': 'one-piece-japanese-emperors-in-the-new-world',
        'OP-10': 'one-piece-japanese-royal-blood',
        'OP-11': 'one-piece-japanese-a-fist-of-divine-speed',
        'OP-12': 'one-piece-japanese-legacy-of-the-master',
        'OP-13': 'one-piece-japanese-carrying-on-his-will',
        'OP-14': 'one-piece-japanese-the-azure-seas-seven',
        'EB-01': 'one-piece-japanese-memorial-collection',
        'EB-02': 'one-piece-japanese-anime-25th-collection',
        'EB-03': 'one-piece-japanese-heroines-edition',
        'PRB-01': 'one-piece-japanese-premium-booster',
    }

    def __init__(self, retailer_config: Dict[str, Any]):
        super().__init__(retailer_config)

    def build_search_url(self, product) -> str:
        """Build PriceCharting URL for a specific product"""
        slug = self.SET_SLUGS.get(product.set_code)
        if not slug:
            return None

        if product.product_type == 'box':
            return f"https://www.pricecharting.com/game/{slug}/booster-box"
        elif product.product_type == 'case':
            return f"https://www.pricecharting.com/game/{slug}/booster-box-case"

        return None

    def parse_price(self, soup: BeautifulSoup, product) -> Optional[Dict[str, Any]]:
        """Parse price from PriceCharting page"""
        try:
            # Look for the ungraded price in the price comparison section
            # PriceCharting shows prices like "$161.99"
            price_elem = soup.select_one('#price_data .price')
            if not price_elem:
                # Try alternate selectors
                price_elem = soup.select_one('.price')

            if price_elem:
                price_text = price_elem.get_text()
                price_match = re.search(r'\$([\d,]+\.?\d*)', price_text)
                if price_match:
                    price = float(price_match.group(1).replace(',', ''))
                    return {
                        'price': price,
                        'currency': 'USD',
                    }

            # Try to find price in the page content
            page_text = soup.get_text()
            # Look for patterns like "$161.99" near "ungraded" or "loose"
            price_match = re.search(r'(?:ungraded|loose)[^\$]*\$([\d,]+\.?\d*)', page_text, re.IGNORECASE)
            if price_match:
                price = float(price_match.group(1).replace(',', ''))
                return {
                    'price': price,
                    'currency': 'USD',
                }

            return None

        except Exception as e:
            logger.error(f"Error parsing PriceCharting price: {e}")
            return None

    def parse_stock_status(self, soup: BeautifulSoup) -> bool:
        """PriceCharting tracks market prices, so always return True"""
        return True
