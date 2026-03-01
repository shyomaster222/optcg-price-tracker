"""
app/models/alert.py

PriceAlert model  –  stores per-user, per-product price-alert thresholds.
"""

from datetime import datetime
from app.extensions import db


class PriceAlert(db.Model):
    __tablename__ = "price_alerts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=True, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    threshold = db.Column(db.Float, nullable=False)
    direction = db.Column(db.String(10), nullable=False, default="below")
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    triggered_at = db.Column(db.DateTime, nullable=True)

    product = db.relationship("Product", backref=db.backref("alerts", lazy="dynamic"))

    def should_trigger(self, current_price_usd: float) -> bool:
        if not self.is_active:
            return False
        if self.direction == "below":
            return current_price_usd < self.threshold
        if self.direction == "above":
            return current_price_usd > self.threshold
        return False

    def mark_triggered(self) -> None:
        self.is_active = False
        self.triggered_at = datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "product_id": self.product_id,
            "threshold": self.threshold,
            "direction": self.direction,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<PriceAlert id={self.id} product_id={self.product_id} "
            f"{self.direction} {self.threshold} active={self.is_active}>"
        )
