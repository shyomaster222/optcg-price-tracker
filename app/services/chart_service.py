"""
app/services/chart_service.py

ChartService  –  builds chart-ready data from price history.

Fix applied
-----------
Added all known retailer colours so the front-end chart never renders
a grey/fallback line for a recognised retailer.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.models.price import Price

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retailer colour palette
# ---------------------------------------------------------------------------
# Keys are the exact strings stored in Price.retailer.
# Values are CSS hex colours used by Chart.js on the front end.

RETAILER_COLORS: Dict[str, str] = {
    # --- originally present ---
    "PVPShoppe": "#e63946",
    "FPTradingCards": "#457b9d",
    # --- added in this fix ---
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
}

DEFAULT_COLOR = "#adb5bd"   # Bootstrap grey  –  fallback for unknown retailers


class ChartService:
    """
    Provides chart-ready time-series data for a given card.
    """

    def get_chart_data(
        self,
        card_id: int,
        days: int = 30,
        retailers: Optional[List[str]] = None,
    ) -> dict:
        """
        Build a Chart.js-compatible dataset for *card_id*.

        Parameters
        ----------
        card_id  : the card to chart.
        days     : look-back window in days (default 30).
        retailers: optional whitelist; if None all retailers are included.

        Returns
        -------
        dict with keys 'labels' (ISO dates) and 'datasets' (list of dicts).
        """
        since = datetime.utcnow() - timedelta(days=days)
        q = Price.query.filter(
            Price.card_id == card_id,
            Price.scraped_at >= since,
        ).order_by(Price.scraped_at.asc())

        if retailers:
            q = q.filter(Price.retailer.in_(retailers))

        prices = q.all()

        # Group by retailer
        series: Dict[str, List] = defaultdict(list)
        for p in prices:
            series[p.retailer].append({
                "x": p.scraped_at.strftime("%Y-%m-%dT%H:%M:%S"),
                "y": p.price_usd,
            })

        datasets = []
        for retailer, points in sorted(series.items()):
            color = RETAILER_COLORS.get(retailer, DEFAULT_COLOR)
            datasets.append({
                "label": retailer,
                "data": points,
                "borderColor": color,
                "backgroundColor": color + "33",  # 20 % opacity fill
                "tension": 0.3,
            })

        return {"datasets": datasets}
