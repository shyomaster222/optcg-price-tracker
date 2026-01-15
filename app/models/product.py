from datetime import datetime
from app.extensions import db


class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    set_code = db.Column(db.String(10), nullable=False, index=True)
    set_name = db.Column(db.String(100), nullable=False)
    set_name_jp = db.Column(db.String(100))
    product_type = db.Column(db.String(20), nullable=False)  # "box" or "case"
    release_date = db.Column(db.Date)
    msrp_jpy = db.Column(db.Integer)
    boxes_per_case = db.Column(db.Integer, default=12)
    packs_per_box = db.Column(db.Integer, default=24)
    image_url = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    price_history = db.relationship('PriceHistory', backref='product', lazy='dynamic')

    __table_args__ = (
        db.UniqueConstraint('set_code', 'product_type', name='unique_product'),
    )

    def __repr__(self):
        return f'<Product {self.set_code} {self.product_type}>'

    @property
    def display_name(self):
        return f"{self.set_code} {self.set_name} ({self.product_type.title()})"

    def latest_price(self, retailer_id=None):
        """Get most recent price, optionally filtered by retailer"""
        from app.models.price import PriceHistory
        query = self.price_history.order_by(PriceHistory.scraped_at.desc())
        if retailer_id:
            query = query.filter_by(retailer_id=retailer_id)
        return query.first()
