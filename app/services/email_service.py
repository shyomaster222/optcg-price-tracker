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


def _cheapest_competitor(product_id: int, exclude_retailer_id: int) -> tuple:
    """Return (min_price_usd, retailer_name) from all retailers except the excluded one."""
    effective = func.coalesce(PriceHistory.price_usd, PriceHistory.price)
    result = (
        db.session.query(effective, Retailer.name)
        .join(Retailer, PriceHistory.retailer_id == Retailer.id)
        .filter(
            PriceHistory.product_id == product_id,
            PriceHistory.retailer_id != exclude_retailer_id,
            effective.isnot(None),
        )
        .order_by(effective.asc())
        .first()
    )
    if result is None:
        return None, None
    return float(result[0]), result[1]


def _avg_market_price(product_id: int, exclude_retailer_id: int) -> Optional[float]:
    """Return AVG(price_usd or price) using the latest price per retailer."""
    effective = func.coalesce(PriceHistory.price_usd, PriceHistory.price)
    # Use latest price per retailer (subquery: max scraped_at per retailer)
    subq = (
        db.session.query(
            PriceHistory.retailer_id,
            func.max(PriceHistory.scraped_at).label("latest"),
        )
        .filter(
            PriceHistory.product_id == product_id,
            PriceHistory.retailer_id != exclude_retailer_id,
        )
        .group_by(PriceHistory.retailer_id)
        .subquery()
    )
    result = (
        db.session.query(func.avg(effective))
        .join(
            subq,
            (PriceHistory.retailer_id == subq.c.retailer_id)
            & (PriceHistory.scraped_at == subq.c.latest),
        )
        .filter(
            PriceHistory.product_id == product_id,
            PriceHistory.retailer_id != exclude_retailer_id,
            effective.isnot(None),
        )
        .scalar()
    )
    return float(result) if result is not None else None


def _pct_diff(market_price: float, rcj_price: float) -> float:
    if rcj_price == 0:
        return 0.0
    return (market_price - rcj_price) / rcj_price * 100


def _latest_retailer_price(product_id: int, retailer_id: int) -> Optional[PriceHistory]:
    return (
        PriceHistory.query
        .filter_by(product_id=product_id, retailer_id=retailer_id)
        .order_by(PriceHistory.scraped_at.desc())
        .first()
    )


def _build_fuji_rows(rcj_id: int) -> list:
    """
    Build rows comparing FujiCardShop vs RCJ for every product that has
    a price from both retailers.
    """
    fuji = Retailer.query.filter_by(slug="fujicardshop").first()
    if fuji is None:
        return []

    # Products that have a FujiCardShop price
    products_with_fuji: List[Product] = (
        db.session.query(Product)
        .join(PriceHistory, PriceHistory.product_id == Product.id)
        .filter(PriceHistory.retailer_id == fuji.id)
        .distinct()
        .all()
    )

    rows = []
    for product in products_with_fuji:
        rcj_entry = _latest_retailer_price(product.id, rcj_id)
        fuji_entry = _latest_retailer_price(product.id, fuji.id)

        if rcj_entry is None:
            continue
        if fuji_entry is None:
            continue

        rcj_price_raw = rcj_entry.price_usd if rcj_entry.price_usd is not None else rcj_entry.price
        fuji_price_raw = fuji_entry.price_usd if fuji_entry.price_usd is not None else fuji_entry.price
        if rcj_price_raw is None or fuji_price_raw is None:
            continue

        fuji_price = float(fuji_price_raw)
        rcj_price = float(rcj_price_raw)
        diff = _pct_diff(fuji_price, rcj_price)
        flagged = abs(diff) >= _THRESHOLD_PCT

        name = product.display_name if hasattr(product, "display_name") else f"{product.set_code} {product.product_type}"
        rows.append({
            "product": name,
            "rcj_price_usd": rcj_price,
            "fuji_price_usd": fuji_price,
            "diff": diff,
            "flagged": flagged,
        })

    rows.sort(key=lambda r: (not r["flagged"], r["product"]))
    return rows


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

        cheapest, cheapest_retailer = _cheapest_competitor(product.id, rcj.id)
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
            "cheapest_retailer": cheapest_retailer,
            "cheap_diff": cheap_diff,
            "avg_market": avg_market,
            "avg_diff": avg_diff,
            "flagged": flagged,
        })

    # Sort: flagged first, then alphabetically
    rows.sort(key=lambda r: (not r["flagged"], r["product"]))

    flagged_count = sum(1 for r in rows if r["flagged"])

    fuji_rows = _build_fuji_rows(rcj.id)
    fuji_flagged = sum(1 for r in fuji_rows if r["flagged"])

    return {
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "rows": rows,
        "flagged": flagged_count,
        "total": len(rows),
        "fuji_rows": fuji_rows,
        "fuji_flagged": fuji_flagged,
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

    # --- Table 1: all-competitor summary ---
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
          <td style="padding:8px;border:1px solid #ddd;text-align:right;">
            {_fmt_usd(row['cheapest'])}
            {f'<br><small style="color:#666;">{row["cheapest_retailer"]}</small>' if row.get("cheapest_retailer") else ""}
          </td>
          <td style="padding:8px;border:1px solid #ddd;text-align:right;{'color:#c00;font-weight:bold;' if row['cheap_diff'] is not None and abs(row['cheap_diff']) >= _THRESHOLD_PCT else ''}">{cheap_diff_str}</td>
          <td style="padding:8px;border:1px solid #ddd;text-align:right;">{_fmt_usd(row['avg_market'])}</td>
          <td style="padding:8px;border:1px solid #ddd;text-align:right;{'color:#c00;font-weight:bold;' if row['avg_diff'] is not None and abs(row['avg_diff']) >= _THRESHOLD_PCT else ''}">{avg_diff_str}</td>
          <td style="padding:8px;border:1px solid #ddd;text-align:center;">{status}</td>
        </tr>"""

    if not rows_html:
        rows_html = '<tr><td colspan="7" style="padding:16px;text-align:center;color:#666;">No data available</td></tr>'

    # --- Table 2: FujiCardShop vs RCJ ---
    fuji_rows = report.get("fuji_rows", [])
    fuji_flagged = report.get("fuji_flagged", 0)
    fuji_within = len(fuji_rows) - fuji_flagged

    fuji_rows_html = ""
    for row in fuji_rows:
        bg = "#fde8e8" if row["flagged"] else "#e8fde8"
        status = "⚠️ Flagged" if row["flagged"] else "✓ OK"
        diff_str = _fmt_pct(row["diff"])
        diff_style = "color:#c00;font-weight:bold;" if row["flagged"] else ""
        fuji_rows_html += f"""
        <tr style="background:{bg};">
          <td style="padding:8px;border:1px solid #ddd;">{row['product']}</td>
          <td style="padding:8px;border:1px solid #ddd;text-align:right;">{_fmt_usd(row['rcj_price_usd'])}</td>
          <td style="padding:8px;border:1px solid #ddd;text-align:right;">{_fmt_usd(row['fuji_price_usd'])}</td>
          <td style="padding:8px;border:1px solid #ddd;text-align:right;{diff_style}">{diff_str}</td>
          <td style="padding:8px;border:1px solid #ddd;text-align:center;">{status}</td>
        </tr>"""

    if not fuji_rows_html:
        fuji_rows_html = '<tr><td colspan="5" style="padding:16px;text-align:center;color:#666;">No FujiCardShop data available</td></tr>'

    fuji_summary = f"<strong>{fuji_within}</strong> within 5% &nbsp;|&nbsp; <strong style=\"color:#c00;\">{fuji_flagged}</strong> flagged &nbsp;|&nbsp; {len(fuji_rows)} total"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;color:#222;max-width:900px;margin:auto;padding:24px;">
  <h2 style="color:#333;">OPTCG Daily Price Report — {date}</h2>
  <p style="margin-top:8px;">
    <a href="https://web-production-d72a9.up.railway.app" style="color:#1a5276;font-size:14px;">
      🔗 Open Dashboard
    </a>
  </p>

  <h3 style="color:#444;margin-top:24px;">Market Overview (All Competitors vs RCJ)</h3>
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
        <th style="padding:10px;border:1px solid #555;">Avg Market</th>
        <th style="padding:10px;border:1px solid #555;">% Diff</th>
        <th style="padding:10px;border:1px solid #555;">Status</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>

  <h3 style="color:#444;margin-top:32px;">FujiCardShop vs RCJ</h3>
  <p style="background:#f5f5f5;padding:12px;border-radius:4px;">{fuji_summary}</p>
  <table style="border-collapse:collapse;width:100%;font-size:14px;">
    <thead>
      <tr style="background:#1a5276;color:#fff;">
        <th style="padding:10px;border:1px solid #555;text-align:left;">Product</th>
        <th style="padding:10px;border:1px solid #555;">RCJ Price (USD)</th>
        <th style="padding:10px;border:1px solid #555;">Fuji Price (USD)</th>
        <th style="padding:10px;border:1px solid #555;">% Diff (Fuji vs RCJ)</th>
        <th style="padding:10px;border:1px solid #555;">Status</th>
      </tr>
    </thead>
    <tbody>
      {fuji_rows_html}
    </tbody>
  </table>

  <p style="margin-top:20px;color:#666;font-size:12px;">
    All prices in USD. % Diff = (Fuji − RCJ) / RCJ × 100. Flagged when |diff| ≥ 5%.
  </p>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Email sender
# ---------------------------------------------------------------------------

_RESEND_API_URL = "https://api.resend.com/emails"


_DASHBOARD_URL = "https://web-production-d72a9.up.railway.app"


# ---- Clean transactional-email palette (slate neutrals + semantic accents) ----
_PS_INK = "#1a1d21"
_PS_MUTED = "#6b7280"
_PS_LINE = "#e5e7eb"
_PS_BG = "#f4f5f7"
_PS_HEAD = "#1f2933"
_PS_GREEN = "#157347"
_PS_AMBER = "#b45309"
_PS_RED = "#b42318"
_PS_BLUE = "#2b5c8a"


def _fmt_stock(inv) -> str:
    if inv is None:
        return f'<span style="color:{_PS_MUTED};">—</span>'
    if inv <= 0:
        return f'<span style="color:{_PS_RED};font-weight:700;">Out</span>'
    return f'<span style="color:{_PS_INK};">{inv}</span>'


def _ps_rows(results: list, action: str, applied_view: bool) -> str:
    rows = [r for r in results if r["action"] == action]
    if not rows:
        return (f'<tr><td colspan="6" style="padding:14px;text-align:center;color:{_PS_MUTED};'
                f'font-size:13px;">None</td></tr>')
    out = ""
    for i, r in enumerate(rows):
        bg = "#ffffff" if i % 2 == 0 else "#fafbfc"
        pct = (r["pct_change"] * 100) if r.get("pct_change") is not None else None
        pct_color = _PS_GREEN if (pct is not None and pct < 0) else (_PS_RED if pct is not None else _PS_MUTED)
        num = ("font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap;"
               f"padding:10px 12px;border-bottom:1px solid {_PS_LINE};font-size:14px;")
        out += f"""
        <tr style="background:{bg};">
          <td style="padding:10px 12px;border-bottom:1px solid {_PS_LINE};font-size:14px;font-weight:600;color:{_PS_INK};white-space:nowrap;">{r.get('set_code','')} <span style="color:{_PS_MUTED};font-weight:400;">{r.get('product_type','')}</span></td>
          <td style="{num}">{_fmt_stock(r.get('inventory'))}</td>
          <td style="{num}color:{_PS_MUTED};">{_fmt_usd(r.get('current_price'))}</td>
          <td style="{num}color:{_PS_MUTED};">{_fmt_usd(r.get('fuji_price'))}</td>
          <td style="{num}color:{_PS_INK};font-weight:700;">{_fmt_usd(r.get('target_price'))}</td>
          <td style="{num}color:{pct_color};font-weight:600;">{_fmt_pct(pct)}</td>
        </tr>"""
    return out


def _ps_section(title, subtitle, results, action, accent, applied_view=False) -> str:
    body = _ps_rows(results, action, applied_view)
    return f"""
      <tr><td style="padding:26px 28px 0 28px;">
        <div style="border-left:3px solid {accent};padding-left:10px;margin-bottom:12px;">
          <div style="font-size:15px;font-weight:700;color:{_PS_INK};">{title}</div>
          <div style="font-size:12px;color:{_PS_MUTED};margin-top:2px;">{subtitle}</div>
        </div>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid {_PS_LINE};border-radius:8px;overflow:hidden;">
          <thead><tr style="background:{_PS_BG};">
            <th align="left" style="padding:8px 12px;font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:{_PS_MUTED};font-weight:600;">Product</th>
            <th align="right" style="padding:8px 12px;font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:{_PS_MUTED};font-weight:600;">Stock</th>
            <th align="right" style="padding:8px 12px;font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:{_PS_MUTED};font-weight:600;">Current</th>
            <th align="right" style="padding:8px 12px;font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:{_PS_MUTED};font-weight:600;">Fuji</th>
            <th align="right" style="padding:8px 12px;font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:{_PS_MUTED};font-weight:600;">New price</th>
            <th align="right" style="padding:8px 12px;font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:{_PS_MUTED};font-weight:600;">Change</th>
          </tr></thead>
          <tbody>{body}</tbody>
        </table>
      </td></tr>"""


def _ps_stat(label, value, color) -> str:
    return f"""<td align="center" style="padding:14px 8px;border:1px solid {_PS_LINE};background:#ffffff;">
        <div style="font-size:26px;font-weight:700;color:{color};font-variant-numeric:tabular-nums;line-height:1;">{value}</div>
        <div style="font-size:11px;color:{_PS_MUTED};text-transform:uppercase;letter-spacing:.05em;margin-top:6px;">{label}</div>
      </td>"""


def _build_price_sync_html(summary: dict) -> str:
    counts = summary.get("counts", {})
    dry = summary.get("dry_run", True)
    date = datetime.utcnow().strftime("%b %-d, %Y")
    results = summary.get("results", [])

    pill_bg, pill_txt = ("#eef4fb", _PS_BLUE) if dry else ("#e7f4ec", _PS_GREEN)
    pill_label = "DRY RUN — no prices changed" if dry else "LIVE — prices updated"

    # Stale-data alarm banner
    stale_banner = ""
    if summary.get("fuji_stale"):
        age = summary.get("fuji_age_hours")
        age_txt = (f"{age/24:.0f} days old" if age and age >= 48 else (f"{age:.0f} hours old" if age else "missing"))
        stale_banner = f"""
      <tr><td style="padding:0 28px;">
        <div style="background:#fdecea;border:1px solid #f5c2c0;border-radius:8px;padding:14px 16px;">
          <div style="font-size:14px;font-weight:700;color:{_PS_RED};">⚠ Competitor price data is stale ({age_txt})</div>
          <div style="font-size:13px;color:#7a2b25;margin-top:4px;line-height:1.5;">
            {summary.get('fuji_stale_count', 0)} products were skipped because the Fuji scraper has not refreshed.
            Prices are <b>not</b> being updated. Check the scraper service before relying on this report.
          </div>
        </div>
      </td></tr>"""

    applied_title = "Applied" if not dry else "Would apply automatically"
    applied_sub = ("Prices updated on your store." if not dry
                   else "Within your 5% tolerance — these apply automatically once live.")

    review_section = _ps_section(
        "Needs your review", "Bigger moves or below your floor — apply from the review page.",
        results, "held", _PS_AMBER) if counts.get("held") else ""
    applied_section = _ps_section(
        applied_title, applied_sub, results, "auto_applied", _PS_GREEN) if counts.get("auto_applied") else ""
    errors_section = _ps_section(
        "Errors", "These did not update — worth a look.", results, "error", _PS_RED) if counts.get("error") else ""

    review_btn = f"""
      <tr><td style="padding:22px 28px 0 28px;">
        <a href="{_DASHBOARD_URL}/admin/price-review" style="display:inline-block;background:{_PS_HEAD};color:#ffffff;text-decoration:none;font-size:14px;font-weight:600;padding:11px 20px;border-radius:8px;">Review &amp; apply held changes →</a>
      </td></tr>""" if counts.get("held") else ""

    oos = summary.get("out_of_stock", 0)
    oos_note = (f' <b>{oos}</b> of these are out of stock on your store (marked <span style="color:{_PS_RED};font-weight:700;">Out</span>) — usually not worth repricing.'
                if oos else "")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:{_PS_BG};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_PS_BG};padding:24px 12px;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border:1px solid {_PS_LINE};border-radius:14px;overflow:hidden;">

        <tr><td style="background:{_PS_HEAD};padding:22px 28px;">
          <div style="font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#9aa5b1;">Rare Cards Japan</div>
          <div style="font-size:22px;font-weight:700;color:#ffffff;margin-top:3px;">Price Sync</div>
          <div style="font-size:13px;color:#cbd2d9;margin-top:2px;">{date}
            &nbsp;·&nbsp;<span style="background:{pill_bg};color:{pill_txt};font-weight:600;font-size:11px;padding:3px 8px;border-radius:20px;">{pill_label}</span>
          </div>
        </td></tr>

        {stale_banner}

        <tr><td style="padding:22px 28px 0 28px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border-spacing:8px 0;">
            <tr>
              {_ps_stat("Applied" if not dry else "Would apply", counts.get('auto_applied', 0), _PS_GREEN)}
              {_ps_stat("To review", counts.get('held', 0), _PS_AMBER)}
              {_ps_stat("Unchanged", counts.get('skipped', 0), _PS_MUTED)}
              {_ps_stat("Errors", counts.get('error', 0), _PS_RED if counts.get('error') else _PS_MUTED)}
            </tr>
          </table>
        </td></tr>

        {review_btn}
        {review_section}
        {applied_section}
        {errors_section}

        <tr><td style="padding:26px 28px 28px 28px;">
          <hr style="border:none;border-top:1px solid {_PS_LINE};margin:0 0 14px 0;">
          <div style="font-size:12px;color:{_PS_MUTED};line-height:1.6;">
            New price = Fuji price minus your undercut. Changes within tolerance apply automatically;
            bigger moves and anything below your floor wait for you. Unchanged items were already on target,
            or Fuji was out of stock.{oos_note}
          </div>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body></html>"""


def send_price_sync_report(summary: dict) -> None:
    """Send the price-sync summary + review email via Resend."""
    api_key = current_app.config.get("RESEND_API_KEY")
    company_email = current_app.config.get("COMPANY_EMAIL")
    if not all([api_key, company_email]):
        logger.warning("email_service: RESEND_API_KEY / COMPANY_EMAIL not configured; skipping price-sync email")
        return

    counts = summary.get("counts", {})
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    tag = "DRY RUN" if summary.get("dry_run", True) else "LIVE"
    if summary.get("fuji_stale"):
        subject = f"⚠ [RCJ Price Sync {tag}] {date_str} — competitor data STALE, prices not updating"
    else:
        subject = (f"[RCJ Price Sync {tag}] {date_str} — "
                   f"{counts.get('auto_applied', 0)} applied, {counts.get('held', 0)} to review")
    html_body = _build_price_sync_html(summary)
    try:
        response = requests.post(
            _RESEND_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"from": f"RCJ Price Sync <{company_email}>", "to": [company_email],
                  "subject": subject, "html": html_body},
            timeout=15,
        )
        response.raise_for_status()
        logger.info("email_service: price-sync report sent to %s", company_email)
    except Exception as exc:
        logger.error("email_service: failed to send price-sync report: %s", exc, exc_info=True)


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
