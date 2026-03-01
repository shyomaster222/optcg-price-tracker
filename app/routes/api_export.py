"""
app/routes/api_export.py

Data-export endpoints – CSV and JSON downloads for price history.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from flask import Blueprint, jsonify, make_response, request

from app.models.product import Product
from app.models.price import PriceHistory

export_bp = Blueprint("export", __name__, url_prefix="/api/export")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _price_rows(prices):
    """Yield dicts suitable for CSV / JSON serialisation."""
    for p in prices:
        yield {
            "product_id": p.product_id,
            "set_code": p.product.set_code if p.product else "",
            "set_name": p.product.set_name if p.product else "",
            "product_type": p.product.product_type if p.product else "",
            "retailer": p.retailer.name if p.retailer else "",
            "price": float(p.price) if p.price else None,
            "price_usd": float(p.price_usd) if p.price_usd else None,
            "currency": p.currency,
            "in_stock": p.in_stock,
            "scraped_at": p.scraped_at.isoformat() if p.scraped_at else "",
        }


def _build_csv_response(rows, filename: str):
    """Return a Flask Response with CSV content and download headers."""
    output = io.StringIO()
    fieldnames = [
        "product_id", "set_code", "set_name", "product_type", "retailer",
        "price", "price_usd", "currency", "in_stock", "scraped_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@export_bp.route("/products")
def export_products():
    """Return all products as JSON."""
    products = Product.query.order_by(Product.set_code, Product.set_name).all()
    return jsonify([
        {
            "id": p.id,
            "set_code": p.set_code,
            "set_name": p.set_name,
            "product_type": p.product_type,
        }
        for p in products
    ])


@export_bp.route("/prices/<int:product_id>.csv")
def export_prices_csv(product_id: int):
    """Download price history for a single product as CSV."""
    product = Product.query.get_or_404(product_id)
    since = request.args.get("since")

    q = PriceHistory.query.filter_by(product_id=product_id).order_by(PriceHistory.scraped_at.asc())
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            q = q.filter(PriceHistory.scraped_at >= since_dt)
        except ValueError:
            pass

    prices = q.all()
    rows = list(_price_rows(prices))
    filename = f"prices_{product.set_code}_{product_id}_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return _build_csv_response(rows, filename)


@export_bp.route("/prices/<int:product_id>.json")
def export_prices_json(product_id: int):
    """Download price history for a single product as JSON."""
    Product.query.get_or_404(product_id)
    since = request.args.get("since")

    q = PriceHistory.query.filter_by(product_id=product_id).order_by(PriceHistory.scraped_at.asc())
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            q = q.filter(PriceHistory.scraped_at >= since_dt)
        except ValueError:
            pass

    return jsonify(list(_price_rows(q.all())))


@export_bp.route("/prices/all.csv")
def export_all_prices_csv():
    """Download the full price history as a single CSV."""
    since = request.args.get("since")
    q = PriceHistory.query.order_by(PriceHistory.scraped_at.asc())
    if since:
        try:
            q = q.filter(PriceHistory.scraped_at >= datetime.fromisoformat(since))
        except ValueError:
            pass

    rows = list(_price_rows(q.all()))
    filename = f"prices_all_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return _build_csv_response(rows, filename)
