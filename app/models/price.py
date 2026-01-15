from datetime import datetime
from app.extensions import db


class PriceHistory(db.Model):
    __tablename__ = 'price_history'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    retailer_id = db.Column(db.Integer, db.ForeignKey('retailers.id'), nullable=False, index=True)

    # Price data
    price = db.Column(db.Numeric(10, 2), nullable=False)
    price_usd = db.Column(db.Numeric(10, 2))
    currency = db.Column(db.String(3), default='JPY')

    # Stock status
    in_stock = db.Column(db.Boolean, default=True)
    stock_quantity = db.Column(db.Integer)

    # Source tracking
    source_url = db.Column(db.String(1000))
    scraped_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        db.Index('idx_price_product_retailer_date', 'product_id', 'retailer_id', 'scraped_at'),
    )

    def __repr__(self):
        return f'<PriceHistory {self.product_id} @ {self.retailer_id}: {self.price}>'
