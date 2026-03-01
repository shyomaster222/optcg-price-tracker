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


@admin_bp.route("/send-report", methods=["POST"])
def trigger_report():
    import requests as http_requests
    from app.services.email_service import _build_report
    api_key = __import__('flask').current_app.config.get("RESEND_API_KEY")
    company_email = __import__('flask').current_app.config.get("COMPANY_EMAIL")
    report = _build_report()
    from app.services.email_service import _build_html
    html_body = _build_html(report)
    flagged = report["flagged"]
    date_str = report["date"]
    subject = f"[OPTCG Price Report] {date_str} — {flagged} product{'s' if flagged != 1 else ''} flagged"
    resp = http_requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"from": f"OPTCG Tracker <{company_email}>", "to": [company_email], "subject": subject, "html": html_body},
        timeout=15,
    )
    return jsonify({
        "status": "ok",
        "report_rows": report["total"],
        "flagged": flagged,
        "to": company_email,
        "subject": subject,
        "resend_status": resp.status_code,
        "resend_body": resp.json(),
    })


@admin_bp.route("/run-scraper", methods=["POST"])
def trigger_scraper():
    from app.scrapers.scraper_manager import ScraperManager
    results = ScraperManager().run_all()
    summary = {name: len(data) for name, data in results.items()}
    return jsonify({"status": "ok", "results": summary})


@admin_bp.route("/debug-rcj")
def debug_rcj():
    from app.scrapers.rarecardsjapan_scraper import RareCardsJapanScraper
    scraper = RareCardsJapanScraper()
    url = "https://www.rarecardsjapan.com/collections/booster-boxes/products.json?limit=250"
    try:
        resp = scraper.fetch(url)
        raw = resp.text[:300]
        try:
            data = resp.json()
            products = data.get("products", [])
            return jsonify({
                "url": url,
                "status_code": resp.status_code,
                "product_count": len(products),
                "titles": [p.get("title") for p in products[:5]],
            })
        except Exception as json_exc:
            return jsonify({
                "url": url,
                "status_code": resp.status_code,
                "json_error": str(json_exc),
                "raw_response": raw,
            })
    except Exception as exc:
        return jsonify({"url": url, "error": str(exc), "type": type(exc).__name__})


@admin_bp.route("/seed-rcj", methods=["POST"])
def seed_rcj():
    existing = Retailer.query.filter_by(slug="rarecardsjapan").first()
    if existing:
        return jsonify({"status": "already_exists", "id": existing.id})
    from app.extensions import db as _db
    retailer = Retailer(
        name="Rare Cards Japan",
        slug="rarecardsjapan",
        base_url="https://www.rarecardsjapan.com",
        country="GB",
        currency="USD",
        min_delay_seconds=2,
        max_delay_seconds=4,
        requests_per_minute=10,
        is_active=True,
    )
    _db.session.add(retailer)
    _db.session.commit()
    return jsonify({"status": "created", "id": retailer.id, "name": retailer.name})


@admin_bp.route("/debug-db")
def debug_db():
    from app.models.product import Product
    from sqlalchemy import distinct
    retailers = Retailer.query.all()
    retailer_info = [{"id": r.id, "name": r.name, "slug": r.slug} for r in retailers]
    rcj = Retailer.query.filter_by(slug="rarecardsjapan").first()
    rcj_price_count = (
        PriceHistory.query.filter_by(retailer_id=rcj.id).count() if rcj else 0
    )
    all_products = Product.query.order_by(Product.set_code, Product.product_type).all()
    # Which products have RCJ prices?
    rcj_product_ids = set()
    if rcj:
        rows = PriceHistory.query.filter_by(retailer_id=rcj.id).with_entities(PriceHistory.product_id).distinct().all()
        rcj_product_ids = {r[0] for r in rows}
    product_coverage = [
        {
            "set_code": p.set_code,
            "product_type": p.product_type,
            "has_rcj_price": p.id in rcj_product_ids,
        }
        for p in all_products
    ]
    missing = [p for p in product_coverage if not p["has_rcj_price"]]
    return jsonify({
        "retailers": len(retailer_info),
        "total_products": len(all_products),
        "rcj_price_rows": rcj_price_count,
        "products_with_rcj_price": len(rcj_product_ids),
        "missing_rcj_price": missing,
    })
