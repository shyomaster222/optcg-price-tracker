"""
app/tasks/daily_email.py

Thin wrapper that triggers the daily price-comparison email report.
Called by the APScheduler job registered in app/__init__.py.
"""

import logging

from app.services.email_service import send_report

logger = logging.getLogger(__name__)


def send_daily_price_report() -> None:
    """Send the daily price comparison email report."""
    logger.info("daily_email: starting daily price report")
    send_report()
    logger.info("daily_email: daily price report complete")
