from typing import Dict, Type
from datetime import datetime
import logging

from app.scrapers.base_scraper import BaseScraper
from app.scrapers.amazon_jp_scraper import AmazonJPScraper
from app.scrapers.tcgrepublic_scraper import TCGRepublicScraper
from app.scrapers.ebay_scraper import EbayScraper
from app.scrapers.pricecharting_scraper import PriceChartingScraper
from app.scrapers.japantcg_scraper import JapanTCGScraper
from app.models.retailer import Retailer
from app.models.product import Product
from app.models.price import PriceHistory
from app.models.scrape_log import ScrapeLog
from app.extensions import db

logger = logging.getLogger(__name__)


class ScraperManager:
    """Orchestrates scraping across all retailers"""

    SCRAPER_CLASSES: Dict[str, Type[BaseScraper]] = {
        'amazon-jp': AmazonJPScraper,
        'tcgrepublic': TCGRepublicScraper,
        'ebay': EbayScraper,
        'pricecharting': PriceChartingScraper,
        'japantcg': JapanTCGScraper,
    }

    def __init__(self):
        self.scrapers: Dict[str, BaseScraper] = {}
        self._initialize_scrapers()

    def _initialize_scrapers(self):
        """Initialize scrapers for all active retailers"""
        retailers = Retailer.query.filter_by(is_active=True).all()

        for retailer in retailers:
            scraper_class = self.SCRAPER_CLASSES.get(retailer.slug)
            if scraper_class:
                config = {
                    'name': retailer.name,
                    'base_url': retailer.base_url,
                    'min_delay_seconds': retailer.min_delay_seconds,
                    'max_delay_seconds': retailer.max_delay_seconds,
                    'requests_per_minute': retailer.requests_per_minute,
                    'requires_proxy': retailer.requires_proxy,
                    'selectors': retailer.config.get('selectors', {}),
                }
                self.scrapers[retailer.slug] = scraper_class(config)

    def run_scrape_job(self, retailer_slug: str = None):
        """Run scraping job for one or all retailers"""
        products = Product.query.filter_by(is_active=True).all()

        retailers_to_scrape = [retailer_slug] if retailer_slug else list(self.scrapers.keys())

        for slug in retailers_to_scrape:
            if slug not in self.scrapers:
                logger.warning(f"No scraper configured for: {slug}")
                continue

            retailer = Retailer.query.filter_by(slug=slug).first()
            if not retailer:
                continue

            # Create scrape log
            scrape_log = ScrapeLog(
                retailer_id=retailer.id,
                status='started'
            )
            db.session.add(scrape_log)
            db.session.commit()

            try:
                scraper = self.scrapers[slug]
                results = scraper.scrape_all_products(products)

                # Save results
                for result in results:
                    price_history = PriceHistory(
                        product_id=result['product_id'],
                        retailer_id=retailer.id,
                        price=result['price'],
                        currency=result['currency'],
                        in_stock=result.get('in_stock', True),
                        source_url=result.get('source_url'),
                        scraped_at=datetime.utcnow()
                    )
                    db.session.add(price_history)

                # Update scrape log
                scrape_log.status = 'completed'
                scrape_log.completed_at = datetime.utcnow()
                scrape_log.products_scraped = len(results)
                scrape_log.products_failed = len(products) - len(results)

            except Exception as e:
                logger.error(f"Scrape job failed for {slug}: {e}")
                scrape_log.status = 'failed'
                scrape_log.completed_at = datetime.utcnow()
                scrape_log.error_message = str(e)

            finally:
                db.session.commit()
