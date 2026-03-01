"""
app/tasks/scheduler.py

APScheduler configuration for the OPTCG Price Tracker.

Scheduled jobs
--------------
* Daily at 00:00 UTC  - scrape_all_retailers   (full price scrape)
* Weekly Sun 03:00 UTC - weekly_maintenance     (archive old prices +
                                                 purge stale scrape logs)
"""

import logging

from flask_apscheduler import APScheduler

logger = logging.getLogger(__name__)
scheduler = APScheduler()


def init_scheduler(app):
    """Initialize the scheduler with the Flask app and register all jobs."""
    scheduler.init_app(app)

    # ------------------------------------------------------------------
    # 1. Daily scrape - every day at midnight UTC
    # ------------------------------------------------------------------
    @scheduler.task('cron', id='scrape_all_retailers', hour=0, minute=0)
    def scheduled_scrape_all():
        """Run full scrape once daily at midnight UTC."""
        with app.app_context():
            logger.info("Starting daily scheduled scrape job")
            from app.scrapers.scraper_manager import ScraperManager
            manager = ScraperManager()
            manager.run_scrape_job()
            logger.info("Daily scheduled scrape job completed")

    # ------------------------------------------------------------------
    # 2. Weekly maintenance - every Sunday at 03:00 UTC
    # ------------------------------------------------------------------
    @scheduler.task('cron', id='weekly_maintenance', day_of_week='sun', hour=3, minute=0)
    def weekly_maintenance():
        """
        Run weekly housekeeping:
          - Archive/deduplicate price_history rows older than 180 days.
          - Purge scrape_log rows older than 90 days.
        """
        with app.app_context():
            logger.info("Starting weekly maintenance job")

            from app.tasks.archival import archive_old_prices, cleanup_stale_scrape_logs

            try:
                archive_stats = archive_old_prices(days_threshold=180)
                logger.info(
                    "archive_old_prices complete: before=%d  removed=%d  after=%d",
                    archive_stats["records_before"],
                    archive_stats["records_removed"],
                    archive_stats["records_after"],
                )
            except Exception as exc:
                logger.error("archive_old_prices failed: %s", exc, exc_info=True)

            try:
                logs_deleted = cleanup_stale_scrape_logs(days=90)
                logger.info("cleanup_stale_scrape_logs complete: deleted=%d", logs_deleted)
            except Exception as exc:
                logger.error("cleanup_stale_scrape_logs failed: %s", exc, exc_info=True)

            logger.info("Weekly maintenance job completed")

    scheduler.start()
    return scheduler


def run_manual_scrape(retailer_slug=None):
    """Run a manual scrape job (used by CLI / admin routes)."""
    from flask import current_app
    from app.scrapers.scraper_manager import ScraperManager

    with current_app.app_context():
        manager = ScraperManager()
        manager.run_scrape_job(retailer_slug)
