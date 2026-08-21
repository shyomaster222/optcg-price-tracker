#!/usr/bin/env python3
"""
CLI entrypoint for the RCJ <- Fuji price sync.

Usage:
    python scripts/run_price_sync.py          # run one sync pass (respects PRICE_SYNC_DRY_RUN)
    python scripts/run_price_sync.py --email  # also send the summary/review email
    python scripts/run_price_sync.py --refresh-prices --email
                                              # scrape first, then sync and email

This is what the daily schedule calls. It ensures the price_sync_log table
exists (db.create_all is idempotent), runs the guardrail engine, and prints a
summary. Whether anything is written to Shopify depends on PRICE_SYNC_DRY_RUN /
PRICE_SYNC_ENABLED in the environment.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.extensions import db
import app.models  # noqa: F401  (registers all models incl. PriceSyncLog)
from app.services.price_sync_service import run_price_sync


def refresh_prices_or_raise() -> int:
    """Refresh all sources and fail closed unless Fuji returned current rows."""
    from app.scrapers.scraper_manager import ScraperManager

    scrape_results = ScraperManager().run_all()
    fuji_rows = scrape_results.get("FujiCardShop", [])
    if not fuji_rows:
        raise RuntimeError(
            "Fuji refresh failed; refusing to sync or send a stale report"
        )
    return len(fuji_rows)


def main():
    parser = argparse.ArgumentParser(description="RCJ <- Fuji price sync")
    parser.add_argument("--email", action="store_true", help="Send the summary/review email after the run")
    parser.add_argument(
        "--refresh-prices",
        action="store_true",
        help="Scrape all retailers first and stop if Fuji returns no current data",
    )
    args = parser.parse_args()

    app = create_app(start_scheduler=False)
    with app.app_context():
        db.create_all()  # creates price_sync_log if missing; no-op otherwise

        print("=" * 60)
        print("RCJ Price Sync")
        print(f"  enabled={app.config.get('PRICE_SYNC_ENABLED')}  dry_run={app.config.get('PRICE_SYNC_DRY_RUN')}")
        print(f"  undercut={app.config.get('UNDERCUT_PCT')}  tolerance={app.config.get('AUTO_TOLERANCE')}")
        print("=" * 60)

        if args.refresh_prices:
            print("\nRefreshing competitor prices before the sync...")
            fuji_count = refresh_prices_or_raise()
            print(f"FujiCardShop returned {fuji_count} rows.")

        summary = run_price_sync()

        counts = summary["counts"]
        print(f"\nResults: {counts}")
        if summary.get("note"):
            print(f"Note: {summary['note']}")
        for r in summary["results"]:
            flag = {"auto_applied": "APPLY", "held": "HOLD ", "skipped": "skip ", "error": "ERROR"}.get(r["action"], "?")
            cur = f"${r['current_price']:.2f}" if r["current_price"] is not None else "—"
            fuji = f"${r['fuji_price']:.2f}" if r["fuji_price"] is not None else "—"
            tgt = f"${r['target_price']:.2f}" if r["target_price"] is not None else "—"
            print(f"  [{flag}] {r['set_code']:>6} {r['product_type']:<4} "
                  f"cur={cur:>9} fuji={fuji:>9} target={tgt:>9}  {r['reason']}")

        if args.email:
            from app.services.email_service import send_price_sync_report
            send_price_sync_report(summary)
            print("\nEmail sent.")

        print("\nDone.")


if __name__ == "__main__":
    main()
