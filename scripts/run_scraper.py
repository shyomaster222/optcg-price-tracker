#!/usr/bin/env python3
"""
CLI script to manually run scrapers.
Usage:
    python scripts/run_scraper.py              # Scrape all retailers
    python scripts/run_scraper.py amazon-jp   # Scrape specific retailer
    python scripts/run_scraper.py --list      # List available retailers
"""

import sys
import os
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.models.retailer import Retailer
from app.scrapers.scraper_manager import ScraperManager


def list_retailers(app):
    """List all available retailers"""
    with app.app_context():
        retailers = Retailer.query.filter_by(is_active=True).all()
        print("Available retailers:")
        for r in retailers:
            print(f"  - {r.slug}: {r.name} ({r.currency})")


def run_scrape(app, retailer_slug=None, limit=None, product_type=None):
    """Run scraping job"""
    with app.app_context():
        print("=" * 50)
        print("OPTCG Price Tracker - Manual Scraper")
        print("=" * 50)

        if retailer_slug:
            print(f"Scraping retailer: {retailer_slug}")
        else:
            print("Scraping all retailers")
        if limit:
            print(f"Products limit: {limit}")
        if product_type:
            print(f"Product type: {product_type}")

        print()

        manager = ScraperManager()
        manager.run_scrape_job(retailer_slug, product_limit=limit, product_type=product_type)

        print()
        print("Scraping complete!")
        print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="OPTCG Price Tracker Scraper CLI")
    parser.add_argument("retailer", nargs="?", help="Retailer slug to scrape (optional)")
    parser.add_argument("--list", action="store_true", help="List available retailers")
    parser.add_argument("--limit", type=int, help="Limit number of products to scrape (for quick testing)")
    parser.add_argument("--type", dest="product_type", choices=["box", "case"], help="Filter by product type (box or case)")

    args = parser.parse_args()

    app = create_app()

    if args.list:
        list_retailers(app)
    else:
        run_scrape(app, args.retailer, args.limit, args.product_type)


if __name__ == "__main__":
    main()
