#!/usr/bin/env python3
"""
Seed script to populate the database with One Piece TCG products and retailers.
Run with: python scripts/seed_products.py
"""

import sys
import os
from datetime import date

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.product import Product
from app.models.retailer import Retailer

# One Piece TCG Booster Sets (Japanese releases)
BOOSTER_SETS = [
    {"set_code": "OP-01", "set_name": "ROMANCE DAWN", "set_name_jp": "ROMANCE DAWN", "release_date": date(2022, 12, 2), "msrp_jpy": 6600},
    {"set_code": "OP-02", "set_name": "PARAMOUNT WAR", "set_name_jp": "頂上決戦", "release_date": date(2023, 3, 10), "msrp_jpy": 6600},
    {"set_code": "OP-03", "set_name": "PILLARS OF STRENGTH", "set_name_jp": "強大な敵", "release_date": date(2023, 6, 30), "msrp_jpy": 6600},
    {"set_code": "OP-04", "set_name": "KINGDOMS OF INTRIGUE", "set_name_jp": "謀略の王国", "release_date": date(2023, 9, 22), "msrp_jpy": 6600},
    {"set_code": "OP-05", "set_name": "AWAKENING OF THE NEW ERA", "set_name_jp": "新時代の主役", "release_date": date(2023, 12, 2), "msrp_jpy": 6600},
    {"set_code": "OP-06", "set_name": "WINGS OF THE CAPTAIN", "set_name_jp": "双璧の覇者", "release_date": date(2024, 3, 15), "msrp_jpy": 6600},
    {"set_code": "OP-07", "set_name": "500 YEARS IN THE FUTURE", "set_name_jp": "500年後の未来", "release_date": date(2024, 6, 28), "msrp_jpy": 6600},
    {"set_code": "OP-08", "set_name": "TWO LEGENDS", "set_name_jp": "二つの伝説", "release_date": date(2024, 9, 13), "msrp_jpy": 6600},
    {"set_code": "OP-09", "set_name": "EMPERORS IN THE NEW WORLD", "set_name_jp": "新世界の皇帝達", "release_date": date(2024, 12, 13), "msrp_jpy": 6600},
    {"set_code": "OP-10", "set_name": "ROYAL BLOOD", "set_name_jp": "ロイヤルブラッド", "release_date": date(2025, 3, 21), "msrp_jpy": 6600},
    {"set_code": "OP-11", "set_name": "A FIST OF DIVINE SPEED", "set_name_jp": "神速の拳", "release_date": date(2025, 6, 6), "msrp_jpy": 6600},
    {"set_code": "OP-12", "set_name": "LEGACY OF THE MASTER", "set_name_jp": "師の遺産", "release_date": date(2025, 8, 22), "msrp_jpy": 6600},
    # Extra Boosters
    {"set_code": "EB-01", "set_name": "MEMORIAL COLLECTION", "set_name_jp": "メモリアルコレクション", "release_date": date(2024, 1, 27), "msrp_jpy": 6600},
    {"set_code": "EB-02", "set_name": "ANIME 25TH COLLECTION", "set_name_jp": "アニメ25周年コレクション", "release_date": date(2024, 10, 26), "msrp_jpy": 6600},
    {"set_code": "EB-03", "set_name": "HEROINES EDITION", "set_name_jp": "ヒロインズエディション", "release_date": date(2025, 5, 24), "msrp_jpy": 6600},
    # Premium Boosters
    {"set_code": "PRB-01", "set_name": "THE BEST", "set_name_jp": "THE BEST", "release_date": date(2024, 5, 25), "msrp_jpy": 8800},
]

# Retailers to track
RETAILERS = [
    {"name": "Amazon Japan", "slug": "amazon-jp", "base_url": "https://www.amazon.co.jp", "country": "JP", "currency": "JPY", "min_delay_seconds": 3, "max_delay_seconds": 6, "requests_per_minute": 8},
    {"name": "TCGRepublic", "slug": "tcgrepublic", "base_url": "https://tcgrepublic.com", "country": "JP", "currency": "USD", "min_delay_seconds": 2, "max_delay_seconds": 4, "requests_per_minute": 12},
    {"name": "eBay", "slug": "ebay", "base_url": "https://www.ebay.com", "country": "US", "currency": "USD", "min_delay_seconds": 2, "max_delay_seconds": 4, "requests_per_minute": 15},
    {"name": "PriceCharting", "slug": "pricecharting", "base_url": "https://www.pricecharting.com", "country": "US", "currency": "USD", "min_delay_seconds": 2, "max_delay_seconds": 4, "requests_per_minute": 10},
    {"name": "Japan TCG Store", "slug": "japantcg", "base_url": "https://japantradingcardstore.com", "country": "US", "currency": "USD", "min_delay_seconds": 2, "max_delay_seconds": 4, "requests_per_minute": 12},
    {"name": "TCG Hobby", "slug": "tcghobby", "base_url": "https://tcghobby.com", "country": "US", "currency": "USD", "min_delay_seconds": 2, "max_delay_seconds": 4, "requests_per_minute": 12},
    {"name": "FP Trading Cards", "slug": "fptradingcards", "base_url": "https://www.fptradingcards.com", "country": "US", "currency": "USD", "min_delay_seconds": 2, "max_delay_seconds": 4, "requests_per_minute": 12},
    {"name": "PVP Shoppe", "slug": "pvpshoppe", "base_url": "https://pvpshoppe.com", "country": "CA", "currency": "USD", "min_delay_seconds": 2, "max_delay_seconds": 4, "requests_per_minute": 12},
    {"name": "A Hidden Fortress", "slug": "ahiddenfortress", "base_url": "https://www.ahiddenfortress.com", "country": "US", "currency": "USD", "min_delay_seconds": 2, "max_delay_seconds": 4, "requests_per_minute": 12},
]


def seed_retailers():
    """Add retailers to database"""
    print("Seeding retailers...")
    for retailer_data in RETAILERS:
        existing = Retailer.query.filter_by(slug=retailer_data["slug"]).first()
        if existing:
            print(f"  Retailer {retailer_data['name']} already exists, skipping...")
            continue

        retailer = Retailer(**retailer_data)
        db.session.add(retailer)
        print(f"  Added retailer: {retailer_data['name']}")

    db.session.commit()
    print(f"  Total retailers: {Retailer.query.count()}")


def seed_products():
    """Add products to database (both boxes and cases)"""
    print("Seeding products...")

    for set_data in BOOSTER_SETS:
        # Create booster box entry
        box_data = {**set_data, "product_type": "box", "packs_per_box": 24}
        existing_box = Product.query.filter_by(
            set_code=set_data["set_code"],
            product_type="box"
        ).first()

        if not existing_box:
            box = Product(**box_data)
            db.session.add(box)
            print(f"  Added box: {set_data['set_code']} - {set_data['set_name']}")

        # Create case entry
        case_data = {**set_data, "product_type": "case", "boxes_per_case": 12}
        existing_case = Product.query.filter_by(
            set_code=set_data["set_code"],
            product_type="case"
        ).first()

        if not existing_case:
            case = Product(**case_data)
            db.session.add(case)
            print(f"  Added case: {set_data['set_code']} - {set_data['set_name']}")

    db.session.commit()
    print(f"  Total products: {Product.query.count()}")


def main():
    """Main seed function"""
    app = create_app()

    with app.app_context():
        print("=" * 50)
        print("OPTCG Price Tracker - Database Seeder")
        print("=" * 50)

        seed_retailers()
        print()
        seed_products()

        print()
        print("=" * 50)
        print("Seeding complete!")
        print(f"  Retailers: {Retailer.query.count()}")
        print(f"  Products: {Product.query.count()}")
        print("=" * 50)


if __name__ == "__main__":
    main()
