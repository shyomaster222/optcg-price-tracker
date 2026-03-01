"""
app/routes/admin.py

Admin / internal routes, including the scraper-health dashboard.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template

from app.models.price import Price
from app.scrapers.scraper_manager import ScraperManager

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ---------------------------------------------------------------------------
# Health dashboard  (HTML)
# ---------------------------------------------------------------------------

@admin_bp.route("/health")
def health_dashboard():
    """
    Render the scraper-health HTML page.

    Passes each scraper's status object to the template so the page can
    show last-run time, success/failure counts, and recent errors.
    """
    manager = ScraperManager()
    statuses = manager.get_all_statuses()

    # Augment each status with DB-derived stats
    for name, status in statuses.items():
        # Count prices recorded in the last 24 h for this retailer
        since = datetime.utcnow() - timedelta(hours=24)
        status["prices_last_24h"] = (
            Price.query
            .filter(
                Price.retailer == name,
                Price.scraped_at >= since,
            )
            .count()
        )

    return render_template("admin/health.html", statuses=statuses)


@admin_bp.route("/health/json")
def health_json():
    """
    Return scraper health data as JSON.

    Suitable for external monitoring tools or a custom front-end.
    """
    manager = ScraperManager()
    statuses = manager.get_all_statuses()

    since = datetime.utcnow() - timedelta(hours=24)
    for name, status in statuses.items():
        status["prices_last_24h"] = (
            Price.query
            .filter(
                Price.retailer == name,
                Price.scraped_at >= since,
            )
            .count()
        )
        # Convert datetime objects to ISO strings for JSON serialisation
        for key in ("last_run", "last_success", "last_failure"):
            val = status.get(key)
            if isinstance(val, datetime):
                status[key] = val.isoformat()

    return jsonify(statuses)


# ---------------------------------------------------------------------------
# Quick smoke-test endpoint
# ---------------------------------------------------------------------------

@admin_bp.route("/ping")
def ping():
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()})
