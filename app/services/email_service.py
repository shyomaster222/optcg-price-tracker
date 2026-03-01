"""
app/services/email_service.py

Daily price-comparison email service.

For each product that has a RareCardsJapan price entry the report computes:
  - Cheapest competitor price  (MIN price_usd from other retailers)
  - Average 24-hour market price (AVG price_usd from other retailers, last 24 h)

Both are compared against RCJ's price_usd.  Products that deviate ± 5 % are
flagged with a warning indicator.  The report is sent via the Resend API
(uses the existing `requests` dependency — no new packages needed).

Environment variables required:
  RESEND_API_KEY  – API key from resend.com
  COMPANY_EMAIL   – recipient address (also used as the From address)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional

import requests
from flask import current_app
from sqlalchemy import func

from app.extensions import db
from app.models.price import PriceHistory
from app.models.product import Product
from app.models.retailer import Retailer

logger = logging.getLogger(__name__)

_THRESHOLD_PCT = 5.0          # Flag if abs(pct_diff) >= this value
_MARKET_WINDOW_HOURS = 24     # Rolling window for average market price


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _get_rcj_retailer() -> Optional[Retailer]:
    return Retailer.query.filter_by(slug="rarecardsjapan").first()


def _latest_rcj_price(product_id: int, rcj_retailer_id: int) -> Optional[PriceHistory]:
    return (
        PriceHistory.query
        .filter_by(product_id=product_id, retailer_id=rcj_retailer_id)
        .order_by(PriceHistory.scraped_at.desc())
        .first()
    )


def _cheapest_competitor(product_id: int, exclude_retailer_id: int) -> Optional[float]:
    """Return MIN(price_usd) from all retailers except the excluded one."""
    result = (
        db.session.query(func.min(PriceHistory.price_usd))
        .filter(
            PriceHistory.product_id == product_id,
            PriceHistory.retailer_id != exclude_retailer_id,
            PriceHistory.price_usd.isnot(None),
        )
        .scalar()
    )
    return float(result) if result is not None else None


def _avg_market_price(product_id: int, exclude_retailer_id: int) -> Optional[float]:
    """Return AVG(price_usd) for the last 24 hours from all retailers except excluded."""
    cutoff = datetime.utcnow() - timedelta(hours=_MARKET_WINDOW_HOURS)
    result = (
        db.session.query(func.avg(PriceHistory.price_usd))
        .filter(
            PriceHistory.product_id == product_id,
            PriceHistory.retailer_id != exclude_retailer_id,
            PriceHistory.price_usd.isnot(None),
            PriceHistory.scraped_at >= cutoff,
        )
        .scalar()
    )
    return float(result) if result is not None else None


def _pct_diff(market_price: float, rcj_price: float) -> float:
    if rcj_price == 0:
        return 0.0
    return (market_price - rcj_price) / rcj_price * 100


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def _build_report() -> dict:
    """
    Build the report data structure.

    Returns
    -------
    dict with keys:
      date        : str
      rows        : list of row dicts
      flagged     : int (count of flagged products)
      total       : int (total products in report)
    """
    rcj = _get_rcj_retailer()
    if rcj is None:
        logger.warning("email_service: RareCardsJapan retailer not found in DB; aborting report")
        return {"date": datetime.utcnow().strftime("%Y-%m-%d"), "rows": [], "flagged": 0, "total": 0}

    products_with_rcj: List[Product] = (
        db.session.query(Product)
        .join(PriceHistory, PriceHistory.product_id == Product.id)
        .filter(PriceHistory.retailer_id == rcj.id)
        .distinct()
        .all()
    )

    rows = []
    for product in products_with_rcj:
        rcj_entry = _latest_rcj_price(product.id, rcj.id)
        if rcj_entry is None or rcj_entry.price_usd is None:
            continue

        rcj_price = float(rcj_entry.price_usd)
        rcj_native = float(rcj_entry.price)
        rcj_currency = rcj_entry.currency or "USD"

        cheapest = _cheapest_competitor(product.id, rcj.id)
        avg_market = _avg_market_price(product.id, rcj.id)

        cheap_diff = _pct_diff(cheapest, rcj_price) if cheapest is not None else None
        avg_diff = _pct_diff(avg_market, rcj_price) if avg_market is not None else None

        flagged = (
            (cheap_diff is not None and abs(cheap_diff) >= _THRESHOLD_PCT)
            or (avg_diff is not None and abs(avg_diff) >= _THRESHOLD_PCT)
        )

        rows.append({
            "product": product.display_name if hasattr(product, "display_name") else f"{product.set_code} {product.product_type}",
            "rcj_price_usd": rcj_price,
            "rcj_native": rcj_native,
            "rcj_currency": rcj_currency,
            "cheapest": cheapest,
            "cheap_diff": cheap_diff,
            "avg_market": avg_market,
            "avg_diff": avg_diff,
            "flagged": flagged,
        })

    # Sort: flagged first, then alphabetically
    rows.sort(key=lambda r: (not r["flagged"], r["product"]))

    flagged_count = sum(1 for r in rows if r["flagged"])
    return {
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "rows": rows,
        "flagged": flagged_count,
        "total": len(rows),
    }


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def _fmt_usd(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"${value:,.2f}"


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"


def _build_html(report: dict) -> str:
    date = report["date"]
    flagged = report["flagged"]
    total = report["total"]
    within = total - flagged

    rows_html = ""
    for row in report["rows"]:
        bg = "#fde8e8" if row["flagged"] else "#e8fde8"
        status = "⚠️ Flagged" if row["flagged"] else "✓ OK"

        cheap_diff_str = _fmt_pct(row["cheap_diff"])
        avg_diff_str = _fmt_pct(row["avg_diff"])

        rows_html += f"""
        <tr style="background:{bg};">
          <td style="padding:8px;border:1px solid #ddd;">{row['product']}</td>
          <td style="padding:8px;border:1px solid #ddd;text-align:right;">
            {_fmt_usd(row['rcj_price_usd'])}
            <br><small style="color:#666;">({row['rcj_currency']} {row['rcj_native']:.2f})</small>
          </td>
          <td style="padding:8px;border:1px solid #ddd;text-align:right;">{_fmt_usd(row['cheapest'])}</td>
          <td style="padding:8px;border:1px solid #ddd;text-align:right;{'color:#c00;font-weight:bold;' if row['cheap_diff'] is not None and abs(row['cheap_diff']) >= _THRESHOLD_PCT else ''}">{cheap_diff_str}</td>
          <td style="padding:8px;border:1px solid #ddd;text-align:right;">{_fmt_usd(row['avg_market'])}</td>
          <td style="padding:8px;border:1px solid #ddd;text-align:right;{'color:#c00;font-weight:bold;' if row['avg_diff'] is not None and abs(row['avg_diff']) >= _THRESHOLD_PCT else ''}">{avg_diff_str}</td>
          <td style="padding:8px;border:1px solid #ddd;text-align:center;">{status}</td>
        </tr>"""

    if not rows_html:
        rows_html = '<tr><td colspan="7" style="padding:16px;text-align:center;color:#666;">No data available</td></tr>'

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;color:#222;max-width:900px;margin:auto;padding:24px;">
  <h2 style="color:#333;">OPTCG Daily Price Report — {date}</h2>
  <p style="background:#f5f5f5;padding:12px;border-radius:4px;">
    <strong>{within}</strong> products within 5% &nbsp;|&nbsp;
    <strong style="color:#c00;">{flagged}</strong> products flagged (&gt;±5%)
    &nbsp;|&nbsp; {total} total
  </p>
  <table style="border-collapse:collapse;width:100%;font-size:14px;">
    <thead>
      <tr style="background:#333;color:#fff;">
        <th style="padding:10px;border:1px solid #555;text-align:left;">Product</th>
        <th style="padding:10px;border:1px solid #555;">RCJ Price (USD)</th>
        <th style="padding:10px;border:1px solid #555;">Cheapest Competitor</th>
        <th style="padding:10px;border:1px solid #555;">% Diff</th>
        <th style="padding:10px;border:1px solid #555;">Avg Market (24h)</th>
        <th style="padding:10px;border:1px solid #555;">% Diff</th>
        <th style="padding:10px;border:1px solid #555;">Status</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
  <p style="margin-top:20px;color:#666;font-size:12px;">
    All prices in USD. Non-USD retailer prices converted at current exchange rates.
    Market average uses prices recorded in the last 24 hours.
  </p>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Email sender
# ---------------------------------------------------------------------------

_RESEND_API_URL = "https://api.resend.com/emails"


def send_report() -> None:
    """Build and send the daily price comparison report via Resend."""
    api_key = current_app.config.get("RESEND_API_KEY")
    company_email = current_app.config.get("COMPANY_EMAIL")

    if not all([api_key, company_email]):
        logger.warning(
            "email_service: RESEND_API_KEY / COMPANY_EMAIL not configured; "
            "skipping daily email"
        )
        return

    report = _build_report()
    html_body = _build_html(report)

    date_str = report["date"]
    flagged = report["flagged"]
    subject = f"[OPTCG Price Report] {date_str} — {flagged} product{'s' if flagged != 1 else ''} flagged"

    try:
        response = requests.post(
            _RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": f"OPTCG Tracker <{company_email}>",
                "to": [company_email],
                "subject": subject,
                "html": html_body,
            },
            timeout=15,
        )
        response.raise_for_status()
        logger.info("email_service: daily report sent to %s (%d flagged)", company_email, flagged)
    except Exception as exc:
        logger.error("email_service: failed to send report: %s", exc, exc_info=True)
        raise
