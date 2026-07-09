from datetime import datetime
from app.extensions import db


class PriceSyncLog(db.Model):
    """One row per product per price-sync run: the decision and (if any) the write.

    Actions:
      auto_applied - target was within tolerance; price written to Shopify
      held         - change too big / below floor; needs manual review
      skipped      - no meaningful change, or missing Fuji/RCJ data
      error        - Shopify write or lookup failed
    """
    __tablename__ = 'price_sync_log'

    id = db.Column(db.Integer, primary_key=True)

    set_code = db.Column(db.String(10), index=True)
    product_type = db.Column(db.String(20))
    rcj_handle = db.Column(db.String(300))
    rcj_variant_id = db.Column(db.BigInteger, index=True)
    fuji_url = db.Column(db.String(1000))

    fuji_price = db.Column(db.Numeric(10, 2))       # latest Fuji price used (USD)
    current_price = db.Column(db.Numeric(10, 2))    # RCJ price before the run (USD)
    target_price = db.Column(db.Numeric(10, 2))     # computed undercut target (USD)
    floor_price = db.Column(db.Numeric(10, 2))      # effective floor applied (USD)
    pct_change = db.Column(db.Float)                # (target-current)/current

    action = db.Column(db.String(20), index=True)   # auto_applied | held | skipped | error
    reason = db.Column(db.String(300))
    applied = db.Column(db.Boolean, default=False)  # True only when Shopify actually written
    dry_run = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f'<PriceSyncLog {self.set_code} {self.product_type} {self.action}>'

    def to_dict(self):
        f = lambda v: float(v) if v is not None else None
        return {
            "id": self.id,
            "set_code": self.set_code,
            "product_type": self.product_type,
            "rcj_handle": self.rcj_handle,
            "rcj_variant_id": self.rcj_variant_id,
            "fuji_url": self.fuji_url,
            "fuji_price": f(self.fuji_price),
            "current_price": f(self.current_price),
            "target_price": f(self.target_price),
            "floor_price": f(self.floor_price),
            "pct_change": self.pct_change,
            "action": self.action,
            "reason": self.reason,
            "applied": self.applied,
            "dry_run": self.dry_run,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
