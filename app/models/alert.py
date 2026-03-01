"""
app/models/alert.py

PriceAlert model  –  stores per-user, per-card price-alert thresholds.
"""

from datetime import datetime
from app import db


class PriceAlert(db.Model):
    """
    A price alert that fires when a card's USD price crosses
    a user-defined threshold.

    Columns
    -------
    id          : primary key
    user_id     : FK to users.id (nullable for now; extend when auth is added)
    card_id     : the card being watched (FK to cards.id)
    threshold   : USD price threshold that triggers the alert
    direction   : 'below' or 'above'
                  - 'below'  → alert when price drops  <  threshold
                  - 'above'  → alert when price rises  >  threshold
    is_active   : False once the alert has fired (one-shot) or manually disabled
    created_at  : timestamp when the alert was created
    triggered_at: timestamp when the alert last fired (None if never)
    """

    __tablename__ = "price_alerts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    card_id = db.Column(db.Integer, db.ForeignKey("cards.id"), nullable=False, index=True)
    threshold = db.Column(db.Float, nullable=False)
    direction = db.Column(db.String(10), nullable=False, default="below")  # 'below' | 'above'
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    triggered_at = db.Column(db.DateTime, nullable=True)

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------
    card = db.relationship("Card", backref=db.backref("alerts", lazy="dynamic"))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def should_trigger(self, current_price_usd: float) -> bool:
        """
        Return True if *current_price_usd* crosses the threshold in the
        configured direction AND the alert is still active.
        """
        if not self.is_active:
            return False
        if self.direction == "below":
            return current_price_usd < self.threshold
        if self.direction == "above":
            return current_price_usd > self.threshold
        return False

    def mark_triggered(self) -> None:
        """Deactivate the alert and record when it fired."""
        self.is_active = False
        self.triggered_at = datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "card_id": self.card_id,
            "threshold": self.threshold,
            "direction": self.direction,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<PriceAlert id={self.id} card_id={self.card_id} "
            f"{self.direction} {self.threshold} active={self.is_active}>"
        )
