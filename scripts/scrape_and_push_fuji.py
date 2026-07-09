#!/usr/bin/env python3
"""
Scrape FujiCardShop from THIS machine (residential IP — Cloudflare 200s it) and
push the results to the Railway app's /admin/ingest-fuji endpoint.

Railway's datacenter IP is Cloudflare-blocked (403), so the in-cloud scraper can't
fetch Fuji. Run this wherever Fuji is reachable (a laptop, a home server, a cron on
a residential box) to keep the tracker's Fuji data fresh.

Env / args:
  SHOPIFY_ADMIN_TOKEN  must match the value set on the Railway web service (used as
                       the X-Ingest-Key). Read from .env by default.
  --url                Railway base URL (default: the production app)

Usage:
  python scripts/scrape_and_push_fuji.py
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import requests
from app.scrapers.fujicardshop_scraper import FujiCardShopScraper

DEFAULT_URL = "https://web-production-d72a9.up.railway.app"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    args = ap.parse_args()

    key = os.environ.get("SHOPIFY_ADMIN_TOKEN")
    if not key:
        print("ERROR: SHOPIFY_ADMIN_TOKEN not set (needed as the ingest key).")
        sys.exit(1)

    print("Scraping FujiCardShop locally ...")
    recs = FujiCardShopScraper().scrape()
    payload = {"fuji": [{
        "set_code": r["set_code"], "product_type": r["product_type"],
        "price_usd": r["price_usd"], "in_stock": r["in_stock"],
        "source_url": r.get("source_url"),
    } for r in recs]}
    print(f"  scraped {len(recs)} Fuji records")

    resp = requests.post(f"{args.url}/admin/ingest-fuji",
                         headers={"X-Ingest-Key": key, "Content-Type": "application/json"},
                         json=payload, timeout=30)
    print(f"  ingest -> HTTP {resp.status_code}: {resp.text[:200]}")
    resp.raise_for_status()


if __name__ == "__main__":
    main()
