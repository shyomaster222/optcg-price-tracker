"""
tests/conftest.py

Shared pytest fixtures for the OPTCG Price Tracker test suite.

Fixtures
--------
app         - Flask application configured with TestingConfig (in-memory SQLite).
              Registers all blueprints including the new alerts and export ones.
db_session  - Database session with tables created; rolled back after each test.
client      - Flask test client bound to the test app.
sample_data - Seed 2 products + 2 retailers + sample PriceHistory rows.
"""

import os
import pytest
from datetime import datetime, date

# Disable the scheduler and external calls before any app import
os.environ.setdefault("ENABLE_IN_PROCESS_SCHEDULER", "false")


@pytest.fixture(scope="session")
def app():
    """
    Create a Flask application instance configured for testing.

    Uses TestingConfig (in-memory SQLite).  The in-process scheduler is
    disabled so it does not interfere with test isolation.  The new
    alerts and export blueprints are registered if they exist.
    """
    from app import create_app
    from app.extensions import db as _db

    application = create_app("testing")

    # Ensure scheduler is off in tests
    application.config["ENABLE_IN_PROCESS_SCHEDULER"] = False
    application.config["SCHEDULER_API_ENABLED"] = False

    with application.app_context():
        # Register new blueprints added by improvements (safe no-op if missing)
        _register_optional_blueprints(application)

        _db.create_all()
        yield application
        _db.drop_all()


def _register_optional_blueprints(app):
    """
    Register blueprints introduced by improvements if they are not already
    registered.  Using try/except so tests degrade gracefully when a
    blueprint module doesn't exist yet.
    """
    existing = {bp.name for bp in app.blueprints.values()}

    # Alerts blueprint: app/routes/api_alerts.py  ->  alerts_bp
    if "alerts" not in existing:
        try:
            from app.routes.api_alerts import alerts_bp
            app.register_blueprint(alerts_bp)
        except ImportError:
            pass

    # Export blueprint: app/routes/api_export.py  ->  export_bp
    if "export" not in existing:
        try:
            from app.routes.api_export import export_bp
            app.register_blueprint(export_bp)
        except ImportError:
            pass


@pytest.fixture(scope="function")
def db_session(app):
    """
    Provide a transactional scope around each test.

    Each test starts with an empty database (tables exist but no rows) so
    tests are fully independent.
    """
    from app.extensions import db as _db

    with app.app_context():
        # Drop and recreate all tables to guarantee a clean state per test.
        _db.drop_all()
        _db.create_all()
        yield _db.session
        _db.session.remove()


@pytest.fixture(scope="function")
def client(app, db_session):
    """
    Flask test client.

    Depends on db_session so the database is always initialised before any
    HTTP request is made.
    """
    return app.test_client()


# ---------------------------------------------------------------------------
# Seed data fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def sample_data(app, db_session):
    """
    Seed the test database with:
    - 2 Products  : OP-01 box, OP-01 case
    - 2 Retailers : amazon-jp (JPY), ebay (USD)
    - 4 PriceHistory entries (2 per product, one per retailer)

    Returns a dict with the seeded ORM objects for easy reference in tests.
    """
    from app.extensions import db as _db
    from app.models.product import Product
    from app.models.retailer import Retailer
    from app.models.price import PriceHistory

    # --- Products ---
    product_box = Product(
        set_code="OP-01",
        set_name="ROMANCE DAWN",
        product_type="box",
        release_date=date(2022, 12, 2),
        msrp_jpy=6600,
        packs_per_box=24,
        is_active=True,
    )
    product_case = Product(
        set_code="OP-01",
        set_name="ROMANCE DAWN",
        product_type="case",
        release_date=date(2022, 12, 2),
        msrp_jpy=6600,
        boxes_per_case=12,
        is_active=True,
    )
    _db.session.add_all([product_box, product_case])
    _db.session.flush()  # assign IDs without committing

    # --- Retailers ---
    retailer_amazon = Retailer(
        name="Amazon Japan",
        slug="amazon-jp",
        base_url="https://www.amazon.co.jp",
        country="JP",
        currency="JPY",
        min_delay_seconds=3,
        max_delay_seconds=6,
        requests_per_minute=8,
        is_active=True,
    )
    retailer_ebay = Retailer(
        name="eBay",
        slug="ebay",
        base_url="https://www.ebay.com",
        country="US",
        currency="USD",
        min_delay_seconds=2,
        max_delay_seconds=4,
        requests_per_minute=15,
        is_active=True,
    )
    _db.session.add_all([retailer_amazon, retailer_ebay])
    _db.session.flush()

    # --- PriceHistory ---
    now = datetime.utcnow()

    ph1 = PriceHistory(
        product_id=product_box.id,
        retailer_id=retailer_amazon.id,
        price=7800,
        price_usd=52.26,
        currency="JPY",
        in_stock=True,
        source_url="https://www.amazon.co.jp/s?k=op-01+box",
        scraped_at=now,
    )
    ph2 = PriceHistory(
        product_id=product_box.id,
        retailer_id=retailer_ebay.id,
        price=55.00,
        price_usd=55.00,
        currency="USD",
        in_stock=True,
        source_url="https://www.ebay.com/sch/i.html?_nkw=op-01+box",
        scraped_at=now,
    )
    ph3 = PriceHistory(
        product_id=product_case.id,
        retailer_id=retailer_amazon.id,
        price=85000,
        price_usd=569.50,
        currency="JPY",
        in_stock=False,
        source_url="https://www.amazon.co.jp/s?k=op-01+case",
        scraped_at=now,
    )
    ph4 = PriceHistory(
        product_id=product_case.id,
        retailer_id=retailer_ebay.id,
        price=600.00,
        price_usd=600.00,
        currency="USD",
        in_stock=True,
        source_url="https://www.ebay.com/sch/i.html?_nkw=op-01+case",
        scraped_at=now,
    )
    _db.session.add_all([ph1, ph2, ph3, ph4])
    _db.session.commit()

    return {
        "product_box": product_box,
        "product_case": product_case,
        "retailer_amazon": retailer_amazon,
        "retailer_ebay": retailer_ebay,
        "ph_box_amazon": ph1,
        "ph_box_ebay": ph2,
        "ph_case_amazon": ph3,
        "ph_case_ebay": ph4,
    }
