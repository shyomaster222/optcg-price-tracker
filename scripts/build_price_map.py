#!/usr/bin/env python3
"""
scripts/build_price_map.py

One-off generator for the RCJ <-> Fuji price link map.

It pairs every RareCardsJapan product/variant to a specific FujiCardShop product
URL, keyed by (set_code, product_type), and writes a DRAFT price_map.json for a
human to review. The daily price-sync job only ever touches products that appear
in the verified map, so this pairing is the safety boundary of the whole feature.

  RCJ side  -> matched later by exact rcj_variant_id (that's what we write to)
  Fuji side -> matched later by exact fuji_url against PriceHistory.source_url

Fuji source:
  Fuji blocks direct scraping from most IPs (403), but the tracker DB already
  stores Fuji rows (with source_url) from its daily scrape. So the Fuji side is
  read from the DB by default. Run this on Railway (or anywhere the DATABASE_URL
  points at the populated tracker DB). Use --fuji-source scrape to force a live
  scrape instead (only works from an IP Fuji allows).

The RCJ side is always read live from Shopify's products.json (not IP-blocked).

Usage:
    python scripts/build_price_map.py                     # Fuji from DB, RCJ live
    python scripts/build_price_map.py --fuji-source scrape
    python scripts/build_price_map.py --out foo.json --force
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

# Allow "python scripts/build_price_map.py" from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.scrapers.rarecardsjapan_scraper import RareCardsJapanScraper

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(REPO_ROOT, "price_map.json")


# ---------------------------------------------------------------------------
# Fuji side
# ---------------------------------------------------------------------------

def fuji_from_db():
    """Return {(set_code, product_type): {url: price}} from the tracker DB.

    Uses the latest Fuji PriceHistory row per product, so each product resolves
    to exactly one fuji_url (no ambiguity)."""
    from app.models.product import Product
    from app.models.price import PriceHistory
    from app.models.retailer import Retailer

    fuji = Retailer.query.filter_by(slug="fujicardshop").first()
    if fuji is None:
        print("  WARN: fujicardshop retailer not found in DB", flush=True)
        return {}

    by_key: dict = defaultdict(dict)
    products = Product.query.all()
    for p in products:
        latest = (
            PriceHistory.query
            .filter_by(product_id=p.id, retailer_id=fuji.id)
            .order_by(PriceHistory.scraped_at.desc())
            .first()
        )
        if latest is None or not latest.source_url:
            continue
        price = float(latest.price_usd if latest.price_usd is not None else latest.price)
        by_key[(p.set_code, p.product_type)][latest.source_url] = price
    print(f"  Fuji (DB): {len(by_key)} (set, type) keys with a source_url", flush=True)
    return by_key


def fuji_from_scrape():
    """Return {(set_code, product_type): {url: price}} by live-scraping Fuji."""
    from app.scrapers.fujicardshop_scraper import FujiCardShopScraper
    records = FujiCardShopScraper().scrape()
    by_key: dict = defaultdict(dict)
    for r in records:
        key = (r["set_code"], r["product_type"])
        url = r.get("source_url")
        if not url:
            continue
        price = float(r["price_usd"] if r.get("price_usd") is not None else r["price"])
        prev = by_key[key].get(url)
        if prev is None or price < prev:
            by_key[key][url] = price
    print(f"  Fuji (scrape): {len(records)} raw records across {len(by_key)} keys", flush=True)
    return by_key


# ---------------------------------------------------------------------------
# RCJ side
# ---------------------------------------------------------------------------

def collect_rcj():
    """Return a list of RCJ variant rows with Shopify identifiers (live)."""
    print("Fetching RareCardsJapan products.json ...", flush=True)
    scraper = RareCardsJapanScraper()
    products = scraper._fetch_all_products()  # raw Shopify product dicts
    rows = []
    for p in products:
        title = p.get("title", "")
        set_code = scraper._detect_set_code(title)
        if not set_code:
            continue
        product_type = scraper._detect_product_type(title)
        handle = p.get("handle", "")
        variants = p.get("variants", []) or []
        for variant in variants:
            try:
                price = float(variant.get("price", "0"))
            except (ValueError, TypeError):
                price = None
            rows.append({
                "set_code": set_code,
                "product_type": product_type,
                "rcj_handle": handle,
                "rcj_product_id": p.get("id"),
                "rcj_variant_id": variant.get("id"),
                "rcj_variant_title": variant.get("title"),
                "rcj_title": title,
                "rcj_current_price": price,
                "rcj_variant_count": len(variants),
                "rcj_available": bool(variant.get("available")),
            })
    print(f"  RCJ: {len(rows)} variant rows matched to a set code", flush=True)
    return rows


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------

def build(fuji_by_key, rcj_rows):
    """Pair RCJ variants with Fuji URLs. Returns (mapped, review)."""
    mapped = []
    review = {"multiple_fuji_urls": [], "no_fuji_match": [], "multi_variant": [], "fuji_unmatched": []}

    matched_fuji_keys = set()

    for row in rcj_rows:
        key = (row["set_code"], row["product_type"])
        fuji_urls = fuji_by_key.get(key, {})

        if row["rcj_variant_count"] > 1:
            review["multi_variant"].append({
                "set_code": row["set_code"], "product_type": row["product_type"],
                "rcj_title": row["rcj_title"], "rcj_variant_title": row["rcj_variant_title"],
                "rcj_variant_id": row["rcj_variant_id"],
            })

        if not fuji_urls:
            review["no_fuji_match"].append({
                "set_code": row["set_code"], "product_type": row["product_type"],
                "rcj_title": row["rcj_title"], "rcj_handle": row["rcj_handle"],
            })
            continue

        matched_fuji_keys.add(key)

        if len(fuji_urls) > 1:
            review["multiple_fuji_urls"].append({
                "set_code": row["set_code"], "product_type": row["product_type"],
                "rcj_title": row["rcj_title"], "candidates": fuji_urls,
            })
            chosen_url, chosen_price = "", None
            note = "REVIEW: multiple Fuji URLs for this set/type — pick one from price_map.report.json"
        else:
            chosen_url, chosen_price = next(iter(fuji_urls.items()))
            note = "" if row["rcj_variant_count"] == 1 else "REVIEW: RCJ product has multiple variants"

        mapped.append({
            "set_code": row["set_code"],
            "product_type": row["product_type"],
            "rcj_handle": row["rcj_handle"],
            "rcj_product_id": row["rcj_product_id"],
            "rcj_variant_id": row["rcj_variant_id"],
            "rcj_title": row["rcj_title"],
            "rcj_current_price": row["rcj_current_price"],
            "fuji_url": chosen_url,
            "fuji_price_at_build": chosen_price,
            "enabled": bool(chosen_url),  # ambiguous rows start disabled until a URL is chosen
            "note": note,
        })

    for key, urls in fuji_by_key.items():
        if key not in matched_fuji_keys:
            review["fuji_unmatched"].append({
                "set_code": key[0], "product_type": key[1], "fuji_urls": list(urls.keys()),
            })

    mapped.sort(key=lambda r: (r["set_code"], r["product_type"]))
    return mapped, review


def get_fuji(source):
    """Resolve the Fuji URL map from the requested source, with auto fallback."""
    if source in ("db", "auto"):
        from app import create_app
        app = create_app()
        with app.app_context():
            by_key = fuji_from_db()
        if by_key:
            return by_key
        if source == "db":
            return by_key
        print("  Fuji DB empty — falling back to live scrape ...", flush=True)
    print("Scraping FujiCardShop listings ...", flush=True)
    return fuji_from_scrape()


def main():
    parser = argparse.ArgumentParser(description="Generate the RCJ<->Fuji price link map (draft).")
    parser.add_argument("--out", default=DEFAULT_OUT, help="Output path (default: price_map.json)")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing price_map.json in place")
    parser.add_argument("--fuji-source", choices=["db", "scrape", "auto"], default="auto",
                        help="Where to read Fuji URLs from (default: auto = DB then scrape)")
    args = parser.parse_args()

    out_path = args.out
    if out_path == DEFAULT_OUT and os.path.exists(DEFAULT_OUT) and not args.force:
        out_path = os.path.join(REPO_ROOT, "price_map.generated.json")
        print(f"price_map.json already exists — writing draft to {os.path.basename(out_path)} instead "
              f"(diff it in, or use --force).", flush=True)

    fuji_by_key = get_fuji(args.fuji_source)
    rcj_rows = collect_rcj()
    mapped, review = build(fuji_by_key, rcj_rows)

    with open(out_path, "w") as f:
        json.dump(mapped, f, indent=2)
    report_path = os.path.join(os.path.dirname(out_path) or ".", "price_map.report.json")
    with open(report_path, "w") as f:
        json.dump(review, f, indent=2)

    enabled = sum(1 for m in mapped if m["enabled"])
    print("\n" + "=" * 60)
    print(f"Wrote {len(mapped)} mapped rows ({enabled} auto-enabled) -> {os.path.basename(out_path)}")
    print(f"Review report -> {os.path.basename(report_path)}")
    print(f"  multiple Fuji URLs (need manual pick): {len(review['multiple_fuji_urls'])}")
    print(f"  RCJ products with no Fuji match:       {len(review['no_fuji_match'])}")
    print(f"  RCJ multi-variant products:            {len(review['multi_variant'])}")
    print(f"  Fuji listings with no RCJ product:     {len(review['fuji_unmatched'])}")
    print("=" * 60)
    print("\nNEXT: open the JSON, confirm each rcj_variant_id <-> fuji_url pair, set")
    print("`enabled: false` on anything you do NOT want auto-priced, then (if needed)")
    print("rename to price_map.json and commit it.")


if __name__ == "__main__":
    main()
