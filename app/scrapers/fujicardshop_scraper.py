from typing import List, Optional
import html as _html
import re
import logging

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class FujiCardShopScraper(BaseScraper):
    """Scraper for Fuji Card Shop (fujicardshop.com) - WooCommerce, prices in USD."""

    BASE_URL = "https://www.fujicardshop.com"
    CATEGORY_PATH = "/product-category/one-piece/"

    # Fuji sits behind Cloudflare, which 403s minimal/bot-like requests. A full,
    # self-consistent browser header set (Chrome UA + matching sec-ch-ua + Sec-Fetch
    # + Referer) passes. Keep Accept-Encoding gzip/deflate only — requests can't
    # decompress brotli. (This was the cause of the ~5-week Fuji scrape outage.)
    EXTRA_HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/avif,image/webp,*/*;q=0.8"),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Referer": "https://www.fujicardshop.com/",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not.A/Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "Connection": "keep-alive",
    }

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
        'OP-16': r'OP-?16|hour\s*of\s*decisive\s*battle|decisive\s*battle',
        'EB-01': r'EB-?01|memorial',
        'EB-02': r'EB-?02|anime\s*25th',
        'EB-03': r'EB-?03|heroines',
        'EB-04': r'EB-?04|egghead',
        'OP-17': r'OP-?17|world.?s\s*strongest\s*warriors',
        'PRB-01': r'PRB-?01|the\s*best(?!\s*vol)',
        'PRB-02': r'PRB-?02|the\s*best\s*vol\.?\s*2',
    }

    # WooCommerce Store API — reachable from Railway (the HTML page is Cloudflare
    # 403'd from datacenter IPs). Returns clean JSON incl. USD prices + stock.
    API_URL = "https://www.fujicardshop.com/wp-json/wc/store/v1/products"

    @property
    def retailer_name(self) -> str:
        return "FujiCardShop"

    @property
    def retailer_slug(self) -> str:
        return "fujicardshop"

    def scrape(self) -> List[dict]:
        """Scrape Japanese One Piece sealed product from Fuji's Store API (USD)."""
        results = []
        page = 1
        while True:
            url = (f"{self.API_URL}?per_page=100&page={page}"
                   f"&category=one-piece&currency=USD")
            try:
                products = self.fetch(url).json()
            except Exception as e:
                logger.error("FujiCardShop API error (page %d): %s", page, e)
                break
            if not products:
                break
            for p in products:
                rec = self._parse_api_product(p)
                if rec:
                    results.append(rec)
            if len(products) < 100:
                break
            page += 1
        logger.info("FujiCardShop: found %d sealed price records", len(results))
        return results

    def _detect_set_code(self, name: str) -> Optional[str]:
        for set_code, pattern in self.SET_PATTERNS.items():
            if re.search(pattern, name, re.IGNORECASE):
                return set_code
        return None

    def _parse_api_product(self, p: dict) -> Optional[dict]:
        name = _html.unescape(p.get("name", "")).upper()

        # Japanese sealed boxes / cases only (skip promos, singles, comics).
        if "JAPAN" not in name and "JPN" not in name and " JP" not in name:
            return None
        if "CASE" in name:
            product_type = "case"
        elif "BOX" in name:
            product_type = "box"
        else:
            return None

        set_code = self._detect_set_code(name)
        if not set_code:
            return None

        prices = p.get("prices", {}) or {}
        try:
            minor = int(prices.get("currency_minor_unit", 2))
            value = int(prices.get("price")) / (10 ** minor)
        except (TypeError, ValueError):
            return None

        # ?currency=USD should return USD; convert defensively if not.
        code = prices.get("currency_code", "USD")
        if code == "USD":
            price_usd = value
        else:
            from app.utils.currency import convert_to_usd
            price_usd = convert_to_usd(value, code)

        if not (10 < price_usd < 2000):
            return None

        return {
            "set_code": set_code,
            "product_type": product_type,
            "price": round(price_usd, 2),
            "price_usd": round(price_usd, 2),
            "currency": "USD",
            "in_stock": bool(p.get("is_in_stock")),
            "source_url": p.get("permalink"),
        }
