"""
app/services/price_service.py

PriceService – price retrieval, comparison, and persistence layer.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from app.extensions import db
from app.models.product import Product
from app.models.price import PriceHistory
from app.models.retailer import Retailer

logger = logging.getLogger(__name__)


class PriceService:

    def get_dashboard_summary(self) -> List[dict]:
        """Return summary data for the dashboard."""
        products = Product.query.filter_by(is_active=True).all()
        summary = []
        for product in products:
            latest = (
                PriceHistory.query
                .filter_by(product_id=product.id)
                .order_by(PriceHistory.scraped_at.desc())
                .first()
            )
            summary.append({
                "product_id": product.id,
                "set_code": product.set_code,
                "display_name": product.display_name,
                "latest_price": float(latest.price) if latest else None,
                "price_usd": float(latest.price_usd) if latest and latest.price_usd else None,
                "currency": latest.currency if latest else None,
                "last_updated": latest.scraped_at.isoformat() if latest else None,
            })
        return summary

    def get_latest_prices(self, product_id: int) -> List[dict]:
        """Get latest price from each active retailer for a product."""
        retailers = Retailer.query.filter_by(is_active=True).all()
        prices = []
        for retailer in retailers:
            latest = (
                PriceHistory.query
                .filter_by(product_id=product_id, retailer_id=retailer.id)
                .order_by(PriceHistory.scraped_at.desc())
                .first()
            )
            if latest:
                prices.append({
                    "retailer": retailer.name,
                    "retailer_id": retailer.id,
                    "price": float(latest.price),
                    "price_usd": float(latest.price_usd) if latest.price_usd else None,
                    "currency": latest.currency,
                    "in_stock": latest.in_stock,
                    "source_url": latest.source_url,
                    "scraped_at": latest.scraped_at.isoformat(),
                })
        return prices

    def get_best_price(self, product_id: int) -> Optional[dict]:
        """Get the lowest in-stock price across all retailers."""
        retailers = Retailer.query.filter_by(is_active=True).all()
        best = None
        for retailer in retailers:
            latest = (
                PriceHistory.query
                .filter_by(product_id=product_id, retailer_id=retailer.id, in_stock=True)
                .order_by(PriceHistory.scraped_at.desc())
                .first()
            )
            if latest and (best is None or latest.price < best["price"]):
                best = {
                    "retailer": retailer.name,
                    "retailer_id": retailer.id,
                    "price": float(latest.price),
                    "price_usd": float(latest.price_usd) if latest.price_usd else None,
                    "currency": latest.currency,
                    "source_url": latest.source_url,
                    "scraped_at": latest.scraped_at.isoformat(),
                }
        return best

    def bulk_upsert(self, records: List[dict]) -> int:
        """Insert price records from scrapers."""
        written = 0
        for rec in records:
            price = PriceHistory(
                product_id=rec["product_id"],
                retailer_id=rec["retailer_id"],
                price=rec["price"],
                price_usd=rec.get("price_usd"),
                currency=rec.get("currency", "JPY"),
                in_stock=rec.get("in_stock", True),
                source_url=rec.get("source_url"),
                scraped_at=datetime.utcnow(),
            )
            db.session.add(price)
            written += 1

        if written:
            db.session.commit()
            logger.info("PriceService.bulk_upsert: wrote %d rows", written)
        return written
