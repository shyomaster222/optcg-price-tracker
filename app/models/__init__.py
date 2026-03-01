"""
app/models/__init__.py

Central import point for all SQLAlchemy models.
Importing from here guarantees that every model is registered with the
metadata before db.create_all() / Alembic migrations run.
"""

from app.models.product import Product
from app.models.retailer import Retailer
from app.models.price import PriceHistory
from app.models.scrape_log import ScrapeLog
from app.models.alert import PriceAlert

__all__ = ['Product', 'Retailer', 'PriceHistory', 'ScrapeLog', 'PriceAlert']
