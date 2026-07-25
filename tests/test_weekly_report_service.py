"""Focused orchestration and idempotency tests for the weekly report."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta

import pytest
import requests

from app.extensions import db
from app.models.weekly_report_run import WeeklyReportRun
from app.reporting.ai import NarrativeResult
from app.reporting.email import (
    EmailDeliveryError,
    EmailSendResult,
    RenderedEmail,
)
from app.reporting.periods import build_report_window
from app.reporting import service


REPORT_END = "2026-07-24"


def _snapshot() -> dict:
    return {
        "currency": "USD",
        "window": {
            "report_date": REPORT_END,
            "current_start": "2026-07-17T00:00:00+08:00",
            "current_end": "2026-07-24T00:00:00+08:00",
        },
        "periods": {
            "current": {
                "net_sales": 1200.0,
                "orders": 12,
                "aov": 100.0,
                "units": 18,
                "refunds": 0.0,
                "comparison": {},
            }
        },
        "channels": [],
        "countries": [],
        "products": [],
        "stock": [],
        "gsc": {"status": "unavailable"},
    }


def _narrative() -> NarrativeResult:
    return NarrativeResult(
        executive_summary="Sales were steady this week.",
        highlights=("Twelve orders were collected.",),
        actions=("Review the strongest product mover.",),
        caveats=("Attribution is directional.",),
        generated_by_ai=True,
        model="test-model",
    )


def _rendered() -> RenderedEmail:
    return RenderedEmail(
        subject="RCJ Weekly Business Pulse",
        html="<html><body>Weekly pulse</body></html>",
        text="Weekly pulse\n",
        attachments=(),
    )


def _enable_delivery(app, monkeypatch) -> None:
    values = {
        "WEEKLY_REPORT_ENABLED": True,
        "WEEKLY_REPORT_REVISION": 1,
        "WEEKLY_REPORT_EMAIL_TO": "owners@example.com",
        "WEEKLY_REPORT_EMAIL_FROM": "reports@example.com",
        "RESEND_API_KEY": "re_test_key",
        "OPENAI_API_KEY": "openai-test-key",
    }
    for name, value in values.items():
        monkeypatch.setitem(app.config, name, value)


def test_reporting_shopify_connection_is_separate_from_price_sync(app):
    app.config["SHOPIFY_REPORT_SHOP"] = "reporting.myshopify.com"
    app.config["SHOPIFY_REPORT_API_VERSION"] = "2026-07"
    app.config["SHOPIFY_REPORT_CLIENT_ID"] = None
    app.config["SHOPIFY_REPORT_CLIENT_SECRET"] = None
    app.config["SHOPIFY_REPORT_TOKEN"] = "report-token"
    app.config["SHOPIFY_SHOP"] = "price-sync.myshopify.com"
    app.config["SHOPIFY_API_VERSION"] = "2025-01"
    app.config["SHOPIFY_ADMIN_TOKEN"] = "write-token"

    with app.app_context():
        client = service._shopify_client()

    assert client.shop == "reporting.myshopify.com"
    assert client.api_version == "2026-07"
    assert client.token == "report-token"


def test_reporting_shopify_client_credentials_are_preferred(app):
    app.config["SHOPIFY_REPORT_SHOP"] = "reporting.myshopify.com"
    app.config["SHOPIFY_REPORT_API_VERSION"] = "2026-07"
    app.config["SHOPIFY_REPORT_CLIENT_ID"] = "report-client-id"
    app.config["SHOPIFY_REPORT_CLIENT_SECRET"] = "report-client-secret"
    app.config["SHOPIFY_REPORT_TOKEN"] = "static-fallback"

    with app.app_context():
        client = service._shopify_client()

    assert client.client_id == "report-client-id"
    assert client.client_secret == "report-client-secret"
    assert client.token == "static-fallback"


def test_reporting_shopify_client_credentials_must_be_complete(app):
    app.config["SHOPIFY_REPORT_CLIENT_ID"] = "report-client-id"
    app.config["SHOPIFY_REPORT_CLIENT_SECRET"] = None
    app.config["SHOPIFY_REPORT_TOKEN"] = "static-fallback"

    with app.app_context(), pytest.raises(
        service.WeeklyReportError,
        match=(
            "SHOPIFY_REPORT_CLIENT_ID and SHOPIFY_REPORT_CLIENT_SECRET "
            "must be set together"
        ),
    ):
        service._shopify_client()


def test_reporting_errors_redact_shopify_client_secret(app):
    app.config["SHOPIFY_REPORT_CLIENT_SECRET"] = "do-not-leak-this"

    with app.app_context():
        message = service._safe_error(
            RuntimeError("credential do-not-leak-this was rejected")
        )

    assert "do-not-leak-this" not in message
    assert "[redacted]" in message


def _install_report_stubs(monkeypatch, *, send):
    import app.reporting.ai as ai_module
    import app.reporting.email as email_module

    build_calls: list[str] = []

    def fake_build(window):
        build_calls.append(window.report_date.isoformat())
        return _snapshot(), []

    monkeypatch.setattr(service, "_build_snapshot", fake_build)
    monkeypatch.setattr(
        ai_module,
        "generate_weekly_narrative",
        lambda *args, **kwargs: _narrative(),
    )
    monkeypatch.setattr(
        email_module,
        "render_weekly_email",
        lambda *args, **kwargs: _rendered(),
    )
    monkeypatch.setattr(email_module, "send_rendered_email", send)
    return build_calls


def test_dry_run_avoids_database_openai_and_email(
    app,
    db_session,
    monkeypatch,
    tmp_path,
):
    import app.reporting.ai as ai_module
    import app.reporting.email as email_module

    monkeypatch.setitem(app.config, "OPENAI_API_KEY", "must-not-be-used")
    monkeypatch.setattr(
        service,
        "_ensure_run_table",
        lambda: pytest.fail("dry-run must not initialise delivery state"),
    )
    monkeypatch.setattr(
        service,
        "_build_snapshot",
        lambda window: (_snapshot(), ["Google Search"]),
    )
    monkeypatch.setattr(
        ai_module.requests,
        "post",
        lambda *args, **kwargs: pytest.fail(
            "dry-run must not call the OpenAI API"
        ),
    )
    monkeypatch.setattr(
        email_module,
        "render_weekly_email",
        lambda *args, **kwargs: _rendered(),
    )
    monkeypatch.setattr(
        email_module,
        "send_rendered_email",
        lambda *args, **kwargs: pytest.fail("dry-run must not send email"),
    )

    with app.app_context():
        before = WeeklyReportRun.query.count()
        result = service.run_weekly_business_report(
            window_end=REPORT_END,
            dry_run=True,
            output=tmp_path,
        )
        after = WeeklyReportRun.query.count()

    assert result.status == "previewed"
    assert result.partial_sources == ("Google Search",)
    assert before == after == 0
    assert (tmp_path / "weekly-report.html").read_text() == _rendered().html
    assert (tmp_path / "weekly-report.txt").read_text() == _rendered().text


def test_active_claim_is_not_claimed_twice(app, db_session, monkeypatch):
    monkeypatch.setitem(app.config, "WEEKLY_REPORT_LEASE_SECONDS", 3600)
    window = build_report_window(REPORT_END)

    with app.app_context():
        first_claim, first_status = service._claim_run(
            window,
            1,
            force_resend=False,
        )
        second_claim, second_status = service._claim_run(
            window,
            1,
            force_resend=False,
        )
        run = WeeklyReportRun.query.one()

    assert first_status == "claimed"
    assert first_claim is not None
    assert second_status == "active_run"
    assert second_claim is None
    assert run.attempt_count == 1


def test_force_resend_does_not_steal_an_active_claim(
    app,
    db_session,
    monkeypatch,
):
    monkeypatch.setitem(app.config, "WEEKLY_REPORT_LEASE_SECONDS", 3600)
    window = build_report_window(REPORT_END)

    with app.app_context():
        first_claim, _ = service._claim_run(window, 1, force_resend=False)
        original = WeeklyReportRun.query.one()
        original_lease = original.lease_token
        forced_claim, forced_status = service._claim_run(
            window,
            1,
            force_resend=True,
        )
        run = WeeklyReportRun.query.one()

    assert first_claim is not None
    assert forced_claim is None
    assert forced_status == "active_run"
    assert run.lease_token == original_lease
    assert run.delivery_generation == 1
    assert run.attempt_count == 1


def test_expired_delivery_lease_requires_manual_reconciliation(
    app,
    db_session,
    monkeypatch,
):
    window = build_report_window(REPORT_END)

    with app.app_context():
        claim, _ = service._claim_run(window, 1, force_resend=False)
        run = WeeklyReportRun.query.one()
        run.status = WeeklyReportRun.STATUS_DELIVERING
        run.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()

        retry_claim, retry_status = service._claim_run(
            window,
            1,
            force_resend=False,
        )
        run = WeeklyReportRun.query.one()

    assert claim is not None
    assert retry_claim is None
    assert retry_status == "delivery_unknown"
    assert run.status == WeeklyReportRun.STATUS_DELIVERY_UNKNOWN
    assert run.lease_token is None
    assert run.attempt_count == 1


def test_delivered_report_is_not_sent_twice(
    app,
    db_session,
    monkeypatch,
):
    _enable_delivery(app, monkeypatch)
    sends: list[str] = []

    def fake_send(message, **kwargs):
        sends.append(kwargs["idempotency_key"])
        return EmailSendResult(provider_id="email-first", status_code=200)

    build_calls = _install_report_stubs(monkeypatch, send=fake_send)

    with app.app_context():
        first = service.run_weekly_business_report(window_end=REPORT_END)
        second = service.run_weekly_business_report(window_end=REPORT_END)
        run = WeeklyReportRun.query.one()

    assert first.status == "sent"
    assert second.status == "already_sent"
    assert sends == [f"rcj-weekly/{REPORT_END}/r1/g1"]
    assert build_calls == [REPORT_END]
    assert run.status == WeeklyReportRun.STATUS_DELIVERED
    assert run.provider_id == "email-first"
    assert run.attempt_count == 1


def test_force_resend_uses_a_new_delivery_generation(
    app,
    db_session,
    monkeypatch,
):
    _enable_delivery(app, monkeypatch)
    sends: list[str] = []

    def fake_send(message, **kwargs):
        sends.append(kwargs["idempotency_key"])
        return EmailSendResult(
            provider_id=f"email-{len(sends)}",
            status_code=200,
        )

    build_calls = _install_report_stubs(monkeypatch, send=fake_send)

    with app.app_context():
        first = service.run_weekly_business_report(window_end=REPORT_END)
        second = service.run_weekly_business_report(
            window_end=REPORT_END,
            force_resend=True,
        )
        run = WeeklyReportRun.query.one()

    assert first.status == second.status == "sent"
    assert sends == [
        f"rcj-weekly/{REPORT_END}/r1/g1",
        f"rcj-weekly/{REPORT_END}/r1/g2",
    ]
    assert build_calls == [REPORT_END, REPORT_END]
    assert run.delivery_generation == 2
    assert run.idempotency_key == sends[-1]
    assert run.provider_id == "email-2"
    assert run.attempt_count == 2


def test_ambiguous_resend_timeout_stops_automatic_retry(
    app,
    db_session,
    monkeypatch,
):
    _enable_delivery(app, monkeypatch)

    def timed_out_send(message, **kwargs):
        try:
            raise requests.Timeout("socket timed out after request upload")
        except requests.Timeout as cause:
            raise EmailDeliveryError(
                "Resend request failed: socket timed out"
            ) from cause

    _install_report_stubs(monkeypatch, send=timed_out_send)

    with app.app_context():
        with pytest.raises(service.DeliveryStateUnknown):
            service.run_weekly_business_report(window_end=REPORT_END)
        retry = service.run_weekly_business_report(window_end=REPORT_END)
        run = WeeklyReportRun.query.one()

    assert run.status == WeeklyReportRun.STATUS_DELIVERY_UNKNOWN
    assert run.lease_token is None
    assert run.provider_id is None
    assert retry.status == "delivery_unknown"


def test_provider_acceptance_with_confirmation_failure_is_delivery_unknown(
    app,
    db_session,
    monkeypatch,
):
    _enable_delivery(app, monkeypatch)
    accepted: list[str] = []

    def accepted_send(message, **kwargs):
        accepted.append(kwargs["idempotency_key"])
        return EmailSendResult(provider_id="email-accepted", status_code=200)

    _install_report_stubs(monkeypatch, send=accepted_send)
    confirmation_error = service.WeeklyReportError(
        "database failed after provider acceptance"
    )
    actual_mark_failed = service._mark_failed
    failure_attempts: list[dict] = []

    def fail_confirmation(*args, **kwargs):
        raise confirmation_error

    def record_mark_failed(run_id, lease_token, exc, **kwargs):
        failure_attempts.append(
            {
                "run_id": run_id,
                "lease_token": lease_token,
                "exception": exc,
                **kwargs,
            }
        )
        return actual_mark_failed(run_id, lease_token, exc, **kwargs)

    monkeypatch.setattr(service, "_mark_delivered", fail_confirmation)
    monkeypatch.setattr(service, "_mark_failed", record_mark_failed)
    monkeypatch.setattr(
        service,
        "_failure_notice",
        lambda *args, **kwargs: pytest.fail(
            "delivery confirmation failures must not trigger another email"
        ),
    )

    with app.app_context():
        with pytest.raises(service.DeliveryStateUnknown) as exc_info:
            service.run_weekly_business_report(window_end=REPORT_END)
        run = WeeklyReportRun.query.one()

    assert exc_info.value.__cause__ is confirmation_error
    assert accepted == [f"rcj-weekly/{REPORT_END}/r1/g1"]
    assert len(failure_attempts) == 1
    assert failure_attempts[0]["exception"] is confirmation_error
    assert failure_attempts[0]["stage"] == "delivery_confirmation"
    assert failure_attempts[0]["delivery_unknown"] is True
    assert run.status == WeeklyReportRun.STATUS_DELIVERY_UNKNOWN
    assert run.error_stage == "delivery_confirmation"
    assert run.lease_token is None


def test_unexpected_pre_delivery_failure_attempts_failure_notice(
    app,
    db_session,
    monkeypatch,
):
    _enable_delivery(app, monkeypatch)
    source_error = RuntimeError("unexpected aggregate failure")
    notices: list[tuple[str, Exception]] = []

    monkeypatch.setattr(
        service,
        "_build_snapshot",
        lambda window: (_ for _ in ()).throw(source_error),
    )
    monkeypatch.setattr(
        service,
        "_failure_notice",
        lambda window, exc: notices.append(
            (window.report_date.isoformat(), exc)
        ),
    )

    with app.app_context():
        with pytest.raises(RuntimeError, match="unexpected aggregate failure"):
            service.run_weekly_business_report(window_end=REPORT_END)
        run = WeeklyReportRun.query.one()

    assert notices == [(REPORT_END, source_error)]
    assert run.status == WeeklyReportRun.STATUS_FAILED
    assert run.error_stage == "source_collection"
    assert run.lease_token is None


def test_email_delivery_failure_does_not_send_a_failure_notice(
    app,
    db_session,
    monkeypatch,
):
    _enable_delivery(app, monkeypatch)

    def rejected_send(message, **kwargs):
        raise EmailDeliveryError(
            "Resend returned HTTP 400: invalid recipient",
            status_code=400,
        )

    _install_report_stubs(monkeypatch, send=rejected_send)
    monkeypatch.setattr(
        service,
        "_failure_notice",
        lambda *args, **kwargs: pytest.fail(
            "email-delivery failures must not trigger recursive email"
        ),
    )

    with app.app_context():
        with pytest.raises(EmailDeliveryError, match="HTTP 400"):
            service.run_weekly_business_report(window_end=REPORT_END)
        run = WeeklyReportRun.query.one()

    assert run.status == WeeklyReportRun.STATUS_FAILED
    assert run.error_stage == "email_delivery"
    assert run.lease_token is None


def test_reporting_client_never_falls_back_to_write_token(
    app,
    monkeypatch,
):
    monkeypatch.setitem(app.config, "SHOPIFY_REPORT_CLIENT_ID", None)
    monkeypatch.setitem(app.config, "SHOPIFY_REPORT_CLIENT_SECRET", None)
    monkeypatch.setitem(app.config, "SHOPIFY_REPORT_TOKEN", None)
    monkeypatch.setitem(app.config, "SHOPIFY_ADMIN_TOKEN", "write-capable-token")
    monkeypatch.setitem(app.config, "SHOPIFY_SHOP", "example.myshopify.com")

    with app.app_context(), pytest.raises(
        service.WeeklyReportError,
        match="SHOPIFY_REPORT_TOKEN is required",
    ):
        service._shopify_client()


@pytest.mark.parametrize(
    ("arguments", "expected_error"),
    [
        (
            ["weekly-report", "--force-resend"],
            "--force-resend requires an explicit --window-end",
        ),
        (
            ["weekly-report", "--dry-run", "--window-end", "2026-07-25"],
            "window end must be a Friday",
        ),
    ],
)
def test_cli_rejects_unsafe_or_invalid_windows(
    monkeypatch,
    capsys,
    arguments,
    expected_error,
):
    from scripts import run_weekly_business_report as cli

    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(
        cli,
        "create_app",
        lambda *args, **kwargs: pytest.fail(
            "CLI must validate arguments before creating the app"
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 2
    assert expected_error in capsys.readouterr().err


@pytest.mark.parametrize("status", ["disabled", "delivery_unknown"])
def test_cli_returns_two_for_non_success_terminal_status(
    app,
    monkeypatch,
    capsys,
    status,
):
    from scripts import run_weekly_business_report as cli

    result = service.WeeklyReportResult(
        status=status,
        window_end=REPORT_END,
        revision=1,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["weekly-report", "--window-end", REPORT_END],
    )
    monkeypatch.setattr(cli, "create_app", lambda *args, **kwargs: app)
    monkeypatch.setattr(
        cli,
        "run_weekly_business_report",
        lambda **kwargs: result,
    )

    exit_code = cli.main()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert output["status"] == status
    assert output["window_end"] == REPORT_END


def test_cli_returns_two_when_delivery_state_becomes_unknown(
    app,
    monkeypatch,
    capsys,
):
    from scripts import run_weekly_business_report as cli

    monkeypatch.setattr(
        sys,
        "argv",
        ["weekly-report", "--window-end", REPORT_END],
    )
    monkeypatch.setattr(cli, "create_app", lambda *args, **kwargs: app)
    monkeypatch.setattr(
        cli,
        "run_weekly_business_report",
        lambda **kwargs: (_ for _ in ()).throw(
            service.DeliveryStateUnknown("reconcile delivery in Resend")
        ),
    )

    exit_code = cli.main()
    output = json.loads(capsys.readouterr().err)

    assert exit_code == 2
    assert output == {
        "error": "reconcile delivery in Resend",
        "error_type": "DeliveryStateUnknown",
        "status": "delivery_unknown",
    }
