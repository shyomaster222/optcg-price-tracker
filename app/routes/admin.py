"""
app/routes/admin.py

Admin / internal routes, including the scraper-health dashboard.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template

from app.models.price import PriceHistory
from app.models.retailer import Retailer
from app.scrapers.scraper_manager import ScraperManager

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/health")
def health_dashboard():
    manager = ScraperManager()
    statuses = manager.get_all_statuses()

    since = datetime.utcnow() - timedelta(hours=24)
    for name, status in statuses.items():
        retailer = Retailer.query.filter_by(name=name).first()
        if retailer:
            status["prices_last_24h"] = (
                PriceHistory.query
                .filter(
                    PriceHistory.retailer_id == retailer.id,
                    PriceHistory.scraped_at >= since,
                )
                .count()
            )
        else:
            status["prices_last_24h"] = 0

    return render_template("admin/health.html", statuses=statuses)


@admin_bp.route("/health/json")
def health_json():
    manager = ScraperManager()
    statuses = manager.get_all_statuses()

    since = datetime.utcnow() - timedelta(hours=24)
    for name, status in statuses.items():
        retailer = Retailer.query.filter_by(name=name).first()
        if retailer:
            status["prices_last_24h"] = (
                PriceHistory.query
                .filter(
                    PriceHistory.retailer_id == retailer.id,
                    PriceHistory.scraped_at >= since,
                )
                .count()
            )
        else:
            status["prices_last_24h"] = 0

        for key in ("last_run", "last_success", "last_failure"):
            val = status.get(key)
            if isinstance(val, datetime):
                status[key] = val.isoformat()

    return jsonify(statuses)


@admin_bp.route("/ping")
def ping():
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()})


@admin_bp.route("/send-report", methods=["POST"])
def trigger_report():
    import requests as http_requests
    from app.services.email_service import _build_report
    api_key = __import__('flask').current_app.config.get("RESEND_API_KEY")
    company_email = __import__('flask').current_app.config.get("COMPANY_EMAIL")
    report = _build_report()
    from app.services.email_service import _build_html
    html_body = _build_html(report)
    flagged = report["flagged"]
    date_str = report["date"]
    subject = f"[OPTCG Price Report] {date_str} — {flagged} product{'s' if flagged != 1 else ''} flagged"
    resp = http_requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"from": f"OPTCG Tracker <{company_email}>", "to": [company_email], "subject": subject, "html": html_body},
        timeout=15,
    )
    return jsonify({
        "status": "ok",
        "report_rows": report["total"],
        "flagged": flagged,
        "fuji_rows": len(report.get("fuji_rows", [])),
        "fuji_flagged": report.get("fuji_flagged", 0),
        "to": company_email,
        "subject": subject,
        "resend_status": resp.status_code,
        "resend_body": resp.json(),
    })


@admin_bp.route("/run-scraper", methods=["POST"])
def trigger_scraper():
    from app.scrapers.scraper_manager import ScraperManager
    results = ScraperManager().run_all()
    summary = {name: len(data) for name, data in results.items()}
    return jsonify({"status": "ok", "results": summary})


@admin_bp.route("/debug-fuji")
def debug_fuji():
    from app.scrapers.fujicardshop_scraper import FujiCardShopScraper
    from bs4 import BeautifulSoup
    scraper = FujiCardShopScraper()
    url = "https://www.fujicardshop.com/product-category/one-piece/?currency=USD"
    try:
        resp = scraper.fetch(url)
        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.select(".product, .type-product, li.product")
        titles = []
        for item in items[:5]:
            t = item.select_one(".woocommerce-loop-product__title, .product_title, h2, h3")
            p = item.select_one(".price .woocommerce-Price-amount bdi") or item.select_one(".woocommerce-Price-amount")
            titles.append({
                "title": t.get_text(strip=True) if t else None,
                "price_text": p.get_text(strip=True) if p else None,
            })
        return jsonify({
            "status_code": resp.status_code,
            "content_type": resp.headers.get("Content-Type"),
            "content_encoding": resp.headers.get("Content-Encoding"),
            "request_accept_encoding": scraper._get_headers().get("Accept-Encoding"),
            "html_length": len(resp.text),
            "product_elements_found": len(items),
            "first_5": titles,
            "raw_snippet": resp.text[:500],
        })
    except Exception as exc:
        return jsonify({"error": str(exc), "type": type(exc).__name__})


@admin_bp.route("/debug-rcj")
def debug_rcj():
    from app.scrapers.rarecardsjapan_scraper import RareCardsJapanScraper
    scraper = RareCardsJapanScraper()
    url = "https://www.rarecardsjapan.com/collections/booster-boxes/products.json?limit=250"
    try:
        resp = scraper.fetch(url)
        raw = resp.text[:300]
        try:
            data = resp.json()
            products = data.get("products", [])
            return jsonify({
                "url": url,
                "status_code": resp.status_code,
                "product_count": len(products),
                "titles": [p.get("title") for p in products[:5]],
            })
        except Exception as json_exc:
            return jsonify({
                "url": url,
                "status_code": resp.status_code,
                "json_error": str(json_exc),
                "raw_response": raw,
            })
    except Exception as exc:
        return jsonify({"url": url, "error": str(exc), "type": type(exc).__name__})


@admin_bp.route("/seed-missing-products", methods=["POST"])
def seed_missing_products():
    from app.models.product import Product
    from app.extensions import db as _db
    from datetime import date
    missing = [
        {"set_code": "OP-13", "set_name": "CARRYING ON HIS WILL", "set_name_jp": "受け継ぐ意志", "release_date": date(2025, 11, 7), "msrp_jpy": 6600},
        {"set_code": "OP-14", "set_name": "THE AZURE SEA'S SEVEN", "set_name_jp": "七海の覇王", "release_date": date(2026, 2, 6), "msrp_jpy": 6600},
        {"set_code": "OP-15", "set_name": "ADVENTURE ON KAMI'S ISLAND", "set_name_jp": "神の島の冒険", "release_date": date(2026, 5, 30), "msrp_jpy": 6600},
        {"set_code": "EB-04", "set_name": "EGGHEAD CRISIS", "set_name_jp": "エッグヘッド危機", "release_date": date(2025, 9, 27), "msrp_jpy": 6600},
        {"set_code": "PRB-01", "set_name": "THE BEST", "set_name_jp": "THE BEST", "release_date": date(2024, 5, 25), "msrp_jpy": 8800},
        {"set_code": "PRB-02", "set_name": "THE BEST VOL.2", "set_name_jp": "THE BEST vol.2", "release_date": date(2025, 7, 19), "msrp_jpy": 8800},
    ]
    added = []
    for s in missing:
        for product_type in ("box", "case"):
            if not Product.query.filter_by(set_code=s["set_code"], product_type=product_type).first():
                _db.session.add(Product(**s, product_type=product_type))
                added.append(f"{s['set_code']} {product_type}")
    _db.session.commit()
    return jsonify({"added": added, "total_products": Product.query.count()})


@admin_bp.route("/seed-fuji", methods=["POST"])
def seed_fuji():
    existing = Retailer.query.filter_by(slug="fujicardshop").first()
    if existing:
        return jsonify({"status": "already_exists", "id": existing.id})
    from app.extensions import db as _db
    retailer = Retailer(
        name="FujiCardShop",
        slug="fujicardshop",
        base_url="https://www.fujicardshop.com",
        country="US",
        currency="USD",
        min_delay_seconds=2,
        max_delay_seconds=4,
        requests_per_minute=10,
        is_active=True,
    )
    _db.session.add(retailer)
    _db.session.commit()
    return jsonify({"status": "created", "id": retailer.id, "name": retailer.name})


@admin_bp.route("/seed-rcj", methods=["POST"])
def seed_rcj():
    existing = Retailer.query.filter_by(slug="rarecardsjapan").first()
    if existing:
        return jsonify({"status": "already_exists", "id": existing.id})
    from app.extensions import db as _db
    retailer = Retailer(
        name="Rare Cards Japan",
        slug="rarecardsjapan",
        base_url="https://www.rarecardsjapan.com",
        country="GB",
        currency="USD",
        min_delay_seconds=2,
        max_delay_seconds=4,
        requests_per_minute=10,
        is_active=True,
    )
    _db.session.add(retailer)
    _db.session.commit()
    return jsonify({"status": "created", "id": retailer.id, "name": retailer.name})


@admin_bp.route("/debug-fuji-rows")
def debug_fuji_rows():
    from app.models.product import Product
    from app.services.email_service import _build_fuji_rows, _latest_retailer_price
    rcj = Retailer.query.filter_by(slug="rarecardsjapan").first()
    fuji = Retailer.query.filter_by(slug="fujicardshop").first()
    if not rcj or not fuji:
        return jsonify({"error": "retailer not found"})
    # Check each product manually
    products = Product.query.order_by(Product.set_code, Product.product_type).all()
    result = []
    for p in products:
        rcj_entry = _latest_retailer_price(p.id, rcj.id)
        fuji_entry = _latest_retailer_price(p.id, fuji.id)
        result.append({
            "set_code": p.set_code,
            "product_type": p.product_type,
            "rcj_price": float(rcj_entry.price) if rcj_entry else None,
            "rcj_price_usd": float(rcj_entry.price_usd) if rcj_entry and rcj_entry.price_usd else None,
            "fuji_price": float(fuji_entry.price) if fuji_entry else None,
            "fuji_price_usd": float(fuji_entry.price_usd) if fuji_entry and fuji_entry.price_usd else None,
        })
    return jsonify({
        "fuji_rows_count": len(_build_fuji_rows(rcj.id)),
        "products": result
    })


@admin_bp.route("/debug-fuji-coverage")
def debug_fuji_coverage():
    from app.models.product import Product
    fuji = Retailer.query.filter_by(slug="fujicardshop").first()
    rcj = Retailer.query.filter_by(slug="rarecardsjapan").first()
    if not fuji or not rcj:
        return jsonify({"error": "retailer not found"})
    fuji_product_ids = {
        r[0] for r in
        PriceHistory.query.filter_by(retailer_id=fuji.id)
        .with_entities(PriceHistory.product_id).distinct().all()
    }
    rcj_product_ids = {
        r[0] for r in
        PriceHistory.query.filter_by(retailer_id=rcj.id)
        .with_entities(PriceHistory.product_id).distinct().all()
    }
    products = Product.query.order_by(Product.set_code, Product.product_type).all()
    coverage = [
        {
            "set_code": p.set_code,
            "product_type": p.product_type,
            "has_fuji": p.id in fuji_product_ids,
            "has_rcj": p.id in rcj_product_ids,
        }
        for p in products
    ]
    missing_fuji = [c for c in coverage if not c["has_fuji"]]
    return jsonify({
        "total_products": len(products),
        "with_fuji_price": len(fuji_product_ids),
        "with_rcj_price": len(rcj_product_ids),
        "in_both": len(fuji_product_ids & rcj_product_ids),
        "missing_fuji": missing_fuji,
    })


@admin_bp.route("/debug-op05")
def debug_op05():
    from app.models.product import Product
    product = Product.query.filter_by(set_code="OP-05", product_type="box").first()
    if not product:
        return jsonify({"error": "OP-05 box not found"})
    rows = (
        PriceHistory.query
        .filter_by(product_id=product.id)
        .order_by(PriceHistory.scraped_at.desc())
        .all()
    )
    rcj = Retailer.query.filter_by(slug="rarecardsjapan").first()
    return jsonify({
        "product_id": product.id,
        "total_price_rows": len(rows),
        "prices": [
            {
                "retailer_id": r.retailer_id,
                "retailer": Retailer.query.get(r.retailer_id).name if Retailer.query.get(r.retailer_id) else "?",
                "price": float(r.price) if r.price else None,
                "price_usd": float(r.price_usd) if r.price_usd else None,
                "currency": r.currency,
                "scraped_at": r.scraped_at.isoformat(),
            }
            for r in rows
        ],
        "rcj_retailer_id": rcj.id if rcj else None,
    })


@admin_bp.route("/debug-db")
def debug_db():
    from app.models.product import Product
    from sqlalchemy import distinct
    retailers = Retailer.query.all()
    retailer_info = [{"id": r.id, "name": r.name, "slug": r.slug} for r in retailers]
    rcj = Retailer.query.filter_by(slug="rarecardsjapan").first()
    rcj_price_count = (
        PriceHistory.query.filter_by(retailer_id=rcj.id).count() if rcj else 0
    )
    all_products = Product.query.order_by(Product.set_code, Product.product_type).all()
    # Which products have RCJ prices?
    rcj_product_ids = set()
    if rcj:
        rows = PriceHistory.query.filter_by(retailer_id=rcj.id).with_entities(PriceHistory.product_id).distinct().all()
        rcj_product_ids = {r[0] for r in rows}
    product_coverage = [
        {
            "set_code": p.set_code,
            "product_type": p.product_type,
            "has_rcj_price": p.id in rcj_product_ids,
        }
        for p in all_products
    ]
    missing = [p for p in product_coverage if not p["has_rcj_price"]]
    return jsonify({
        "retailers": len(retailer_info),
        "total_products": len(all_products),
        "rcj_price_rows": rcj_price_count,
        "products_with_rcj_price": len(rcj_product_ids),
        "missing_rcj_price": missing,
    })
