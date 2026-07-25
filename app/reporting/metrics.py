"""Deterministic sales, attribution, geography, product, and stock metrics."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterable
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from app.reporting.periods import ReportWindow


ZERO = Decimal("0")
SEARCH_HOSTS = {
    "google.com",
    "google.co.jp",
    "google.co.uk",
    "bing.com",
    "yahoo.com",
    "duckduckgo.com",
    "baidu.com",
}
AI_HOST_MARKERS = (
    "chatgpt.com",
    "openai.com",
    "perplexity.ai",
    "claude.ai",
    "gemini.google.com",
    "copilot.microsoft.com",
)
SOCIAL_HOST_MARKERS = (
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "x.com",
    "twitter.com",
    "reddit.com",
    "pinterest.com",
)
EMAIL_MARKERS = ("email", "newsletter", "klaviyo", "mailchimp", "omnisend", "sms")
PAID_MARKERS = ("cpc", "ppc", "paid", "paid_search", "paid-social", "paid_social")
SELF_REFERRAL_HOSTS = ("rarecardsjapan.com",)
COUNTRY_NAMES = {
    "AU": "Australia",
    "CA": "Canada",
    "CN": "China",
    "DE": "Germany",
    "ES": "Spain",
    "FR": "France",
    "GB": "United Kingdom",
    "HK": "Hong Kong",
    "ID": "Indonesia",
    "IT": "Italy",
    "JP": "Japan",
    "KR": "South Korea",
    "MY": "Malaysia",
    "NL": "Netherlands",
    "NZ": "New Zealand",
    "PH": "Philippines",
    "SG": "Singapore",
    "TH": "Thailand",
    "TW": "Taiwan",
    "US": "United States",
    "VN": "Vietnam",
}


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError):
        return ZERO


def _money_bag(node: dict | None) -> tuple[Decimal, str | None]:
    money = ((node or {}).get("shopMoney") or {})
    return _decimal(money.get("amount")), money.get("currencyCode")


def _iso_datetime(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _processed_at(order: dict, tz: ZoneInfo) -> datetime | None:
    value = _iso_datetime(order.get("processedAt") or order.get("createdAt"))
    return value.astimezone(tz) if value else None


def _net_payment(order: dict) -> Decimal:
    return _money_bag(order.get("netPaymentSet"))[0]


def _refund_amount(order: dict) -> Decimal:
    return _money_bag(order.get("totalRefundedSet"))[0]


def _line_nodes(order: dict) -> list[dict]:
    value = order.get("lineItems") or []
    if isinstance(value, dict):
        return list(value.get("nodes") or [])
    return list(value)


def _is_eligible(order: dict) -> bool:
    return not bool(order.get("test")) and not bool(order.get("cancelledAt"))


def _orders_in(
    orders: Iterable[dict],
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
) -> list[dict]:
    result = []
    for order in orders:
        processed = _processed_at(order, tz)
        if processed and start <= processed < end and not bool(order.get("test")):
            result.append(order)
    return result


def _units(order: dict) -> int:
    if _net_payment(order) <= ZERO:
        return 0
    total = 0
    for line in _line_nodes(order):
        quantity = line.get("currentQuantity", line.get("quantity", 0))
        try:
            total += max(int(quantity or 0), 0)
        except (TypeError, ValueError):
            continue
    return total


def _period_metrics(orders: Iterable[dict]) -> dict:
    order_list = list(orders)
    eligible = [order for order in order_list if _is_eligible(order)]
    positive = [order for order in eligible if _net_payment(order) > ZERO]
    sales = sum((_net_payment(order) for order in positive), ZERO)
    refunds = sum((_refund_amount(order) for order in order_list), ZERO)
    count = len(positive)
    return {
        "net_sales": float(sales),
        "orders": count,
        "aov": float(sales / count) if count else 0.0,
        "units": sum(_units(order) for order in positive),
        "refunds": float(refunds),
        "refund_orders": sum(1 for order in order_list if _refund_amount(order) > ZERO),
        "cancelled_orders": sum(1 for order in order_list if order.get("cancelledAt")),
    }


def percent_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / abs(previous)


def _with_comparison(current: dict, previous: dict) -> dict:
    result = dict(current)
    result["comparison"] = {
        key: {
            "previous": previous.get(key, 0),
            "absolute": current.get(key, 0) - previous.get(key, 0),
            "percent": percent_change(current.get(key, 0), previous.get(key, 0)),
        }
        for key in ("net_sales", "orders", "aov", "units", "refunds")
    }
    return result


def _average_period(periods: list[dict]) -> dict:
    if not periods:
        return _period_metrics([])
    keys = ("net_sales", "orders", "aov", "units", "refunds", "refund_orders")
    return {key: sum(float(p.get(key, 0)) for p in periods) / len(periods) for key in keys}


def _domain(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.hostname or "").lower().removeprefix("www.")


def _is_self_referral(host: str) -> bool:
    return any(
        host == domain or host.endswith(f".{domain}")
        for domain in SELF_REFERRAL_HOSTS
    )


def _first_visit(order: dict) -> dict | None:
    journey = order.get("customerJourneySummary") or {}
    if not journey.get("ready", True):
        return None
    return journey.get("firstVisit")


def _landing_url(visit: dict | None) -> str:
    return str((visit or {}).get("landingPage") or "")


def _visit_signals(visit: dict | None) -> dict:
    visit = visit or {}
    landing = _landing_url(visit)
    referrer = str(visit.get("referrerUrl") or "")
    query = parse_qs(urlparse(landing).query)
    utm = visit.get("utmParameters") or {}

    def first_query(name: str) -> str:
        values = query.get(name) or []
        return str(values[0]) if values else ""

    return {
        "source": str(utm.get("source") or visit.get("source") or first_query("utm_source")).lower(),
        "medium": str(utm.get("medium") or first_query("utm_medium")).lower(),
        "campaign": str(utm.get("campaign") or first_query("utm_campaign")).lower(),
        "source_type": str(visit.get("sourceType") or "").lower(),
        "referrer": referrer.lower(),
        "referrer_host": _domain(referrer),
        "landing": landing.lower(),
        "gclid": bool(first_query("gclid")),
        "srsltid": bool(first_query("srsltid")),
    }


def acquisition_source(order: dict) -> str:
    visit = _first_visit(order)
    if not visit:
        return "Unknown"
    signals = _visit_signals(visit)
    joined = " ".join(str(value) for value in signals.values())
    source = signals["source"]
    medium = signals["medium"]
    campaign = signals["campaign"]
    host = signals["referrer_host"]
    source_type = signals["source_type"]

    if any(marker in joined for marker in EMAIL_MARKERS):
        return "Email / SMS"
    if signals["gclid"] or (
        "google" in source and (
            any(marker in medium for marker in PAID_MARKERS)
            or "shopping" in campaign
            or "pmax" in campaign
        )
    ):
        return "Paid Google / Shopping"
    if signals["srsltid"] or ("google" in source and "merchant" in campaign):
        return "Google Product Listings"
    if any(marker in medium for marker in PAID_MARKERS) or source_type in {"ad", "retargeting"}:
        return "Other Paid"
    if any(marker in host for marker in AI_HOST_MARKERS) or any(
        marker in source for marker in ("chatgpt", "perplexity", "claude", "gemini", "copilot")
    ):
        return "AI Referral"
    if source_type == "seo" or host in SEARCH_HOSTS or any(
        marker in source for marker in ("google", "bing", "yahoo", "duckduckgo", "baidu")
    ):
        return "Organic Search"
    if any(marker in host for marker in SOCIAL_HOST_MARKERS) or source_type == "social":
        return "Organic Social"
    if any(
        "affiliate" in value
        for value in (source, medium, campaign, source_type)
    ):
        return "Affiliate"
    if _is_self_referral(host):
        return "Direct"
    if host:
        return "Other website referrals"
    if medium == "referral" or source_type == "referral":
        return "Other website referrals"
    if source in {"direct", "", "none"} and not signals["referrer"]:
        return "Direct"
    return "Unknown"


def _app_name(order: dict) -> str:
    app = order.get("app") or {}
    return str(app.get("name") or app.get("title") or "").lower()


def sales_channel(order: dict, b2b_tags: set[str]) -> str:
    tags = {str(tag).strip().lower() for tag in (order.get("tags") or [])}
    if tags & b2b_tags:
        return "B2B / Wholesale"

    source = str(order.get("sourceName") or "").lower().replace("-", "_")
    app_name = _app_name(order)
    if source in {"shopify_draft_order", "draft_order"} or "draft" in app_name:
        return "Draft / Manual"
    if source == "web" or "online store" in app_name:
        return "Online Store"
    if source in {"shop", "3890849"} or app_name == "shop":
        return "Shop"
    return "Other"


def landing_page_type(visit: dict | None) -> tuple[str, str]:
    landing = _landing_url(visit)
    if not landing:
        return "Unknown", "Unknown"
    path = urlparse(landing).path.rstrip("/") or "/"
    if path == "/":
        kind = "Homepage"
    elif path.startswith("/blogs/"):
        kind = "Blog"
    elif path.startswith("/products/"):
        kind = "Product"
    elif path.startswith("/collections/"):
        kind = "Collection"
    elif path.startswith("/pages/"):
        kind = "Information"
    elif path.startswith("/search"):
        kind = "Search"
    else:
        kind = "Other"
    return kind, path


def _aggregate_orders(orders: Iterable[dict], key_fn) -> list[dict]:
    values: dict[str, dict] = defaultdict(lambda: {"orders": 0, "net_sales": ZERO})
    for order in orders:
        if not _is_eligible(order) or _net_payment(order) <= ZERO:
            continue
        key = key_fn(order) or "Unknown"
        values[key]["orders"] += 1
        values[key]["net_sales"] += _net_payment(order)
    total = sum((row["net_sales"] for row in values.values()), ZERO)
    rows = []
    for label, values_row in values.items():
        sales = values_row["net_sales"]
        count = values_row["orders"]
        rows.append(
            {
                "label": label,
                "orders": count,
                "net_sales": float(sales),
                "share": float(sales / total) if total else 0.0,
                "aov": float(sales / count) if count else 0.0,
            }
        )
    return sorted(rows, key=lambda row: (-row["net_sales"], row["label"]))


def _countries(orders: list[dict]) -> dict:
    def country(order: dict) -> str:
        shipping = order.get("shippingAddress") or {}
        billing = order.get("billingAddress") or {}
        code = shipping.get("countryCodeV2") or billing.get("countryCodeV2")
        return COUNTRY_NAMES.get(str(code or "").upper(), code or "Unknown")

    rows = _aggregate_orders(orders, country)
    top, remainder = rows[:5], rows[5:]
    if remainder:
        top.append(
            {
                "label": "Other",
                "orders": sum(row["orders"] for row in remainder),
                "net_sales": sum(row["net_sales"] for row in remainder),
                "share": sum(row["share"] for row in remainder),
                "aov": (
                    sum(row["net_sales"] for row in remainder)
                    / max(sum(row["orders"] for row in remainder), 1)
                ),
            }
        )
    return {"items": top}


def _landing_assists(orders: list[dict]) -> dict:
    positive = [order for order in orders if _net_payment(order) > ZERO and _first_visit(order)]
    type_rows = _aggregate_orders(positive, lambda order: landing_page_type(_first_visit(order))[0])
    page_rows = _aggregate_orders(positive, lambda order: landing_page_type(_first_visit(order))[1])
    return {"types": type_rows, "top_pages": page_rows[:5]}


def _product_key(line: dict) -> str:
    variant = line.get("variant") or {}
    return str(variant.get("id") or line.get("sku") or line.get("title") or "Unknown")


def _product_sales(orders: Iterable[dict]) -> dict[str, dict]:
    values: dict[str, dict] = {}
    for order in orders:
        if not _is_eligible(order) or _net_payment(order) <= ZERO:
            continue
        for line in _line_nodes(order):
            key = _product_key(line)
            variant = line.get("variant") or {}
            product = line.get("product") or variant.get("product") or {}
            row = values.setdefault(
                key,
                {
                    "key": key,
                    "variant_id": variant.get("id"),
                    "sku": variant.get("sku") or line.get("sku"),
                    "title": product.get("title") or line.get("title") or "Unknown",
                    "variant_title": line.get("variantTitle") or variant.get("title"),
                    "handle": product.get("handle"),
                    "units": 0,
                    "line_sales": ZERO,
                },
            )
            try:
                current_quantity = max(
                    int(line.get("currentQuantity", line.get("quantity", 0)) or 0),
                    0,
                )
                row["units"] += current_quantity
            except (TypeError, ValueError):
                current_quantity = 0
            line_total, _ = _money_bag(line.get("priceAfterAllDiscountsBeforeTaxesSet"))
            unit_price, _ = _money_bag(line.get("discountedUnitPriceAfterAllDiscountsSet"))
            if line.get("priceAfterAllDiscountsBeforeTaxesSet"):
                row["line_sales"] += line_total
            elif line.get("discountedUnitPriceAfterAllDiscountsSet"):
                row["line_sales"] += unit_price * current_quantity
            else:
                row["line_sales"] += _money_bag(line.get("discountedTotalSet"))[0]
    return values


def _products(current_orders: list[dict], previous_orders: list[dict]) -> dict:
    current = _product_sales(current_orders)
    previous = _product_sales(previous_orders)
    items = []
    for key, row in current.items():
        prior = previous.get(key, {})
        item = dict(row)
        item["line_sales"] = float(item["line_sales"])
        item["previous_line_sales"] = float(prior.get("line_sales", ZERO))
        item["sales_change"] = percent_change(item["line_sales"], item["previous_line_sales"])
        item["previous_units"] = int(prior.get("units", 0))
        items.append(item)
    return {"items": sorted(items, key=lambda item: (-item["line_sales"], item["title"]))[:10]}


def _catalog_variants(catalog: Iterable[dict]) -> list[dict]:
    variants = []
    for product in catalog:
        if str(product.get("status") or "ACTIVE").upper() != "ACTIVE":
            continue
        raw_variants = product.get("variants") or []
        if isinstance(raw_variants, dict):
            raw_variants = raw_variants.get("nodes") or []
        for variant in raw_variants:
            raw_inventory = variant.get("inventoryQuantity")
            variants.append(
                {
                    "variant_id": variant.get("id"),
                    "sku": variant.get("sku"),
                    "title": product.get("title") or "Unknown",
                    "variant_title": variant.get("title"),
                    "handle": product.get("handle"),
                    "price": float(_decimal(variant.get("price"))),
                    "inventory": int(raw_inventory) if raw_inventory is not None else None,
                    "sellable_online_quantity": variant.get("sellableOnlineQuantity"),
                    "inventory_policy": variant.get("inventoryPolicy"),
                    "available": bool(variant.get("availableForSale")),
                }
            )
    return variants


def _stock(
    orders_28d: list[dict],
    orders_90d: list[dict],
    catalog: Iterable[dict],
) -> dict:
    sales_28 = _product_sales(orders_28d)
    sales_90 = _product_sales(orders_90d)
    items = []
    action_order = {
        "Restock": 0,
        "Order soon": 1,
        "Selling slowly": 2,
        "Promote": 3,
        "Check stock": 4,
        "Healthy": 5,
    }
    for variant in _catalog_variants(catalog):
        key = str(variant.get("variant_id") or variant.get("sku") or variant.get("title"))
        units_28 = int((sales_28.get(key) or {}).get("units", 0))
        units_90 = int((sales_90.get(key) or {}).get("units", 0))
        weekly_velocity = units_28 / 4.0
        inventory = variant["inventory"]
        tracked = inventory is not None and variant.get("inventory_policy") != "CONTINUE"
        weeks_cover = (
            max(inventory, 0) / weekly_velocity
            if tracked and weekly_velocity > 0
            else None
        )
        if not tracked:
            action = "Check stock"
        elif inventory <= 0 and units_90 > 0:
            action = "Restock"
        elif units_28 >= 2 and weeks_cover is not None and weeks_cover < 2:
            action = "Order soon"
        elif inventory > 0 and units_90 == 0:
            action = "Selling slowly"
        elif weeks_cover is not None and weeks_cover > 12:
            action = "Promote"
        else:
            action = "Healthy"
        items.append(
            {
                **variant,
                "units_28d": units_28,
                "units_90d": units_90,
                "weekly_velocity": weekly_velocity,
                "weeks_cover": weeks_cover,
                "action": action,
            }
        )
    items.sort(
        key=lambda row: (
            action_order[row["action"]],
            -(
                row["units_28d"]
                if row["action"] in {"Restock", "Order soon"}
                else (row["inventory"] or 0)
            ),
            row["title"],
        )
    )
    return {
        "sellable_units": sum(max(row["inventory"] or 0, 0) for row in items),
        "active_skus": len(items),
        "out_of_stock_skus": sum(
            1 for row in items if row["inventory"] is not None and row["inventory"] <= 0
        ),
        "negative_inventory_skus": sum(
            1 for row in items if row["inventory"] is not None and row["inventory"] < 0
        ),
        "action_items": [row for row in items if row["action"] != "Healthy"][:12],
    }


def summarize_shopify(
    orders: Iterable[dict],
    catalog: Iterable[dict],
    window: ReportWindow,
    *,
    b2b_tags: Iterable[str] = ("B2B", "Wholesale"),
) -> dict:
    """Produce the PII-free metric snapshot consumed by email and AI layers."""

    tz = ZoneInfo(window.timezone)
    order_list = list(orders)
    current_orders = _orders_in(order_list, window.current_start, window.current_end, tz)
    previous_orders = _orders_in(order_list, window.previous_start, window.previous_end, tz)
    current = _period_metrics(current_orders)
    previous = _period_metrics(previous_orders)

    four_weeks = []
    for index in range(4):
        end = window.current_start - timedelta(days=7 * index)
        start = end - timedelta(days=7)
        four_weeks.append(_period_metrics(_orders_in(order_list, start, end, tz)))

    trend = []
    for index in reversed(range(8)):
        end = window.current_end - timedelta(days=7 * index)
        start = end - timedelta(days=7)
        metrics = _period_metrics(_orders_in(order_list, start, end, tz))
        trend.append({"start": start.date().isoformat(), "end": end.date().isoformat(), **metrics})

    month_orders = _orders_in(order_list, window.month_start, window.month_end, tz)
    prior_matched_orders = _orders_in(
        order_list,
        window.prior_month_matched_start,
        window.prior_month_matched_end,
        tz,
    )
    last_month_orders = _orders_in(
        order_list,
        window.last_full_month_start,
        window.last_full_month_end,
        tz,
    )
    previous_full_month_orders = _orders_in(
        order_list,
        window.previous_full_month_start,
        window.previous_full_month_end,
        tz,
    )
    year_orders = _orders_in(order_list, window.year_start, window.current_end, tz)
    analysis_orders = _orders_in(
        order_list,
        window.analysis_start,
        window.current_end,
        tz,
    )

    normalized_b2b = {tag.strip().lower() for tag in b2b_tags if tag.strip()}
    channels = _aggregate_orders(
        analysis_orders,
        lambda order: sales_channel(order, normalized_b2b),
    )
    online_orders = [
        order
        for order in analysis_orders
        if _is_eligible(order)
        and sales_channel(order, normalized_b2b) == "Online Store"
        and _net_payment(order) > ZERO
    ]
    acquisition = _aggregate_orders(online_orders, acquisition_source)
    covered = [order for order in online_orders if acquisition_source(order) != "Unknown"]
    online_revenue = sum((_net_payment(order) for order in online_orders), ZERO)
    covered_revenue = sum((_net_payment(order) for order in covered), ZERO)

    orders_28d = _orders_in(order_list, window.velocity_start, window.current_end, tz)
    orders_90d = analysis_orders
    currencies = sorted(
        {
            currency
            for order in order_list
            for _, currency in [_money_bag(order.get("netPaymentSet"))]
            if currency
        }
    )

    return {
        "window": window.to_dict(),
        "currency": currencies[0] if len(currencies) == 1 else (",".join(currencies) or "USD"),
        "year_to_date": _period_metrics(year_orders),
        "analysis_window": {
            "label": "Last 90 days",
            "days": 90,
            "start": window.analysis_start.date().isoformat(),
            "end": window.report_date.isoformat(),
            "orders": _period_metrics(analysis_orders)["orders"],
        },
        "weekly": {
            "current": _with_comparison(current, previous),
            "previous": previous,
            "four_week_average": _average_period(four_weeks),
        },
        "monthly": {
            "month_to_date": _with_comparison(
                _period_metrics(month_orders),
                _period_metrics(prior_matched_orders),
            ),
            "prior_month_matched": _period_metrics(prior_matched_orders),
            "last_full_month": _with_comparison(
                _period_metrics(last_month_orders),
                _period_metrics(previous_full_month_orders),
            ),
            "previous_full_month": _period_metrics(previous_full_month_orders),
        },
        "trend": trend,
        "channels": {"items": channels},
        "acquisition": {
            "items": acquisition,
            "eligible_orders": len(online_orders),
            "covered_orders": len(covered),
            "order_coverage": len(covered) / len(online_orders) if online_orders else 0.0,
            "eligible_revenue": float(online_revenue),
            "covered_revenue": float(covered_revenue),
            "revenue_coverage": float(covered_revenue / online_revenue) if online_revenue else 0.0,
            "confidence": (
                "high"
                if online_orders and len(covered) / len(online_orders) >= 0.7
                else "low"
            ),
        },
        "landing_pages": _landing_assists(analysis_orders),
        "countries": _countries(analysis_orders),
        "products": _products(analysis_orders, []),
        "stock": _stock(orders_28d, orders_90d, catalog),
        "data_quality": {
            "orders_fetched": len(order_list),
            "current_period_records": len(current_orders),
            "analysis_period_records": len(analysis_orders),
            "shop_currencies": currencies,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "notes": [
                "Sales collected means payments for orders processed in the period.",
                "Refunds shown are linked to these orders and may have happened later.",
                "The first known visit may not tell the full story.",
            ],
        },
    }
