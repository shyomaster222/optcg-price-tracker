from datetime import datetime
import json
from app.extensions import db


class Retailer(db.Model):
    __tablename__ = 'retailers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    slug = db.Column(db.String(50), nullable=False, unique=True)
    base_url = db.Column(db.String(500), nullable=False)
    country = db.Column(db.String(2), default='JP')
    currency = db.Column(db.String(3), default='JPY')
    is_active = db.Column(db.Boolean, default=True)
    requires_proxy = db.Column(db.Boolean, default=False)

    # Scraper configuration stored as JSON
    scraper_config = db.Column(db.Text)

    # Rate limiting
    min_delay_seconds = db.Column(db.Integer, default=2)
    max_delay_seconds = db.Column(db.Integer, default=5)
    requests_per_minute = db.Column(db.Integer, default=10)

    # Relationships
    price_history = db.relationship('PriceHistory', backref='retailer', lazy='dynamic')
    scrape_logs = db.relationship('ScrapeLog', backref='retailer', lazy='dynamic')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Retailer {self.name}>'

    @property
    def config(self):
        """Parse JSON config"""
        if self.scraper_config:
            return json.loads(self.scraper_config)
        return {}

    @config.setter
    def config(self, value):
        self.scraper_config = json.dumps(value)
