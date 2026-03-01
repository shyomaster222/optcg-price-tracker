"""
app/routes/api_export.py

Data-export endpoints  –  CSV and JSON downloads for price history.

Endpoints
---------
GET /api/export/cards                     – all cards (JSON)
GET /api/export/prices/<card_id>.csv      – price history as CSV
GET /api/export/prices/<card_id>.json     – price history as JSON
GET /api/export/prices/all.csv            – full price history (all cards)
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from flask import Blueprint, jsonify, make_response, request

from app.models.card import Card
from app.models.price import Price

export_bp = Blueprint("export", __name__, url_prefix="/api/export")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _price_rows(prices):
    """Yield dicts suitable for CSV / JSON serialisation."""
    for p in prices:
        yield {
            "card_id": p.card_id,
            "card_name": p.card.name if p.card else "",
            "set_code": p.card.set_code if p.card else "",
            "retailer": p.retailer,
            "price_usd": p.price_usd,
            "original_price": p.original_price,
            "original_currency": p.original_currency,
            "in_stock": p.in_stock,
            "scraped_at": p.scraped_at.isoformat() if p.scraped_at else "",
        }


def _build_csv_response(rows, filename: str):
    """Return a Flask Response with CSV content and download headers."""
    output = io.StringIO()
    fieldnames = [
        "card_id", "card_name", "set_code", "retailer",
        "price_usd", "original_price", "original_currency",
        "in_stock", "scraped_at",
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

@export_bp.route("/cards")
def export_cards():
    """Return all cards as JSON."""
    cards = Card.query.order_by(Card.set_code, Card.name).all()
    return jsonify([
        {
            "id": c.id,
            "name": c.name,
            "set_code": c.set_code,
            "card_number": c.card_number,
        }
        for c in cards
    ])


@export_bp.route("/prices/<int:card_id>.csv")
def export_prices_csv(card_id: int):
    """Download price history for a single card as CSV."""
    card = Card.query.get_or_404(card_id)
    since = request.args.get("since")  # optional ISO-date filter

    q = Price.query.filter_by(card_id=card_id).order_by(Price.scraped_at.asc())
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            q = q.filter(Price.scraped_at >= since_dt)
        except ValueError:
            pass  # ignore bad date; return full history

    prices = q.all()
    rows = list(_price_rows(prices))
    filename = f"prices_{card.set_code}_{card_id}_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return _build_csv_response(rows, filename)


@export_bp.route("/prices/<int:card_id>.json")
def export_prices_json(card_id: int):
    """Download price history for a single card as JSON."""
    Card.query.get_or_404(card_id)  # 404 if not found
    since = request.args.get("since")

    q = Price.query.filter_by(card_id=card_id).order_by(Price.scraped_at.asc())
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            q = q.filter(Price.scraped_at >= since_dt)
        except ValueError:
            pass

    return jsonify(list(_price_rows(q.all())))


@export_bp.route("/prices/all.csv")
def export_all_prices_csv():
    """Download the full price history for every card as a single CSV."""
    since = request.args.get("since")
    q = Price.query.order_by(Price.scraped_at.asc())
    if since:
        try:
            q = q.filter(Price.scraped_at >= datetime.fromisoformat(since))
        except ValueError:
            pass

    rows = list(_price_rows(q.all()))
    filename = f"prices_all_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return _build_csv_response(rows, filename)
