"""Unit coverage for weekly reporting windows and deterministic metrics."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.reporting.metrics import (
    _countries,
    _stock,
    acquisition_source,
    sales_channel,
    summarize_shopify,
)
from app.reporting.periods import build_report_window


def _money(amount: str | int | float, currency: str = "USD") -> dict:
    return {
        "shopMoney": {
            "amount": str(amount),
            "currencyCode": currency,
        }
    }


def _order(
    processed_at: str,
    *,
    order_id: str = "gid://shopify/Order/1",
    net: str | int | float = 100,
    refund: str | int | float = 0,
    test: bool = False,
    cancelled: bool = False,
    source: str = "web",
    app_name: str = "Online Store",
    tags: tuple[str, ...] = (),
    shipping_country: str | None = "US",
    billing_country: str | None = None,
    lines: list[dict] | None = None,
    journey: dict | None = None,
) -> dict:
    order = {
        "id": order_id,
        "processedAt": processed_at,
        "test": test,
        "cancelledAt": "2026-08-03T00:00:00Z" if cancelled else None,
        "tags": list(tags),
        "sourceName": source,
        "app": {"name": app_name},
        "netPaymentSet": _money(net),
        "totalRefundedSet": _money(refund),
        "shippingAddress": (
            {"countryCodeV2": shipping_country} if shipping_country else None
        ),
        "billingAddress": (
            {"countryCodeV2": billing_country} if billing_country else None
        ),
        "lineItems": {"nodes": list(lines or [])},
    }
    if journey is not None:
        order["customerJourneySummary"] = journey
    return order


def _line(variant_id: str, quantity: int) -> dict:
    return {
        "id": f"line-{variant_id}",
        "title": variant_id,
        "currentQuantity": quantity,
        "variant": {"id": variant_id, "sku": variant_id},
        "product": {"title": variant_id, "handle": variant_id.lower()},
        "priceAfterAllDiscountsBeforeTaxesSet": _money(quantity),
    }


def _catalog_variant(
    variant_id: str,
    inventory: int | None,
    *,
    inventory_policy: str = "DENY",
) -> dict:
    return {
        "id": variant_id,
        "sku": variant_id,
        "title": "Default",
        "price": "10.00",
        "inventoryQuantity": inventory,
        "sellableOnlineQuantity": inventory,
        "inventoryPolicy": inventory_policy,
        "availableForSale": inventory is None or inventory > 0,
    }


def test_default_report_date_changes_after_hong_kong_friday_is_complete():
    before = build_report_window(
        now=datetime(2026, 7, 24, 15, 59, 59, tzinfo=timezone.utc)
    )
    at_boundary = build_report_window(
        now=datetime(2026, 7, 24, 16, 0, 0, tzinfo=timezone.utc)
    )

    assert before.report_date.isoformat() == "2026-07-17"
    assert at_boundary.report_date.isoformat() == "2026-07-24"
    assert at_boundary.current_start.isoformat() == "2026-07-18T00:00:00+08:00"
    assert at_boundary.current_end.isoformat() == "2026-07-25T00:00:00+08:00"


def test_report_window_clamps_prior_month_match_to_shorter_month():
    window = build_report_window("2023-03-31")

    assert window.month_start.isoformat() == "2023-03-01T00:00:00+08:00"
    assert window.month_end.isoformat() == "2023-04-01T00:00:00+08:00"
    assert window.prior_month_matched_start.isoformat() == (
        "2023-02-01T00:00:00+08:00"
    )
    assert window.prior_month_matched_end.isoformat() == (
        "2023-03-01T00:00:00+08:00"
    )


def test_explicit_non_friday_report_date_is_rejected():
    with pytest.raises(ValueError, match="must be a Friday"):
        build_report_window("2026-08-06")


def test_week_ending_friday_includes_orders_processed_on_friday():
    window = build_report_window("2026-07-24")
    order = _order(
        "2026-07-24T14:26:59+08:00",
        order_id="friday-hawaii-op14",
        net=1121,
        lines=[_line("op14case", 1)],
    )

    result = summarize_shopify([order], [], window)

    assert window.current_start.isoformat() == "2026-07-18T00:00:00+08:00"
    assert window.current_end.isoformat() == "2026-07-25T00:00:00+08:00"
    assert result["weekly"]["current"]["orders"] == 1
    assert result["weekly"]["current"]["net_sales"] == 1121.0
    assert result["products"]["items"][0]["sku"] == "op14case"


def test_weekly_metrics_apply_half_open_boundaries_and_order_exclusions():
    window = build_report_window("2026-08-07")
    orders = [
        _order(
            "2026-08-01T00:00:00+08:00",
            order_id="start",
            net=80,
            refund=20,
            lines=[_line("start-item", 2)],
        ),
        _order(
            "2026-08-02T12:00:00+08:00",
            order_id="paid",
            net=20,
            lines=[_line("paid-item", 1)],
        ),
        _order(
            "2026-08-03T12:00:00+08:00",
            order_id="fully-refunded",
            net=0,
            refund=50,
            lines=[_line("refunded-item", 9)],
        ),
        _order(
            "2026-08-04T12:00:00+08:00",
            order_id="cancelled",
            net=100,
            refund=5,
            cancelled=True,
            lines=[_line("cancelled-item", 3)],
        ),
        _order(
            "2026-08-05T12:00:00+08:00",
            order_id="test",
            net=500,
            refund=25,
            test=True,
            lines=[_line("test-item", 5)],
        ),
        _order(
            "2026-08-08T00:00:00+08:00",
            order_id="at-exclusive-end",
            net=400,
            lines=[_line("end-item", 4)],
        ),
        _order(
            "2026-07-30T12:00:00+08:00",
            order_id="previous",
            net=40,
            lines=[_line("previous-item", 1)],
        ),
    ]

    result = summarize_shopify(orders, [], window)
    current = result["weekly"]["current"]

    assert current["net_sales"] == 100.0
    assert current["orders"] == 2
    assert current["aov"] == 50.0
    assert current["units"] == 3
    assert current["refunds"] == 75.0
    assert current["refund_orders"] == 3
    assert current["cancelled_orders"] == 1
    assert current["comparison"]["net_sales"] == {
        "previous": 40.0,
        "absolute": 60.0,
        "percent": 1.5,
    }
    assert result["data_quality"]["current_period_records"] == 4


@pytest.mark.parametrize(
    ("order", "expected"),
    [
        (
            {"tags": [" WHOLESALE "], "sourceName": "shopify_draft_order"},
            "B2B / Wholesale",
        ),
        (
            {
                "tags": [],
                "sourceName": "web",
                "app": {"name": "Draft Orders"},
            },
            "Draft / Manual",
        ),
        (
            {"tags": [], "sourceName": "draft-order", "app": {"name": "Shop"}},
            "Draft / Manual",
        ),
        (
            {"tags": [], "sourceName": "web", "app": {"name": "Online Store"}},
            "Online Store",
        ),
        (
            {"tags": [], "sourceName": "3890849", "app": {"name": "Other"}},
            "Shop",
        ),
    ],
)
def test_sales_channel_precedence(order, expected):
    assert sales_channel(order, {"b2b", "wholesale"}) == expected


def test_first_touch_blog_order_contributes_to_acquisition_and_landing_metrics():
    first_visit = {
        "landingPage": (
            "https://rarecardsjapan.com/blogs/news/restock"
            "?utm_source=google&utm_medium=organic"
        ),
        "referrerUrl": "https://www.google.com/search?q=one+piece",
        "source": "Google",
        "sourceType": "seo",
        "utmParameters": {"source": "google", "medium": "organic"},
    }
    journey = {
        "ready": True,
        "firstVisit": first_visit,
        # Later-touch evidence must not replace the Shopify first-touch signal.
        "lastVisit": {
            "landingPage": "https://rarecardsjapan.com/?utm_source=newsletter",
            "sourceType": "email",
        },
    }
    order = _order(
        "2026-08-02T12:00:00+08:00",
        net=120,
        journey=journey,
    )

    assert acquisition_source(order) == "Organic Search"

    result = summarize_shopify([order], [], build_report_window("2026-08-07"))
    acquisition = {row["label"]: row for row in result["acquisition"]["items"]}
    landing_types = {
        row["label"]: row for row in result["landing_pages"]["types"]
    }

    assert acquisition["Organic Search"]["net_sales"] == 120.0
    assert landing_types["Blog"]["net_sales"] == 120.0
    assert result["landing_pages"]["top_pages"][0]["label"] == (
        "/blogs/news/restock"
    )
    assert result["acquisition"]["order_coverage"] == 1.0


def test_countries_prefer_shipping_then_billing_and_roll_tail_into_other():
    orders = [
        _order("2026-08-01T00:00:00Z", net=70, shipping_country="US"),
        _order(
            "2026-08-01T00:00:00Z",
            net=60,
            shipping_country=None,
            billing_country="JP",
        ),
        _order("2026-08-01T00:00:00Z", net=50, shipping_country="GB"),
        _order("2026-08-01T00:00:00Z", net=40, shipping_country="CA"),
        _order("2026-08-01T00:00:00Z", net=30, shipping_country="AU"),
        _order("2026-08-01T00:00:00Z", net=20, shipping_country="FR"),
        _order(
            "2026-08-01T00:00:00Z",
            net=10,
            shipping_country=None,
            billing_country=None,
        ),
    ]

    rows = _countries(orders)["items"]

    assert [row["label"] for row in rows] == [
        "US",
        "JP",
        "GB",
        "CA",
        "AU",
        "Other",
    ]
    assert rows[-1]["orders"] == 2
    assert rows[-1]["net_sales"] == 30.0
    assert rows[-1]["aov"] == 15.0
    assert rows[-1]["share"] == pytest.approx(30 / 280)


def test_stock_actions_enforce_velocity_and_cover_thresholds():
    quantities = {
        "stockout": 1,
        "reorder": 8,
        "promote": 1,
        "healthy": 4,
        "cover-two": 2,
        "cover-twelve": 1,
        "continue-selling": 1,
    }
    sale = _order(
        "2026-08-01T00:00:00+08:00",
        net=1,
        lines=[_line(variant_id, quantity) for variant_id, quantity in quantities.items()],
    )
    catalog = [
        {
            "id": "product",
            "title": "Stock thresholds",
            "status": "ACTIVE",
            "variants": {
                "nodes": [
                    _catalog_variant("stockout", 0),
                    _catalog_variant("reorder", 3),
                    _catalog_variant("slow", 5),
                    _catalog_variant("promote", 4),
                    _catalog_variant("healthy", 8),
                    _catalog_variant("cover-two", 1),
                    _catalog_variant("cover-twelve", 3),
                    _catalog_variant(
                        "continue-selling",
                        0,
                        inventory_policy="CONTINUE",
                    ),
                    _catalog_variant("untracked", None),
                ]
            },
        }
    ]

    result = _stock([sale], [sale], catalog)
    actions = {row["variant_id"]: row for row in result["action_items"]}

    assert actions["stockout"]["action"] == "Stockout"
    assert actions["reorder"]["action"] == "Reorder review"
    assert actions["reorder"]["weeks_cover"] == 1.5
    assert actions["slow"]["action"] == "Slow-stock review"
    assert actions["promote"]["action"] == "Promote"
    assert actions["promote"]["weeks_cover"] == 16.0
    assert actions["continue-selling"]["action"] == "Inventory review"
    assert actions["untracked"]["action"] == "Inventory review"

    # The thresholds are strict: exactly two or twelve weeks remains healthy.
    assert "cover-two" not in actions
    assert "cover-twelve" not in actions
    assert "healthy" not in actions
    assert result["active_skus"] == 9
    assert result["out_of_stock_skus"] == 2
