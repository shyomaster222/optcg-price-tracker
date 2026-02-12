from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
import random
import time
import logging
import requests
from bs4 import BeautifulSoup

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
    """Abstract base class for all retailer scrapers using requests"""

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

        self.session = requests.Session()

    @abstractmethod
    def build_search_url(self, product) -> str:
        """Build the search URL for a specific product"""
        pass

    @abstractmethod
    def parse_price(self, soup: BeautifulSoup, product) -> Optional[Dict[str, Any]]:
        """Parse price information from the page"""
        pass

    @abstractmethod
    def parse_stock_status(self, soup: BeautifulSoup) -> bool:
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

    def get_headers(self) -> Dict[str, str]:
        """Get request headers"""
        return {
            'User-Agent': self.get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,ja;q=0.8',
        }

    def fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch and parse a page using requests"""
        try:
            response = self.session.get(
                url,
                headers=self.get_headers(),
                timeout=30
            )
            response.raise_for_status()
            return BeautifulSoup(response.text, 'html.parser')
        except requests.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            return None

    def scrape_product(self, product) -> Optional[Dict[str, Any]]:
        """Scrape price for a single product using requests"""
        self.rate_limiter.wait()

        try:
            url = self.build_search_url(product)
            logger.info(f"Scraping {self.retailer_name}: {url}")

            soup = self.fetch_page(url)
            if not soup:
                return None

            time.sleep(self.get_random_delay())

            price_data = self.parse_price(soup, product)

            if price_data:
                price_data['source_url'] = url
                price_data['in_stock'] = self.parse_stock_status(soup)

            return price_data

        except Exception as e:
            logger.error(f"Error scraping {self.retailer_name}: {e}")
            return None

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
