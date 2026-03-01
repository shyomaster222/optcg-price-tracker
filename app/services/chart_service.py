"""
app/services/chart_service.py

ChartService – builds chart-ready data from price history.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.models.price import PriceHistory
from app.models.retailer import Retailer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retailer colour palette (keys = retailer names as stored in the DB)
# ---------------------------------------------------------------------------

RETAILER_COLORS: Dict[str, str] = {
    "PVPShoppe": "#e63946",
    "FPTradingCards": "#457b9d",
    "TCGPlayer": "#f4a261",
    "CardMarket": "#2a9d8f",
    "YYTCGShop": "#e9c46a",
    "BigOrb": "#264653",
    "HobbySearch": "#6d6875",
    "AmiAmi": "#b5838d",
    "PlaysetTCG": "#e76f51",
    "TrollandToad": "#52b788",
    "ChannelFireball": "#d62828",
    "StarCityGames": "#023e8a",
    "Amazon Japan": "#ff9900",
    "TCGRepublic": "#1a73e8",
    "eBay": "#e53238",
    "PriceCharting": "#48bb78",
    "Japan TCG": "#805ad5",
    "TCG Hobby": "#dd6b20",
    "A Hidden Fortress": "#319795",
}

DEFAULT_COLOR = "#adb5bd"


class ChartService:

    def get_price_chart_data(
        self,
        product_id: int,
        days: int = 30,
        retailer_id: Optional[int] = None,
    ) -> dict:
        """Build a Chart.js-compatible dataset for a product."""
        since = datetime.utcnow() - timedelta(days=days)
        q = PriceHistory.query.filter(
            PriceHistory.product_id == product_id,
            PriceHistory.scraped_at >= since,
        ).order_by(PriceHistory.scraped_at.asc())

        if retailer_id:
            q = q.filter(PriceHistory.retailer_id == retailer_id)

        prices = q.all()

        series: Dict[str, List] = defaultdict(list)
        for p in prices:
            retailer_name = p.retailer.name if p.retailer else "Unknown"
            series[retailer_name].append({
                "x": p.scraped_at.strftime("%Y-%m-%dT%H:%M:%S"),
                "y": float(p.price) if p.price else 0,
            })

        datasets = []
        for retailer, points in sorted(series.items()):
            color = RETAILER_COLORS.get(retailer, DEFAULT_COLOR)
            datasets.append({
                "label": retailer,
                "data": points,
                "borderColor": color,
                "backgroundColor": color + "33",
                "tension": 0.3,
            })

        return {"datasets": datasets}

    def get_comparison_data(self, product_id: int) -> dict:
        """Get current price comparison across retailers."""
        retailers = Retailer.query.filter_by(is_active=True).all()

        comparisons = []
        for retailer in retailers:
            latest = (
                PriceHistory.query
                .filter_by(product_id=product_id, retailer_id=retailer.id)
                .order_by(PriceHistory.scraped_at.desc())
                .first()
            )
            if latest:
                comparisons.append({
                    "retailer": retailer.name,
                    "price": float(latest.price),
                    "price_usd": float(latest.price_usd) if latest.price_usd else None,
                    "currency": latest.currency,
                    "in_stock": latest.in_stock,
                    "scraped_at": latest.scraped_at.isoformat(),
                })

        return {"product_id": product_id, "comparisons": comparisons}
