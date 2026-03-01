"""
app/__init__.py

Flask application factory.

Changes in this revision
------------------------
- Register export_bp  (GET /api/export/...)
- Register alerts_bp  (GET|POST|DELETE /api/alerts)
- Register admin_bp   (GET /admin/health, /admin/health/json, /admin/ping)
- Schedule weekly archival task via APScheduler
- Schedule alert evaluation every 15 minutes
"""

from __future__ import annotations

import logging
import os

from flask import Flask

from app.extensions import db, migrate

logger = logging.getLogger(__name__)


def create_app(config_name: str = "default") -> Flask:
    app = Flask(__name__)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    from app.config import config
    app.config.from_object(config[config_name])

    # ------------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------------
    db.init_app(app)
    migrate.init_app(app, db)

    # ------------------------------------------------------------------
    # Blueprints
    # ------------------------------------------------------------------
    from app.routes.main import main_bp
    from app.routes.api import api_bp
    from app.routes.api_export import export_bp
    from app.routes.api_alerts import alerts_bp
    from app.routes.admin import admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(admin_bp)

    # ------------------------------------------------------------------
    # Scheduler  (APScheduler)
    # ------------------------------------------------------------------
    _start_scheduler(app)

    return app


def _start_scheduler(app: Flask) -> None:
    """
    Start APScheduler with:
      - scraping job    : every 6 hours
      - alert eval job  : every 15 minutes
      - archival job    : every Sunday at 02:00 UTC
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        logger.warning("APScheduler not installed; background jobs disabled")
        return

    scheduler = BackgroundScheduler()

    # -- Scraping ----------------------------------------------------------
    def _scrape_job():
        with app.app_context():
            from app.scrapers.scraper_manager import ScraperManager
            ScraperManager().run_all()

    scheduler.add_job(
        _scrape_job,
        trigger=IntervalTrigger(hours=6),
        id="scraping",
        replace_existing=True,
    )

    # -- Alert evaluation --------------------------------------------------
    def _alert_job():
        with app.app_context():
            from app.services.alert_service import run_all_alerts
            run_all_alerts()

    scheduler.add_job(
        _alert_job,
        trigger=IntervalTrigger(minutes=15),
        id="alert_evaluation",
        replace_existing=True,
    )

    # -- Archival ----------------------------------------------------------
    def _archival_job():
        with app.app_context():
            from app.tasks.archival import run_archival_task
            run_archival_task()

    scheduler.add_job(
        _archival_job,
        trigger=CronTrigger(day_of_week="sun", hour=2, minute=0),
        id="archival",
        replace_existing=True,
    )

    # -- Daily email report ------------------------------------------------
    def _daily_email_job():
        with app.app_context():
            from app.tasks.daily_email import send_daily_price_report
            send_daily_price_report()

    scheduler.add_job(
        _daily_email_job,
        trigger=CronTrigger(hour=4, minute=0),  # 12:00 HKT (UTC+8)
        id="daily_email",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("APScheduler started with scraping / alert-eval / archival / daily-email jobs")
