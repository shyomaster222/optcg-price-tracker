"""
app/services/price_service.py

PriceService  –  thin persistence layer for scraped prices.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List

from app import db
from app.models.card import Card
from app.models.price import Price

logger = logging.getLogger(__name__)


class PriceService:
    """
    Handles bulk upsertion of price records scraped by the scrapers.
    """

    def bulk_upsert(self, records: List[dict]) -> int:
        """
        Insert-or-update price records.

        Each dict in *records* must contain:
          card_id          : int
          retailer         : str
          price_usd        : float
          original_price   : float   (price in original currency)
          original_currency: str     (ISO-4217, e.g. 'USD', 'JPY')
          in_stock         : bool

        Returns the number of rows written.
        """
        written = 0
        for rec in records:
            price = Price(
                card_id=rec["card_id"],
                retailer=rec["retailer"],
                price_usd=rec["price_usd"],
                original_price=rec.get("original_price", rec["price_usd"]),
                original_currency=rec.get("original_currency", "USD"),
                in_stock=rec.get("in_stock", True),
                scraped_at=datetime.utcnow(),
            )
            db.session.add(price)
            written += 1

        if written:
            db.session.commit()
            logger.info("PriceService.bulk_upsert: wrote %d rows", written)
        return written
