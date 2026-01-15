from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
import random
import time
import logging

from app.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# Common user agents for rotation
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
]


class BaseScraper(ABC):
    """Abstract base class for all retailer scrapers"""

    def __init__(self, retailer_config: Dict[str, Any]):
        self.retailer_name = retailer_config.get('name')
        self.base_url = retailer_config.get('base_url')
        self.min_delay = retailer_config.get('min_delay_seconds', 2)
        self.max_delay = retailer_config.get('max_delay_seconds', 5)
        self.requires_proxy = retailer_config.get('requires_proxy', False)
        self.selectors = retailer_config.get('selectors', {})

        self.rate_limiter = RateLimiter(
            requests_per_minute=retailer_config.get('requests_per_minute', 10)
        )

    @abstractmethod
    def build_search_url(self, product) -> str:
        """Build the search URL for a specific product"""
        pass

    @abstractmethod
    def parse_price(self, page, product) -> Optional[Dict[str, Any]]:
        """Parse price information from the page"""
        pass

    @abstractmethod
    def parse_stock_status(self, page) -> bool:
        """Parse stock availability from the page"""
        pass

    def get_random_delay(self) -> float:
        """Get a random delay with jitter for anti-detection"""
        base_delay = random.uniform(self.min_delay, self.max_delay)
        jitter = random.uniform(-0.5, 0.5)
        return max(0.5, base_delay + jitter)

    def get_random_user_agent(self) -> str:
        """Get a random user agent string"""
        return random.choice(USER_AGENTS)

    def scrape_product(self, product) -> Optional[Dict[str, Any]]:
        """Scrape price for a single product using Playwright"""
        self.rate_limiter.wait()

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("Playwright not installed. Run: pip install playwright && playwright install")
            return None

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=self.get_random_user_agent(),
                locale='ja-JP',
                timezone_id='Asia/Tokyo'
            )
            page = context.new_page()

            try:
                url = self.build_search_url(product)
                logger.info(f"Scraping {self.retailer_name}: {url}")

                page.goto(url, wait_until='networkidle', timeout=30000)
                time.sleep(self.get_random_delay())

                price_data = self.parse_price(page, product)

                if price_data:
                    price_data['source_url'] = url
                    price_data['in_stock'] = self.parse_stock_status(page)

                return price_data

            except Exception as e:
                logger.error(f"Error scraping {self.retailer_name}: {e}")
                return None
            finally:
                browser.close()

    def scrape_all_products(self, products: List) -> List[Dict[str, Any]]:
        """Scrape prices for all products"""
        results = []
        for product in products:
            result = self.scrape_product(product)
            if result:
                result['product_id'] = product.id
                results.append(result)
            time.sleep(self.get_random_delay())
        return results
