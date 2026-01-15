from flask_apscheduler import APScheduler
import logging

logger = logging.getLogger(__name__)
scheduler = APScheduler()


def init_scheduler(app):
    """Initialize the scheduler with the Flask app"""
    scheduler.init_app(app)

    @scheduler.task('cron', id='scrape_all_retailers', hour='*/6')
    def scheduled_scrape_all():
        """Run full scrape every 6 hours"""
        with app.app_context():
            logger.info("Starting scheduled scrape job")
            from app.scrapers.scraper_manager import ScraperManager
            manager = ScraperManager()
            manager.run_scrape_job()
            logger.info("Scheduled scrape job completed")

    @scheduler.task('cron', id='scrape_high_priority', hour='*/2')
    def scheduled_scrape_priority():
        """Scrape high-traffic retailers more frequently"""
        with app.app_context():
            logger.info("Starting priority scrape job")
            from app.scrapers.scraper_manager import ScraperManager
            manager = ScraperManager()
            for slug in ['tcgrepublic', 'ebay']:
                try:
                    manager.run_scrape_job(slug)
                except Exception as e:
                    logger.error(f"Error scraping {slug}: {e}")
            logger.info("Priority scrape job completed")

    scheduler.start()
    return scheduler


def run_manual_scrape(retailer_slug=None):
    """Run a manual scrape job"""
    from flask import current_app
    from app.scrapers.scraper_manager import ScraperManager

    with current_app.app_context():
        manager = ScraperManager()
        manager.run_scrape_job(retailer_slug)
