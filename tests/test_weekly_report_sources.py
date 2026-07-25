"""Mocked-session coverage for weekly report data sources."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
import requests

from app.reporting.sources import (
    GoogleSearchConsoleClient,
    ReportSourceError,
    ShopifyReportClient,
)


class _Response:
    def __init__(
        self,
        body: dict,
        *,
        status_code: int = 200,
        headers: dict | None = None,
    ):
        self._body = body
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


def _shopify_response(body: dict, *, version: str = "2026-07") -> _Response:
    return _Response(body, headers={"X-Shopify-API-Version": version})


def _shop_money(amount: int | str) -> dict:
    return {
        "shopMoney": {
            "amount": str(amount),
            "currencyCode": "USD",
        }
    }


def _shopify_client(session: Mock) -> ShopifyReportClient:
    return ShopifyReportClient(
        shop="example.myshopify.com",
        token="secret",
        session=session,
        max_retries=0,
        sleeper=lambda _: None,
    )


def _gsc_client(session: Mock) -> GoogleSearchConsoleClient:
    return GoogleSearchConsoleClient(
        client_id="client-id",
        client_secret="client-secret",
        refresh_token="refresh-token",
        session=session,
        max_retries=0,
        sleeper=lambda _: None,
    )


def test_shopify_client_credentials_mints_and_reuses_short_lived_token():
    session = Mock()
    now = [100.0]
    session.post.side_effect = [
        _Response(
            {
                "access_token": "runtime-token",
                "scope": "read_all_orders,read_orders,read_products",
                "expires_in": 86400,
            }
        ),
        _shopify_response({"data": {"shop": {"name": "RCJ"}}}),
        _shopify_response({"data": {"shop": {"name": "RCJ"}}}),
    ]
    client = ShopifyReportClient(
        shop="example.myshopify.com",
        client_id="report-client-id",
        client_secret="report-client-secret",
        session=session,
        max_retries=0,
        sleeper=lambda _: None,
        clock=lambda: now[0],
    )

    assert client.graphql("query { shop { name } }")["shop"]["name"] == "RCJ"
    assert client.graphql("query { shop { name } }")["shop"]["name"] == "RCJ"

    token_call, first_api_call, second_api_call = session.post.call_args_list
    assert token_call.args[0] == (
        "https://example.myshopify.com/admin/oauth/access_token"
    )
    assert token_call.kwargs["data"] == {
        "grant_type": "client_credentials",
        "client_id": "report-client-id",
        "client_secret": "report-client-secret",
    }
    assert token_call.kwargs["headers"]["Content-Type"] == (
        "application/x-www-form-urlencoded"
    )
    assert first_api_call.kwargs["headers"]["X-Shopify-Access-Token"] == (
        "runtime-token"
    )
    assert second_api_call.kwargs["headers"]["X-Shopify-Access-Token"] == (
        "runtime-token"
    )


def test_shopify_client_credentials_refreshes_before_expiry():
    session = Mock()
    now = [100.0]
    session.post.side_effect = [
        _Response({"access_token": "first-token", "expires_in": 120}),
        _shopify_response({"data": {"shop": {"name": "RCJ"}}}),
        _Response({"access_token": "second-token", "expires_in": 120}),
        _shopify_response({"data": {"shop": {"name": "RCJ"}}}),
    ]
    client = ShopifyReportClient(
        shop="example.myshopify.com",
        token="static-fallback",
        client_id="report-client-id",
        client_secret="report-client-secret",
        session=session,
        max_retries=0,
        sleeper=lambda _: None,
        clock=lambda: now[0],
    )

    client.graphql("query { shop { name } }")
    now[0] = 209.0
    client.graphql("query { shop { name } }")

    assert session.post.call_args_list[1].kwargs["headers"][
        "X-Shopify-Access-Token"
    ] == "first-token"
    assert session.post.call_args_list[3].kwargs["headers"][
        "X-Shopify-Access-Token"
    ] == "second-token"


def test_shopify_client_credentials_errors_do_not_include_secret():
    session = Mock()
    session.post.return_value = _Response(
        {"error": "invalid_client"},
        status_code=401,
    )
    client = ShopifyReportClient(
        shop="example.myshopify.com",
        client_id="report-client-id",
        client_secret="do-not-leak-this",
        session=session,
        max_retries=0,
        sleeper=lambda _: None,
    )

    with pytest.raises(ReportSourceError) as error:
        client.graphql("query { shop { name } }")

    assert "unauthorized" in str(error.value)
    assert "do-not-leak-this" not in str(error.value)


def test_shopify_client_credentials_must_be_complete():
    with pytest.raises(ValueError, match="must be provided together"):
        ShopifyReportClient(
            shop="example.myshopify.com",
            client_id="report-client-id",
        )


def test_shopify_fetch_orders_paginates_lines_and_keeps_partial_journeys():
    session = Mock()
    online_one = {
        "id": "gid://shopify/Order/1",
        "sourceName": "web",
        "app": {"name": "Online Store"},
        "cancelledAt": None,
        "netPaymentSet": _shop_money(100),
    }
    online_two = {
        "id": "gid://shopify/Order/2",
        "sourceName": "web",
        "app": {"name": "Online Store"},
        "cancelledAt": None,
        "netPaymentSet": _shop_money(50),
    }
    zero_value = {
        "id": "gid://shopify/Order/3",
        "sourceName": "shopify_draft_order",
        "app": {"name": "Draft Orders"},
        "cancelledAt": None,
        "netPaymentSet": _shop_money(0),
    }
    journey = {
        "ready": True,
        "firstVisit": {
            "landingPage": "https://example.com/blogs/news/post",
            "source": "google",
            "sourceType": "seo",
        },
    }
    session.post.side_effect = [
        _shopify_response(
            {
                "data": {
                    "orders": {
                        "nodes": [online_one],
                        "pageInfo": {
                            "hasNextPage": True,
                            "endCursor": "orders-page-2",
                        },
                    }
                }
            }
        ),
        _shopify_response(
            {
                "data": {
                    "orders": {
                        "nodes": [online_two, zero_value],
                        "pageInfo": {
                            "hasNextPage": False,
                            "endCursor": None,
                        },
                    }
                }
            }
        ),
        _shopify_response(
            {
                "data": {
                    "order": {
                        "lineItems": {
                            "nodes": [{"id": "line-1"}],
                            "pageInfo": {
                                "hasNextPage": True,
                                "endCursor": "line-page-2",
                            },
                        }
                    }
                }
            }
        ),
        _shopify_response(
            {
                "data": {
                    "order": {
                        "lineItems": {
                            "nodes": [{"id": "line-2"}],
                            "pageInfo": {
                                "hasNextPage": False,
                                "endCursor": None,
                            },
                        }
                    }
                }
            }
        ),
        _shopify_response(
            {
                "data": {
                    "order": {
                        "lineItems": {
                            "nodes": [{"id": "line-3"}],
                            "pageInfo": {
                                "hasNextPage": False,
                                "endCursor": None,
                            },
                        }
                    }
                }
            }
        ),
        _shopify_response(
            {
                "errors": [
                    {
                        "message": "One journey is still processing",
                        "extensions": {"code": "INTERNAL_SERVER_ERROR"},
                    }
                ],
                "data": {
                    "nodes": [
                        {
                            "id": "gid://shopify/Order/1",
                            "customerJourneySummary": journey,
                        }
                    ]
                },
            }
        ),
    ]
    client = _shopify_client(session)
    hkt = ZoneInfo("Asia/Hong_Kong")

    orders = client.fetch_orders(
        datetime(2026, 7, 31, tzinfo=hkt),
        datetime(2026, 8, 7, tzinfo=hkt),
    )

    assert [order["id"] for order in orders] == [
        "gid://shopify/Order/1",
        "gid://shopify/Order/2",
        "gid://shopify/Order/3",
    ]
    assert online_one["lineItems"]["nodes"] == [{"id": "line-1"}, {"id": "line-2"}]
    assert online_two["lineItems"]["nodes"] == [{"id": "line-3"}]
    assert "lineItems" not in zero_value
    assert online_one["customerJourneySummary"] == journey
    assert "customerJourneySummary" not in online_two
    assert client.warnings == ["Shopify returned partial GraphQL data"]

    payloads = [call.kwargs["json"] for call in session.post.call_args_list]
    assert payloads[0]["variables"]["after"] is None
    assert payloads[1]["variables"]["after"] == "orders-page-2"
    assert payloads[2]["variables"] == {
        "id": "gid://shopify/Order/1",
        "after": None,
    }
    assert payloads[3]["variables"] == {
        "id": "gid://shopify/Order/1",
        "after": "line-page-2",
    }
    assert payloads[-1]["variables"]["ids"] == [
        "gid://shopify/Order/1",
        "gid://shopify/Order/2",
    ]
    assert (
        "processed_at:>='2026-07-30T16:00:00Z' "
        "processed_at:<'2026-08-06T16:00:00Z' test:false"
    ) == payloads[0]["variables"]["query"]


def test_shopify_fetch_orders_rejects_partial_core_sales_page():
    session = Mock()
    session.post.return_value = _shopify_response(
        {
            "errors": [
                {
                    "message": "Order page timed out",
                    "extensions": {"code": "INTERNAL_SERVER_ERROR"},
                }
            ],
            "data": {
                "orders": {
                    "nodes": [],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            },
        }
    )
    client = _shopify_client(session)
    hkt = ZoneInfo("Asia/Hong_Kong")

    with pytest.raises(ReportSourceError, match="Order page timed out"):
        client.fetch_orders(
            datetime(2026, 7, 31, tzinfo=hkt),
            datetime(2026, 8, 7, tzinfo=hkt),
        )

    assert client.warnings == []


def test_shopify_catalog_paginates_products_and_nested_variants():
    session = Mock()
    product_one = {
        "id": "gid://shopify/Product/1",
        "title": "One",
        "variants": {
            "nodes": [{"id": "variant-1"}],
            "pageInfo": {
                "hasNextPage": True,
                "endCursor": "variant-page-2",
            },
        },
    }
    product_two = {
        "id": "gid://shopify/Product/2",
        "title": "Two",
        "variants": {
            "nodes": [{"id": "variant-3"}],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        },
    }
    session.post.side_effect = [
        _shopify_response(
            {
                "data": {
                    "products": {
                        "nodes": [product_one],
                        "pageInfo": {
                            "hasNextPage": True,
                            "endCursor": "product-page-2",
                        },
                    }
                }
            }
        ),
        _shopify_response(
            {
                "data": {
                    "product": {
                        "variants": {
                            "nodes": [{"id": "variant-2"}],
                            "pageInfo": {
                                "hasNextPage": False,
                                "endCursor": None,
                            },
                        }
                    }
                }
            }
        ),
        _shopify_response(
            {
                "data": {
                    "products": {
                        "nodes": [product_two],
                        "pageInfo": {
                            "hasNextPage": False,
                            "endCursor": None,
                        },
                    }
                }
            }
        ),
    ]
    client = _shopify_client(session)

    products = client.fetch_catalog()

    assert [product["id"] for product in products] == [
        "gid://shopify/Product/1",
        "gid://shopify/Product/2",
    ]
    assert product_one["variants"]["nodes"] == [
        {"id": "variant-1"},
        {"id": "variant-2"},
    ]
    payloads = [call.kwargs["json"] for call in session.post.call_args_list]
    assert payloads[0]["variables"] == {"after": None}
    assert payloads[1]["variables"] == {
        "id": "gid://shopify/Product/1",
        "after": "variant-page-2",
    }
    assert payloads[2]["variables"] == {"after": "product-page-2"}


def test_shopify_rejects_served_api_version_mismatch():
    session = Mock()
    session.post.return_value = _shopify_response(
        {"data": {"shop": {}}},
        version="2026-04",
    )
    client = _shopify_client(session)

    with pytest.raises(
        ReportSourceError,
        match=r"served API 2026-04, expected 2026-07",
    ):
        client.graphql("query { shop { name } }")


def test_shopify_validate_access_lists_missing_required_scopes():
    session = Mock()
    session.post.return_value = _shopify_response(
        {
            "data": {
                "shop": {
                    "myshopifyDomain": "example.myshopify.com",
                    "currencyCode": "USD",
                },
                "currentAppInstallation": {
                    "accessScopes": [{"handle": "read_orders"}]
                },
            }
        }
    )
    client = _shopify_client(session)

    with pytest.raises(
        ReportSourceError,
        match=r"missing scopes: read_all_orders, read_products",
    ):
        client.validate_access()


def test_gsc_latest_final_date_falls_back_to_max_final_row():
    session = Mock()
    session.request.side_effect = [
        _Response({"access_token": "access-token"}),
        _Response({"metadata": {}}),
        _Response(
            {
                "rows": [
                    {"keys": ["2026-07-19"]},
                    {"keys": ["2026-07-21"]},
                    {"keys": ["2026-07-20"]},
                ]
            }
        ),
    ]
    client = _gsc_client(session)

    assert client.latest_final_date(today=date(2026, 7, 25)) == date(2026, 7, 21)

    query_calls = session.request.call_args_list[1:]
    assert query_calls[0].kwargs["json"]["dataState"] == "all"
    assert query_calls[1].kwargs["json"]["dataState"] == "final"


def test_gsc_report_uses_latest_final_window_and_builds_movers_and_opportunities():
    session = Mock()
    session.request.side_effect = [
        _Response({"access_token": "access-token"}),
        _Response({"metadata": {"first_incomplete_date": "2026-07-22"}}),
        _Response(
            {
                "rows": [
                    {
                        "clicks": 100,
                        "impressions": 1000,
                        "ctr": 0.10,
                        "position": 5,
                    }
                ]
            }
        ),
        _Response(
            {
                "rows": [
                    {
                        "clicks": 80,
                        "impressions": 800,
                        "ctr": 0.10,
                        "position": 6,
                    }
                ]
            }
        ),
        _Response(
            {
                "rows": [
                    {
                        "keys": ["alpha"],
                        "clicks": 20,
                        "impressions": 200,
                        "ctr": 0.02,
                        "position": 8,
                    },
                    {
                        "keys": ["new query"],
                        "clicks": 12,
                        "impressions": 120,
                        "ctr": 0.04,
                        "position": 15,
                    },
                    {
                        "keys": ["beta"],
                        "clicks": 2,
                        "impressions": 80,
                        "ctr": 0.025,
                        "position": 20,
                    },
                ]
            }
        ),
        _Response(
            {
                "rows": [
                    {
                        "keys": ["alpha"],
                        "clicks": 5,
                        "impressions": 100,
                        "ctr": 0.01,
                        "position": 12,
                    },
                    {
                        "keys": ["beta"],
                        "clicks": 10,
                        "impressions": 100,
                        "ctr": 0.04,
                        "position": 15,
                    },
                ]
            }
        ),
        _Response(
            {
                "rows": [
                    {
                        "keys": ["https://example.com/collections/one-piece"],
                        "clicks": 40,
                        "impressions": 400,
                        "ctr": 0.10,
                        "position": 4,
                    }
                ]
            }
        ),
        _Response(
            {
                "rows": [
                    {
                        "keys": ["low ctr", "https://example.com/products/a"],
                        "clicks": 3,
                        "impressions": 300,
                        "ctr": 0.01,
                        "position": 7,
                    },
                    {
                        "keys": [
                            "near page one",
                            "https://example.com/products/b",
                        ],
                        "clicks": 4,
                        "impressions": 80,
                        "ctr": 0.05,
                        "position": 12,
                    },
                    {
                        "keys": ["too small", "https://example.com/products/c"],
                        "clicks": 1,
                        "impressions": 40,
                        "ctr": 0.025,
                        "position": 12,
                    },
                ]
            }
        ),
    ]
    client = _gsc_client(session)

    report = client.fetch_report(today=date(2026, 7, 25))

    assert report["as_of"] == "2026-07-21"
    assert report["weekly_window"] == {
        "start": "2026-07-15",
        "end": "2026-07-21",
    }
    assert report["previous_weekly_window"] == {
        "start": "2026-07-08",
        "end": "2026-07-14",
    }
    assert report["query_window"] == {
        "start": "2026-06-24",
        "end": "2026-07-21",
    }
    assert report["previous_query_window"] == {
        "start": "2026-05-27",
        "end": "2026-06-23",
    }
    assert report["current"]["clicks"] == 100.0
    assert report["comparison"]["clicks"] == {
        "absolute": 20.0,
        "percent": 0.25,
    }
    assert [row["query"] for row in report["query_movers"]] == [
        "alpha",
        "new query",
        "beta",
    ]
    assert report["query_movers"][0]["click_delta"] == 15.0
    assert report["query_movers"][0]["position_improvement"] == 4.0
    assert report["query_movers"][1]["position_improvement"] is None
    assert [
        (row["query"], row["type"]) for row in report["opportunities"]
    ] == [
        ("low ctr", "CTR gap"),
        ("near page one", "Striking distance"),
    ]
    assert report["query_rows_are_partial"] is True

    range_payloads = [
        call.kwargs["json"] for call in session.request.call_args_list[2:]
    ]
    assert (range_payloads[0]["startDate"], range_payloads[0]["endDate"]) == (
        "2026-07-15",
        "2026-07-21",
    )
    assert (range_payloads[1]["startDate"], range_payloads[1]["endDate"]) == (
        "2026-07-08",
        "2026-07-14",
    )
    assert (
        range_payloads[4]["dimensions"],
        range_payloads[4]["aggregationType"],
    ) == (["page"], "auto")
    assert (
        range_payloads[-1]["startDate"],
        range_payloads[-1]["endDate"],
        range_payloads[-1]["dimensions"],
        range_payloads[-1]["aggregationType"],
    ) == (
        "2026-06-24",
        "2026-07-21",
        ["query", "page"],
        "auto",
    )
