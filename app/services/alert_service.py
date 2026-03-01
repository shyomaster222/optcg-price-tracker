"""
app/services/alert_service.py

Business logic for creating, listing, and evaluating PriceAlerts.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from app import db
from app.models.alert import PriceAlert
from app.models.price import Price

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def create_alert(
    card_id: int,
    threshold: float,
    direction: str = "below",
    user_id: Optional[int] = None,
) -> PriceAlert:
    """
    Create and persist a new PriceAlert.

    Parameters
    ----------
    card_id   : ID of the card to watch.
    threshold : USD price threshold.
    direction : 'below' or 'above'.
    user_id   : optional FK; reserved for future auth integration.

    Returns
    -------
    The newly created PriceAlert (already committed to the DB).
    """
    if direction not in ("below", "above"):
        raise ValueError(f"direction must be 'below' or 'above', got {direction!r}")
    if threshold <= 0:
        raise ValueError("threshold must be a positive number")

    alert = PriceAlert(
        card_id=card_id,
        threshold=threshold,
        direction=direction,
        user_id=user_id,
    )
    db.session.add(alert)
    db.session.commit()
    logger.info("Created %r", alert)
    return alert


def get_alerts(
    card_id: Optional[int] = None,
    user_id: Optional[int] = None,
    active_only: bool = True,
) -> List[PriceAlert]:
    """
    Return a list of PriceAlert records filtered by optional criteria.
    """
    q = PriceAlert.query
    if card_id is not None:
        q = q.filter_by(card_id=card_id)
    if user_id is not None:
        q = q.filter_by(user_id=user_id)
    if active_only:
        q = q.filter_by(is_active=True)
    return q.order_by(PriceAlert.created_at.desc()).all()


def delete_alert(alert_id: int) -> bool:
    """
    Hard-delete a PriceAlert by ID.

    Returns True if the record was found and deleted, False otherwise.
    """
    alert = PriceAlert.query.get(alert_id)
    if alert is None:
        return False
    db.session.delete(alert)
    db.session.commit()
    return True


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_alerts(card_id: int, current_price_usd: float) -> List[PriceAlert]:
    """
    Check all active alerts for *card_id* against *current_price_usd*.

    For each alert whose threshold is crossed:
    - mark it as triggered (is_active=False, triggered_at=now)
    - log a warning (in production you'd send an e-mail / push notification)

    Returns
    -------
    List of PriceAlert objects that were triggered in this call.
    """
    active = get_alerts(card_id=card_id, active_only=True)
    triggered: List[PriceAlert] = []

    for alert in active:
        if alert.should_trigger(current_price_usd):
            alert.mark_triggered()
            triggered.append(alert)
            logger.warning(
                "ALERT TRIGGERED  alert_id=%s  card_id=%s  direction=%s  "
                "threshold=%.4f  current=%.4f",
                alert.id,
                card_id,
                alert.direction,
                alert.threshold,
                current_price_usd,
            )

    if triggered:
        db.session.commit()

    return triggered


def run_all_alerts() -> dict:
    """
    Evaluate every active alert against the card's most recent USD price.

    Intended to be called from a scheduled task (e.g. APScheduler).

    Returns
    -------
    dict with keys 'checked' and 'triggered' (counts).
    """
    active_alerts = PriceAlert.query.filter_by(is_active=True).all()
    checked = len(active_alerts)
    triggered_total = 0

    # Group by card_id so we only query the latest price once per card
    card_ids = {a.card_id for a in active_alerts}
    for card_id in card_ids:
        latest = (
            Price.query.filter_by(card_id=card_id)
            .order_by(Price.scraped_at.desc())
            .first()
        )
        if latest is None:
            continue
        fired = evaluate_alerts(card_id, latest.price_usd)
        triggered_total += len(fired)

    logger.info("run_all_alerts: checked=%d triggered=%d", checked, triggered_total)
    return {"checked": checked, "triggered": triggered_total}
