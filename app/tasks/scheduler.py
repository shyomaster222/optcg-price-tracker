from flask_apscheduler import APScheduler
import logging

logger = logging.getLogger(__name__)
scheduler = APScheduler()


def init_scheduler(app):
    """Initialize the scheduler with the Flask app"""
    scheduler.init_app(app)

    @scheduler.task('cron', id='scrape_all_retailers', hour=0, minute=0)
    def scheduled_scrape_all():
        """Run full scrape once daily at midnight UTC"""
        with app.app_context():
            logger.info("Starting daily scheduled scrape job")
            from app.scrapers.scraper_manager import ScraperManager
            manager = ScraperManager()
            manager.run_scrape_job()
            logger.info("Daily scheduled scrape job completed")

    scheduler.start()
    return scheduler


def run_manual_scrape(retailer_slug=None):
    """Run a manual scrape job"""
    from flask import current_app
    from app.scrapers.scraper_manager import ScraperManager

    with current_app.app_context():
        manager = ScraperManager()
        manager.run_scrape_job(retailer_slug)
