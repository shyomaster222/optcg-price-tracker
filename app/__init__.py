import os
from flask import Flask
from app.config import config
from app.extensions import db, migrate


def create_app(config_name=None):
    """Application factory"""
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)

    # Register blueprints
    from app.routes.main import main_bp
    from app.routes.api import api_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)

    # Create database tables and seed if empty
    with app.app_context():
        db.create_all()
        _seed_if_empty()

    # Initialize scheduler for automated price scraping (daily at midnight UTC)
    from app.tasks.scheduler import init_scheduler
    init_scheduler(app)

    return app


def _seed_if_empty():
    """Seed database with products and retailers if empty"""
    from app.models.product import Product
    from app.models.retailer import Retailer
    from datetime import date

    # Check if already seeded
    if Product.query.first() is not None:
        return

    print("Seeding database with products and retailers...")

    # Retailers
    retailers_data = [
        {"name": "Amazon Japan", "slug": "amazon-jp", "base_url": "https://www.amazon.co.jp", "country": "JP", "currency": "JPY", "min_delay_seconds": 3, "max_delay_seconds": 6, "requests_per_minute": 8},
        {"name": "TCGRepublic", "slug": "tcgrepublic", "base_url": "https://tcgrepublic.com", "country": "JP", "currency": "USD", "min_delay_seconds": 2, "max_delay_seconds": 4, "requests_per_minute": 12},
        {"name": "eBay", "slug": "ebay", "base_url": "https://www.ebay.com", "country": "US", "currency": "USD", "min_delay_seconds": 2, "max_delay_seconds": 4, "requests_per_minute": 15},
    ]

    for r in retailers_data:
        db.session.add(Retailer(**r))

    # Products
    sets_data = [
        {"set_code": "OP-01", "set_name": "ROMANCE DAWN", "release_date": date(2022, 12, 2), "msrp_jpy": 6600},
        {"set_code": "OP-02", "set_name": "PARAMOUNT WAR", "release_date": date(2023, 3, 10), "msrp_jpy": 6600},
        {"set_code": "OP-03", "set_name": "PILLARS OF STRENGTH", "release_date": date(2023, 6, 30), "msrp_jpy": 6600},
        {"set_code": "OP-04", "set_name": "KINGDOMS OF INTRIGUE", "release_date": date(2023, 9, 22), "msrp_jpy": 6600},
        {"set_code": "OP-05", "set_name": "AWAKENING OF THE NEW ERA", "release_date": date(2023, 12, 2), "msrp_jpy": 6600},
        {"set_code": "OP-06", "set_name": "WINGS OF THE CAPTAIN", "release_date": date(2024, 3, 15), "msrp_jpy": 6600},
        {"set_code": "OP-07", "set_name": "500 YEARS IN THE FUTURE", "release_date": date(2024, 6, 28), "msrp_jpy": 6600},
        {"set_code": "OP-08", "set_name": "TWO LEGENDS", "release_date": date(2024, 9, 13), "msrp_jpy": 6600},
        {"set_code": "OP-09", "set_name": "EMPERORS IN THE NEW WORLD", "release_date": date(2024, 12, 13), "msrp_jpy": 6600},
        {"set_code": "OP-10", "set_name": "ROYAL BLOOD", "release_date": date(2025, 3, 21), "msrp_jpy": 6600},
        {"set_code": "OP-11", "set_name": "A FIST OF DIVINE SPEED", "release_date": date(2025, 6, 6), "msrp_jpy": 6600},
        {"set_code": "OP-12", "set_name": "LEGACY OF THE MASTER", "release_date": date(2025, 8, 22), "msrp_jpy": 6600},
        {"set_code": "OP-13", "set_name": "CARRYING ON HIS WILL", "release_date": date(2025, 11, 21), "msrp_jpy": 6600},
        {"set_code": "OP-14", "set_name": "THE AZURE SEA'S SEVEN", "release_date": date(2026, 1, 16), "msrp_jpy": 6600},
        {"set_code": "EB-01", "set_name": "MEMORIAL COLLECTION", "release_date": date(2024, 1, 27), "msrp_jpy": 6600},
        {"set_code": "EB-02", "set_name": "ANIME 25TH COLLECTION", "release_date": date(2024, 10, 26), "msrp_jpy": 6600},
        {"set_code": "EB-03", "set_name": "HEROINES EDITION", "release_date": date(2025, 5, 24), "msrp_jpy": 6600},
        {"set_code": "PRB-01", "set_name": "THE BEST", "release_date": date(2024, 5, 25), "msrp_jpy": 8800},
    ]

    for s in sets_data:
        for product_type in ['box', 'case']:
            db.session.add(Product(
                set_code=s["set_code"],
                set_name=s["set_name"],
                release_date=s["release_date"],
                msrp_jpy=s["msrp_jpy"],
                product_type=product_type,
                packs_per_box=24 if product_type == 'box' else None,
                boxes_per_case=12 if product_type == 'case' else None
            ))

    db.session.commit()
    print(f"Seeded {Product.query.count()} products and {Retailer.query.count()} retailers")
