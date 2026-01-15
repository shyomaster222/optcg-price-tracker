from datetime import datetime
from app.extensions import db


class ScrapeLog(db.Model):
    __tablename__ = 'scrape_logs'

    id = db.Column(db.Integer, primary_key=True)
    retailer_id = db.Column(db.Integer, db.ForeignKey('retailers.id'), nullable=False)

    # Job tracking
    status = db.Column(db.String(20), default='started')  # started, completed, failed
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    # Results
    products_scraped = db.Column(db.Integer, default=0)
    products_failed = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text)

    def __repr__(self):
        return f'<ScrapeLog {self.retailer_id} @ {self.started_at}>'

    @property
    def duration_seconds(self):
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
