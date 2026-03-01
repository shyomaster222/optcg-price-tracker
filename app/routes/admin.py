"""
app/routes/admin.py

Admin / internal routes, including the scraper-health dashboard.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template

from app.models.price import PriceHistory
from app.models.retailer import Retailer
from app.scrapers.scraper_manager import ScraperManager

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/health")
def health_dashboard():
    manager = ScraperManager()
    statuses = manager.get_all_statuses()

    since = datetime.utcnow() - timedelta(hours=24)
    for name, status in statuses.items():
        retailer = Retailer.query.filter_by(name=name).first()
        if retailer:
            status["prices_last_24h"] = (
                PriceHistory.query
                .filter(
                    PriceHistory.retailer_id == retailer.id,
                    PriceHistory.scraped_at >= since,
                )
                .count()
            )
        else:
            status["prices_last_24h"] = 0

    return render_template("admin/health.html", statuses=statuses)


@admin_bp.route("/health/json")
def health_json():
    manager = ScraperManager()
    statuses = manager.get_all_statuses()

    since = datetime.utcnow() - timedelta(hours=24)
    for name, status in statuses.items():
        retailer = Retailer.query.filter_by(name=name).first()
        if retailer:
            status["prices_last_24h"] = (
                PriceHistory.query
                .filter(
                    PriceHistory.retailer_id == retailer.id,
                    PriceHistory.scraped_at >= since,
                )
                .count()
            )
        else:
            status["prices_last_24h"] = 0

        for key in ("last_run", "last_success", "last_failure"):
            val = status.get(key)
            if isinstance(val, datetime):
                status[key] = val.isoformat()

    return jsonify(statuses)


@admin_bp.route("/ping")
def ping():
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()})
