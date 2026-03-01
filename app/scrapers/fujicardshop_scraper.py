from typing import List
import re
import logging
from bs4 import BeautifulSoup

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class FujiCardShopScraper(BaseScraper):
    """Scraper for Fuji Card Shop (fujicardshop.com) - WooCommerce, prices in USD."""

    BASE_URL = "https://www.fujicardshop.com"
    CATEGORY_PATH = "/product-category/one-piece/"

    SET_PATTERNS = {
        'OP-01': r'OP-?01|romance\s*dawn',
        'OP-02': r'OP-?02|paramount\s*war',
        'OP-03': r'OP-?03|pillars\s*of\s*strength',
        'OP-04': r'OP-?04|kingdom\s*of\s*intrigue',
        'OP-05': r'OP-?05|awakening',
        'OP-06': r'OP-?06|wings\s*of\s*the\s*captain',
        'OP-07': r'OP-?07|500\s*years',
        'OP-08': r'OP-?08|two\s*legends',
        'OP-09': r'OP-?09|emperors?\s*in\s*the\s*new\s*world',
        'OP-10': r'OP-?10|royal\s*blood',
        'OP-11': r'OP-?11|fist\s*of\s*divine',
        'OP-12': r'OP-?12|legacy\s*of\s*the\s*master',
        'OP-13': r'OP-?13|carrying\s*on\s*his\s*will',
        'OP-14': r'OP-?14|azure\s*sea',
        'OP-15': r'OP-?15|adventure\s*on\s*kami',
        'EB-01': r'EB-?01|memorial',
        'EB-02': r'EB-?02|anime\s*25th',
        'EB-03': r'EB-?03|heroines',
        'EB-04': r'EB-?04|egghead',
        'PRB-01': r'PRB-?01|the\s*best(?!\s*vol)',
        'PRB-02': r'PRB-?02|the\s*best\s*vol\.?\s*2',
    }

    @property
    def retailer_name(self) -> str:
        return "FujiCardShop"

    @property
    def retailer_slug(self) -> str:
        return "fujicardshop"

    def scrape(self) -> List[dict]:
        results = []
        page = 1
        while True:
            if page == 1:
                url = f"{self.BASE_URL}{self.CATEGORY_PATH}?currency=USD"
            else:
                url = f"{self.BASE_URL}{self.CATEGORY_PATH}page/{page}/?currency=USD"
            try:
                response = self.fetch(url)
                soup = BeautifulSoup(response.text, "lxml")
                page_results = list(self._parse_products(soup, url))
                if not page_results:
                    break
                results.extend(page_results)
                next_link = soup.select_one("a.next.page-numbers")
                if not next_link:
                    break
                page += 1
            except Exception as e:
                logger.error("Error scraping FujiCardShop page %d: %s", page, e)
                break
        return results

    def _parse_products(self, soup: BeautifulSoup, page_url: str = ""):
        items = soup.select(".product, .type-product, li.product")

        for item in items:
            title_elem = item.select_one(
                ".woocommerce-loop-product__title, .product_title, h2, h3"
            )
            # Prefer the sale price if present, otherwise regular price
            price_elem = (
                item.select_one(".price ins .woocommerce-Price-amount bdi")
                or item.select_one(".price ins .amount")
                or item.select_one(".price .woocommerce-Price-amount bdi")
                or item.select_one(".price .woocommerce-Price-amount")
                or item.select_one(".price bdi")
                or item.select_one(".woocommerce-Price-amount")
            )
            link = item.select_one("a[href*='fujicardshop.com']") or item.select_one("a")

            if not title_elem:
                continue

            title = title_elem.get_text(strip=True).upper()

            # Only Japanese products
            if "JAPANESE" not in title and "JPN" not in title and "JP" not in title:
                continue

            for set_code, pattern in self.SET_PATTERNS.items():
                if re.search(pattern, title, re.IGNORECASE):
                    is_case = "CASE" in title
                    product_type = "case" if is_case else "box"

                    if price_elem:
                        price_text = price_elem.get_text(strip=True)
                        price_match = re.search(r"[\d,]+\.?\d*", price_text)
                        if price_match:
                            price = float(price_match.group().replace(",", ""))
                            if 10 < price < 2000:
                                source_url = (
                                    link.get("href", page_url)
                                    if link
                                    else page_url or f"{self.BASE_URL}{self.CATEGORY_PATH}"
                                )
                                yield {
                                    "set_code": set_code,
                                    "product_type": product_type,
                                    "price": price,
                                    "price_usd": price,
                                    "currency": "USD",
                                    "in_stock": (
                                        "out of stock" not in item.get_text().lower()
                                        and "sold out" not in item.get_text().lower()
                                    ),
                                    "source_url": source_url,
                                }
                    break
