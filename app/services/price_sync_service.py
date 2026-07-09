"""
app/services/price_sync_service.py

The price-sync guardrail engine.

For every product in the hand-verified price_map.json it:
  1. reads the latest Fuji price (from the tracker DB, matched by exact fuji_url),
  2. reads the current RCJ price (live, from products.json),
  3. computes an undercut target (Fuji x (1 - UNDERCUT_PCT)),
  4. decides AUTO_APPLY / HELD / SKIPPED using the floor + tolerance guardrails,
  5. writes auto-approved prices to Shopify (unless dry-run),
  6. records every decision in the price_sync_log table.

Nothing outside price_map.json is ever touched. Large changes and sub-floor
targets are held for human review rather than applied.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from flask import current_app
from sqlalchemy import func

from app.extensions import db
from app.models.price import PriceHistory
from app.models.price_sync_log import PriceSyncLog
from app.models.retailer import Retailer
from app.services import rcj_shopify
from app.services.price_sync_config import load_price_map, load_price_floors

logger = logging.getLogger(__name__)

AUTO_APPLIED = "auto_applied"
HELD = "held"
SKIPPED = "skipped"
ERROR = "error"


def round_price(value: float, round_99: bool) -> float:
    if round_99:
        base = round(value)
        return float(base - 0.01) if base >= 1 else round(value, 2)
    return round(value, 2)


def _latest_fuji_price(fuji_retailer_id: int, fuji_url: str, fresh_since: datetime) -> Optional[dict]:
    """Latest fresh, in-stock Fuji price row matching this exact URL. Returns dict or None."""
    row = (
        PriceHistory.query
        .filter(
            PriceHistory.retailer_id == fuji_retailer_id,
            PriceHistory.source_url == fuji_url,
            PriceHistory.scraped_at >= fresh_since,
        )
        .order_by(PriceHistory.scraped_at.desc())
        .first()
    )
    if row is None:
        return None
    price = row.price_usd if row.price_usd is not None else row.price
    if price is None:
        return None
    return {"price": float(price), "in_stock": bool(row.in_stock), "scraped_at": row.scraped_at}


def run_price_sync() -> dict:
    """Run one sync pass. Returns a summary dict with per-product results."""
    cfg = current_app.config
    dry_run = cfg.get("PRICE_SYNC_DRY_RUN", True)

    summary = {
        "enabled": cfg.get("PRICE_SYNC_ENABLED", False),
        "dry_run": dry_run,
        "results": [],
        "counts": {AUTO_APPLIED: 0, HELD: 0, SKIPPED: 0, ERROR: 0},
        "run_at": datetime.utcnow().isoformat(),
    }

    if not cfg.get("PRICE_SYNC_ENABLED", False):
        logger.info("price_sync: PRICE_SYNC_ENABLED is false; nothing to do")
        summary["note"] = "disabled"
        return summary

    entries = load_price_map()
    if not entries:
        logger.warning("price_sync: price_map is empty; nothing to do")
        summary["note"] = "empty price_map"
        return summary

    floors = load_price_floors()
    undercut = cfg.get("UNDERCUT_PCT", 0.03)
    tolerance = cfg.get("AUTO_TOLERANCE", 0.05)
    max_drop = cfg.get("MAX_DROP", 0.30)
    eps = cfg.get("NOOP_EPSILON", 0.01)
    eps_usd = cfg.get("NOOP_EPSILON_USD", 0.50)
    round_99 = cfg.get("PRICE_ROUND_99", False)
    fresh_since = datetime.utcnow() - timedelta(hours=cfg.get("FUJI_FRESH_HOURS", 48))

    fuji = Retailer.query.filter_by(slug="fujicardshop").first()
    if fuji is None:
        summary["note"] = "fujicardshop retailer missing"
        logger.error("price_sync: fujicardshop retailer not found in DB")
        return summary

    # Current RCJ prices for just the mapped variants, via the authenticated Admin
    # API (avoids the rate-limited public products.json).
    try:
        variant_ids = [int(e["rcj_variant_id"]) for e in entries]
        rcj_prices = rcj_shopify.fetch_prices_by_variant_ids(variant_ids)
    except Exception as exc:
        summary["note"] = f"failed to fetch RCJ prices: {exc}"
        logger.error("price_sync: could not fetch RCJ prices via Admin API: %s", exc)
        return summary

    for e in entries:
        variant_id = int(e["rcj_variant_id"])
        result = {
            "set_code": e.get("set_code"),
            "product_type": e.get("product_type"),
            "rcj_handle": e.get("rcj_handle"),
            "rcj_variant_id": variant_id,
            "fuji_url": e.get("fuji_url"),
            "fuji_price": None,
            "current_price": None,
            "target_price": None,
            "floor_price": None,
            "pct_change": None,
            "action": SKIPPED,
            "reason": "",
            "applied": False,
        }

        # --- current RCJ price ---
        live = rcj_prices.get(variant_id)
        if not live:
            result["reason"] = "variant not found in live RCJ catalog"
            _record(result, dry_run, summary)
            continue
        current = live["price"]
        product_id = live.get("product_id") or e.get("rcj_product_id")
        result["current_price"] = current

        # --- latest Fuji price ---
        fuji_row = _latest_fuji_price(fuji.id, e["fuji_url"], fresh_since)
        if fuji_row is None:
            result["reason"] = "no fresh Fuji price for this URL"
            _record(result, dry_run, summary)
            continue
        if not fuji_row["in_stock"]:
            result["reason"] = "Fuji listing out of stock"
            _record(result, dry_run, summary)
            continue
        fuji_price = fuji_row["price"]
        result["fuji_price"] = fuji_price

        if current <= 0:
            result["reason"] = "current RCJ price is zero"
            _record(result, dry_run, summary)
            continue

        # --- target + guardrails ---
        target = round_price(fuji_price * (1 - undercut), round_99)
        configured_floor = floors.get(e.get("set_code"), e.get("product_type"))
        relative_floor = current * (1 - max_drop)
        floor = max(relative_floor, configured_floor) if configured_floor is not None else relative_floor
        change = (target - current) / current

        result["target_price"] = target
        result["floor_price"] = round(floor, 2)
        result["pct_change"] = change

        if target < floor:
            result["action"] = HELD
            result["reason"] = f"target ${target:.2f} below floor ${floor:.2f}"
        elif abs(change) < eps and abs(target - current) < eps_usd:
            result["action"] = SKIPPED
            result["reason"] = "no meaningful change"
        elif abs(change) <= tolerance:
            ok, err = rcj_shopify.update_variant_price(product_id, variant_id, target)
            if ok:
                result["action"] = AUTO_APPLIED
                result["applied"] = not dry_run
                result["reason"] = ("dry-run: would apply" if dry_run
                                    else f"applied {current:.2f} -> {target:.2f}")
            else:
                result["action"] = ERROR
                result["reason"] = f"Shopify update failed: {err}"
        else:
            result["action"] = HELD
            result["reason"] = f"change {change * 100:+.1f}% exceeds {tolerance * 100:.0f}% tolerance"

        _record(result, dry_run, summary)

    # Data-freshness alarm: if products are skipping because Fuji data is stale,
    # surface it loudly so a silent scrape outage can't hide again.
    stale_count = sum(1 for r in summary["results"] if "no fresh Fuji" in (r["reason"] or ""))
    newest = (
        PriceHistory.query.filter_by(retailer_id=fuji.id)
        .order_by(PriceHistory.scraped_at.desc()).first()
    )
    newest_at = newest.scraped_at if newest else None
    summary["fuji_last_scraped"] = newest_at.isoformat() if newest_at else None
    summary["fuji_stale_count"] = stale_count
    summary["fuji_stale"] = stale_count > 0
    if newest_at is not None:
        summary["fuji_age_hours"] = round((datetime.utcnow() - newest_at).total_seconds() / 3600, 1)
    else:
        summary["fuji_age_hours"] = None

    db.session.commit()
    logger.info("price_sync: done — %s (fuji_stale=%s, age=%sh)",
                summary["counts"], summary["fuji_stale"], summary.get("fuji_age_hours"))
    return summary


def _record(result: dict, dry_run: bool, summary: dict) -> None:
    """Append to summary and stage a PriceSyncLog row."""
    summary["results"].append(result)
    summary["counts"][result["action"]] = summary["counts"].get(result["action"], 0) + 1
    db.session.add(PriceSyncLog(
        set_code=result["set_code"],
        product_type=result["product_type"],
        rcj_handle=result["rcj_handle"],
        rcj_variant_id=result["rcj_variant_id"],
        fuji_url=result["fuji_url"],
        fuji_price=result["fuji_price"],
        current_price=result["current_price"],
        target_price=result["target_price"],
        floor_price=result["floor_price"],
        pct_change=result["pct_change"],
        action=result["action"],
        reason=result["reason"],
        applied=result["applied"],
        dry_run=dry_run,
    ))


def apply_one(variant_id: int) -> dict:
    """Manually apply the latest held target for a single variant (from /admin/price-review).

    Recomputes against the current live price and writes it, ignoring the tolerance
    gate (this is an explicit human approval) but still respecting the floor."""
    cfg = current_app.config
    entries = {int(e["rcj_variant_id"]): e for e in load_price_map()}
    e = entries.get(int(variant_id))
    if not e:
        return {"ok": False, "error": "variant not in price_map"}

    floors = load_price_floors()
    undercut = cfg.get("UNDERCUT_PCT", 0.03)
    max_drop = cfg.get("MAX_DROP", 0.30)
    round_99 = cfg.get("PRICE_ROUND_99", False)
    fresh_since = datetime.utcnow() - timedelta(hours=cfg.get("FUJI_FRESH_HOURS", 48))

    fuji = Retailer.query.filter_by(slug="fujicardshop").first()
    if fuji is None:
        return {"ok": False, "error": "fujicardshop retailer missing"}

    rcj_prices = rcj_shopify.fetch_prices_by_variant_ids([int(variant_id)])
    live = rcj_prices.get(int(variant_id))
    if not live:
        return {"ok": False, "error": "variant not found in live RCJ catalog"}
    current = live["price"]
    product_id = live.get("product_id") or e.get("rcj_product_id")

    fuji_row = _latest_fuji_price(fuji.id, e["fuji_url"], fresh_since)
    if fuji_row is None:
        return {"ok": False, "error": "no fresh Fuji price for this URL"}

    target = round_price(fuji_row["price"] * (1 - undercut), round_99)
    configured_floor = floors.get(e.get("set_code"), e.get("product_type"))
    relative_floor = current * (1 - max_drop)
    floor = max(relative_floor, configured_floor) if configured_floor is not None else relative_floor
    if target < floor:
        return {"ok": False, "error": f"target ${target:.2f} below floor ${floor:.2f}"}

    ok, err = rcj_shopify.update_variant_price(product_id, variant_id, target)
    dry_run = cfg.get("PRICE_SYNC_DRY_RUN", True)
    db.session.add(PriceSyncLog(
        set_code=e.get("set_code"), product_type=e.get("product_type"),
        rcj_handle=e.get("rcj_handle"), rcj_variant_id=int(variant_id),
        fuji_url=e.get("fuji_url"), fuji_price=fuji_row["price"], current_price=current,
        target_price=target, floor_price=round(floor, 2),
        pct_change=(target - current) / current if current else None,
        action=AUTO_APPLIED if ok else ERROR,
        reason="manual apply" if ok else f"manual apply failed: {err}",
        applied=ok and not dry_run, dry_run=dry_run,
    ))
    db.session.commit()
    if not ok:
        return {"ok": False, "error": err, "target": target, "current": current}
    return {"ok": True, "target": target, "current": current, "applied": not dry_run, "dry_run": dry_run}
