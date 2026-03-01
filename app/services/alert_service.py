"""
app/services/alert_service.py

Business logic for creating, listing, and evaluating PriceAlerts.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from app.extensions import db
from app.models.alert import PriceAlert
from app.models.price import PriceHistory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def create_alert(
    product_id: int,
    threshold: float,
    direction: str = "below",
    user_id: Optional[int] = None,
) -> PriceAlert:
    if direction not in ("below", "above"):
        raise ValueError(f"direction must be 'below' or 'above', got {direction!r}")
    if threshold <= 0:
        raise ValueError("threshold must be a positive number")

    alert = PriceAlert(
        product_id=product_id,
        threshold=threshold,
        direction=direction,
        user_id=user_id,
    )
    db.session.add(alert)
    db.session.commit()
    logger.info("Created %r", alert)
    return alert


def get_alerts(
    product_id: Optional[int] = None,
    user_id: Optional[int] = None,
    active_only: bool = True,
) -> List[PriceAlert]:
    q = PriceAlert.query
    if product_id is not None:
        q = q.filter_by(product_id=product_id)
    if user_id is not None:
        q = q.filter_by(user_id=user_id)
    if active_only:
        q = q.filter_by(is_active=True)
    return q.order_by(PriceAlert.created_at.desc()).all()


def delete_alert(alert_id: int) -> bool:
    alert = PriceAlert.query.get(alert_id)
    if alert is None:
        return False
    db.session.delete(alert)
    db.session.commit()
    return True


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_alerts(product_id: int, current_price_usd: float) -> List[PriceAlert]:
    active = get_alerts(product_id=product_id, active_only=True)
    triggered: List[PriceAlert] = []

    for alert in active:
        if alert.should_trigger(current_price_usd):
            alert.mark_triggered()
            triggered.append(alert)
            logger.warning(
                "ALERT TRIGGERED  alert_id=%s  product_id=%s  direction=%s  "
                "threshold=%.4f  current=%.4f",
                alert.id,
                product_id,
                alert.direction,
                alert.threshold,
                current_price_usd,
            )

    if triggered:
        db.session.commit()

    return triggered


def run_all_alerts() -> dict:
    active_alerts = PriceAlert.query.filter_by(is_active=True).all()
    checked = len(active_alerts)
    triggered_total = 0

    product_ids = {a.product_id for a in active_alerts}
    for product_id in product_ids:
        latest = (
            PriceHistory.query.filter_by(product_id=product_id)
            .order_by(PriceHistory.scraped_at.desc())
            .first()
        )
        if latest is None or latest.price_usd is None:
            continue
        fired = evaluate_alerts(product_id, float(latest.price_usd))
        triggered_total += len(fired)

    logger.info("run_all_alerts: checked=%d triggered=%d", checked, triggered_total)
    return {"checked": checked, "triggered": triggered_total}
