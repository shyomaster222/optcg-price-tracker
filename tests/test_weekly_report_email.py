"""Tests for aggregate AI commentary, charts, rendering, and Resend delivery."""

from __future__ import annotations

import base64
import json

import pytest

from app.reporting.ai import (
    NarrativeResult,
    build_ai_projection,
    generate_weekly_narrative,
)
from app.reporting.email import (
    EmailDeliveryError,
    render_weekly_email,
    send_rendered_email,
)


@pytest.fixture
def report_snapshot():
    return {
        "window": {
            "report_date": "2026-07-24",
            "timezone": "Asia/Hong_Kong",
            "current_start": "2026-07-18T00:00:00+08:00",
            "current_end": "2026-07-25T00:00:00+08:00",
        },
        "currency": "USD",
        "weekly": {
            "current": {
                "net_sales": 12_500,
                "orders": 25,
                "aov": 500,
                "units": 42,
                "refunds": 100,
                "refund_orders": 1,
                "comparison": {
                    "net_sales": {
                        "previous": 10_000,
                        "absolute": 2_500,
                        "percent": 0.25,
                    },
                    "orders": {
                        "previous": 20,
                        "absolute": 5,
                        "percent": 0.25,
                    },
                    "aov": {
                        "previous": 500,
                        "absolute": 0,
                        "percent": 0,
                    },
                    "units": {
                        "previous": 35,
                        "absolute": 7,
                        "percent": 0.2,
                    },
                },
            },
            "previous": {
                "net_sales": 10_000,
                "orders": 20,
                "aov": 500,
                "units": 35,
                "refunds": 0,
                "refund_orders": 0,
            },
            "four_week_average": {
                "net_sales": 9_750,
                "orders": 19,
                "aov": 513.16,
                "units": 33,
                "refunds": 25,
                "refund_orders": 0.25,
            },
        },
        "monthly": {
            "month_to_date": {
                "net_sales": 41_000,
                "orders": 88,
                "comparison": {
                    "net_sales": {
                        "previous": 37_000,
                        "absolute": 4_000,
                        "percent": 4_000 / 37_000,
                    }
                },
            },
            "last_full_month": {
                "net_sales": 53_000,
                "orders": 110,
                "aov": 481.82,
                "units": 175,
            },
        },
        "trend": [
            {
                "start": f"2026-0{index}-01",
                "end": f"2026-0{index}-08",
                "net_sales": index * 1_500,
                "orders": index * 3,
            }
            for index in range(1, 9)
        ],
        "channels": {
            "items": [
                {
                    "label": "Online Store",
                    "orders": 20,
                    "net_sales": 10_500,
                    "share": 0.84,
                },
                {
                    "label": "Shop",
                    "orders": 5,
                    "net_sales": 2_000,
                    "share": 0.16,
                },
            ]
        },
        "acquisition": {
            "items": [
                {
                    "label": "Organic Search",
                    "orders": 10,
                    "net_sales": 6_000,
                    "share": 0.6,
                },
                {
                    "label": "Direct",
                    "orders": 8,
                    "net_sales": 4_000,
                    "share": 0.4,
                },
            ],
            "eligible_orders": 20,
            "covered_orders": 18,
            "order_coverage": 0.9,
            "eligible_revenue": 10_500,
            "covered_revenue": 10_000,
            "revenue_coverage": 10_000 / 10_500,
            "confidence": "high",
        },
        "landing_pages": {
            "types": [
                {
                    "label": "Product",
                    "orders": 12,
                    "net_sales": 7_500,
                    "share": 0.6,
                },
                {
                    "label": "Blog",
                    "orders": 4,
                    "net_sales": 2_000,
                    "share": 0.16,
                },
            ],
            "top_pages": [
                {
                    "label": "/blogs/one-piece-card-guides",
                    "orders": 4,
                    "net_sales": 2_000,
                    "share": 0.16,
                }
            ],
        },
        "countries": {
            "items": [
                {
                    "label": "US",
                    "orders": 15,
                    "net_sales": 8_000,
                    "share": 0.64,
                },
                {
                    "label": "JP",
                    "orders": 10,
                    "net_sales": 4_500,
                    "share": 0.36,
                },
            ]
        },
        "products": {
            "items": [
                {
                    "title": "OP-01 Booster Box",
                    "variant_title": "English",
                    "sku": "OP01-BOX-EN",
                    "units": 8,
                    "line_sales": 4_800,
                    "previous_line_sales": 3_600,
                    "sales_change": 1 / 3,
                }
            ]
        },
        "stock": {
            "sellable_units": 220,
            "active_skus": 40,
            "out_of_stock_skus": 2,
            "negative_inventory_skus": 0,
            "action_items": [
                {
                    "title": "OP-05 Booster Box",
                    "variant_title": "Japanese",
                    "sku": "OP05-BOX-JP",
                    "inventory": 1,
                    "units_28d": 8,
                    "units_90d": 21,
                    "weekly_velocity": 2,
                    "weeks_cover": 0.5,
                    "action": "Reorder review",
                }
            ],
        },
        "gsc": {
            "status": "ok",
            "as_of": "2026-07-22",
            "timezone": "America/Los_Angeles",
            "weekly_window": {
                "start": "2026-07-16",
                "end": "2026-07-22",
            },
            "previous_weekly_window": {
                "start": "2026-07-09",
                "end": "2026-07-15",
            },
            "query_window": {
                "start": "2026-06-25",
                "end": "2026-07-22",
            },
            "previous_query_window": {
                "start": "2026-05-28",
                "end": "2026-06-24",
            },
            "current": {
                "clicks": 120,
                "impressions": 4_000,
                "ctr": 0.03,
                "position": 8.4,
            },
            "previous": {
                "clicks": 100,
                "impressions": 3_600,
                "ctr": 100 / 3_600,
                "position": 9.1,
            },
            "comparison": {
                "clicks": {"absolute": 20, "percent": 0.2},
                "impressions": {"absolute": 400, "percent": 400 / 3_600},
            },
            "top_queries": [
                {
                    "keys": ["one piece booster box"],
                    "clicks": 32,
                    "impressions": 700,
                    "ctr": 32 / 700,
                    "position": 4.2,
                },
                {
                    "keys": ["private-search@example.com"],
                    "clicks": 1,
                    "impressions": 2,
                }
            ],
            "query_movers": [
                {
                    "query": "rare cards japan",
                    "clicks": 24,
                    "impressions": 320,
                    "ctr": 0.075,
                    "position": 3.1,
                    "click_delta": 9,
                    "impression_delta": 80,
                    "ctr_delta_pp": 1.2,
                    "position_improvement": 0.8,
                }
            ],
            "opportunities": [
                {
                    "type": "CTR gap",
                    "query": "customer name",
                    "page": "https://example.test/private",
                    "clicks": 2,
                    "impressions": 200,
                    "ctr": 0.01,
                    "position": 11.4,
                }
            ],
            "query_rows_are_partial": True,
        },
        "data_quality": {
            "orders_fetched": 500,
            "current_period_records": 25,
            "notes": ["Acquisition is first-touch evidence, not proof of causation."],
        },
    }


class FakeResponse:
    def __init__(self, status_code, body=None, text=""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class RecordingSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_ai_projection_is_allowlisted_and_excludes_raw_or_query_data(report_snapshot):
    report_snapshot["orders"] = [
        {
            "email": "private-order@example.com",
            "shippingAddress": {"name": "A Customer"},
        }
    ]
    report_snapshot["customer_email"] = "private-customer@example.com"

    projection = build_ai_projection(report_snapshot)
    serialized = json.dumps(projection)

    assert "orders" not in projection
    assert "customer_email" not in projection
    assert "private-order@example.com" not in serialized
    assert "private-search@example.com" not in serialized
    assert "customer name" not in serialized
    assert projection["gsc"]["opportunity_count"] == 1
    assert projection["gsc"]["weekly_window"] == {
        "start": "2026-07-16",
        "end": "2026-07-22",
    }
    assert projection["gsc"]["query_window"] == {
        "start": "2026-06-25",
        "end": "2026-07-22",
    }


def test_generate_narrative_uses_responses_json_schema_and_all_output_items(
    report_snapshot,
):
    structured = {
        "headline": "Growth with stock pressure",
        "executive_summary": "Sales grew while one fast seller needs attention.",
        "highlights": ["Net collected revenue increased 25% week over week."],
        "actions": ["Review the low-cover booster box."],
        "caveats": ["First-touch attribution is directional."],
    }
    session = RecordingSession(
        FakeResponse(
            200,
            {
                "status": "completed",
                "output": [
                    {"type": "reasoning", "summary": []},
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(structured),
                            }
                        ],
                    },
                ],
            },
        )
    )

    result = generate_weekly_narrative(
        report_snapshot,
        api_key="test-openai-key",
        model="test-model",
        session=session,
    )

    assert result.generated_by_ai is True
    assert result.headline == structured["headline"]
    _, request = session.calls[0]
    assert request["json"]["model"] == "test-model"
    assert request["json"]["store"] is False
    output_format = request["json"]["text"]["format"]
    assert output_format["type"] == "json_schema"
    assert output_format["strict"] is True
    assert output_format["schema"]["additionalProperties"] is False
    assert "private-search@example.com" not in request["json"]["input"]


def test_generate_narrative_falls_back_without_hiding_provider_failure(
    report_snapshot,
):
    session = RecordingSession(
        FakeResponse(
            503,
            {"error": {"message": "service temporarily unavailable"}},
        )
    )

    result = generate_weekly_narrative(
        report_snapshot,
        api_key="test-openai-key",
        session=session,
    )

    assert result.generated_by_ai is False
    assert result.executive_summary.startswith(
        "Net collected revenue was USD 12,500.00"
    )
    assert "HTTP 503" in result.error
    assert result.actions


def test_rendered_email_has_escaped_content_plain_text_and_three_cids(
    report_snapshot,
):
    report_snapshot["products"]["items"][0]["title"] = "<script>alert(1)</script>"
    narrative = NarrativeResult(
        headline="<b>Important</b>",
        executive_summary="Verified <em>summary</em>.",
        highlights=("A <script>bad()</script> highlight.",),
        actions=("Review inventory.",),
        caveats=("Directional only.",),
        generated_by_ai=True,
        model="test-model",
    )

    rendered = render_weekly_email(
        report_snapshot,
        narrative,
        partial_sources=("Google Ads",),
    )

    assert "(partial)" in rendered.subject
    assert "<script>alert(1)</script>" not in rendered.html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered.html
    assert "<b>Important</b>" not in rendered.html
    assert "&lt;b&gt;Important&lt;/b&gt;" in rendered.html
    assert "Verified <em>summary</em>." in rendered.text
    assert "@media only screen" in rendered.html
    assert "Rare_Cards_Japan.png" in rendered.html
    assert "Sales week 18 Jul 2026–24 Jul 2026" in rendered.html
    assert "Latest 7 finalized days" in rendered.html
    assert "16 Jul 2026–22 Jul 2026" in rendered.html
    assert "not month-to-date or daily figures" in rendered.html
    assert "Latest 28 finalized days" in rendered.html
    assert "25 Jun 2026–22 Jul 2026" in rendered.html
    assert "Blog assists:" in rendered.html
    assert "/blogs/one-piece-card-guides" in rendered.html
    assert "Last full month" in rendered.html
    assert "USD 53,000" in rendered.html
    assert "Top Google keywords" in rendered.html
    assert "one piece booster box" in rendered.html
    assert "Keyword movers" in rendered.html
    assert "rare cards japan" in rendered.html
    assert "Keyword opportunities" in rendered.html
    assert "customer name" in rendered.html
    assert "private-search@example.com" not in rendered.html
    assert "https://example.test/private" not in rendered.html
    assert "TOP GOOGLE KEYWORDS" in rendered.text
    assert "latest 7 finalized days" in rendered.text
    assert "latest 28 finalized days" in rendered.text
    assert "Last full month net collected revenue: USD 53,000" in rendered.text
    assert "not refunds issued during the week" in rendered.text
    assert "https://example.test/private" not in rendered.text
    assert len(rendered.attachments) == 3
    assert len({attachment.content_id for attachment in rendered.attachments}) == 3
    for attachment in rendered.attachments:
        assert attachment.content.startswith(b"\x89PNG\r\n\x1a\n")
        assert attachment.content_type == "image/png"
        assert f"cid:{attachment.content_id}" in rendered.html


def test_resend_payload_encodes_bytes_once_and_sets_idempotency_header(
    report_snapshot,
):
    rendered = render_weekly_email(
        report_snapshot,
        generate_weekly_narrative(report_snapshot),
    )
    session = RecordingSession(FakeResponse(200, {"id": "email_123"}))

    result = send_rendered_email(
        rendered,
        api_key="resend-test-key",
        from_address="RCJ Reports <reports@example.com>",
        recipients=("owner@example.com", "ops@example.com"),
        idempotency_key="weekly-2026-07-24",
        session=session,
    )

    assert result.provider_id == "email_123"
    assert result.status_code == 200
    url, request = session.calls[0]
    assert url.endswith("/emails")
    assert request["headers"]["Idempotency-Key"] == "weekly-2026-07-24"
    assert request["headers"]["Authorization"] == "Bearer resend-test-key"
    payload = request["json"]
    assert payload["to"] == ["owner@example.com", "ops@example.com"]
    assert len(payload["attachments"]) == 3
    for original, encoded in zip(rendered.attachments, payload["attachments"]):
        assert base64.b64decode(encoded["content"]) == original.content
        assert encoded["content_id"] == original.content_id
        assert encoded["content_type"] == "image/png"


def test_resend_provider_error_is_raised_with_real_status(report_snapshot):
    rendered = render_weekly_email(
        report_snapshot,
        generate_weekly_narrative(report_snapshot),
    )
    session = RecordingSession(
        FakeResponse(
            422,
            {"name": "validation_error", "message": "invalid from address"},
        )
    )

    with pytest.raises(EmailDeliveryError, match="HTTP 422.*invalid from address") as error:
        send_rendered_email(
            rendered,
            api_key="resend-test-key",
            from_address="bad",
            recipients="owner@example.com",
            idempotency_key="weekly-2026-07-24",
            session=session,
        )

    assert error.value.status_code == 422


def test_resend_success_without_provider_id_is_not_reported_as_sent(
    report_snapshot,
):
    rendered = render_weekly_email(
        report_snapshot,
        generate_weekly_narrative(report_snapshot),
    )
    session = RecordingSession(FakeResponse(200, {"message": "ok"}))

    with pytest.raises(EmailDeliveryError, match="without an email id"):
        send_rendered_email(
            rendered,
            api_key="resend-test-key",
            from_address="reports@example.com",
            recipients="owner@example.com",
            idempotency_key="weekly-2026-07-24",
            session=session,
        )
