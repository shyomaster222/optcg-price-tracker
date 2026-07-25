"""Orchestration and idempotent delivery for the weekly RCJ report."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.reporting.metrics import summarize_shopify
from app.reporting.periods import ReportWindow, build_report_window
from app.reporting.sources import (
    GoogleSearchConsoleClient,
    ReportSourceError,
    ShopifyReportClient,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WeeklyReportResult:
    status: str
    window_end: str
    revision: int
    partial_sources: tuple[str, ...] = ()
    provider_id: str | None = None
    subject: str | None = None
    output_files: tuple[str, ...] = ()
    message: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class WeeklyReportError(RuntimeError):
    pass


class DeliveryStateUnknown(WeeklyReportError):
    pass


def _delivery_state_is_unknown(exc: Exception) -> bool:
    """Return whether a provider may have accepted the message.

    Transport exceptions are commonly wrapped by the email adapter, so inspect
    the full exception chain rather than only the outer error type.
    """

    try:
        from app.reporting.email import EmailDeliveryError
    except ImportError:  # pragma: no cover - defensive during partial installs
        EmailDeliveryError = ()  # type: ignore[assignment]

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, ConnectionError)):
            return True
        if current.__class__.__name__ in {
            "Timeout",
            "ConnectTimeout",
            "ReadTimeout",
            "ConnectionError",
            "ChunkedEncodingError",
            "ProxyError",
            "SSLError",
        }:
            return True
        if EmailDeliveryError and isinstance(current, EmailDeliveryError):
            status_code = getattr(current, "status_code", None)
            if status_code is None or 200 <= int(status_code) < 300:
                return True
        current = current.__cause__ or current.__context__
    return False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _split_csv(value) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _safe_error(exc: Exception, limit: int = 500) -> str:
    text = f"{type(exc).__name__}: {exc}"
    for secret_name in (
        "SHOPIFY_REPORT_TOKEN",
        "SHOPIFY_ADMIN_TOKEN",
        "GSC_CLIENT_SECRET",
        "GSC_REFRESH_TOKEN",
        "OPENAI_API_KEY",
        "RESEND_API_KEY",
    ):
        secret = current_app.config.get(secret_name)
        if secret:
            text = text.replace(str(secret), "[redacted]")
    return text[:limit]


def _required(value, name: str):
    if value is None or value == "" or value == [] or value == ():
        raise WeeklyReportError(f"{name} is required")
    return value


def _shopify_client() -> ShopifyReportClient:
    return ShopifyReportClient(
        shop=_required(
            current_app.config.get("SHOPIFY_REPORT_SHOP"),
            "SHOPIFY_REPORT_SHOP",
        ),
        token=_required(
            current_app.config.get("SHOPIFY_REPORT_TOKEN"),
            "SHOPIFY_REPORT_TOKEN",
        ),
        api_version=current_app.config.get(
            "SHOPIFY_REPORT_API_VERSION",
            "2026-07",
        ),
        timeout=float(current_app.config.get("WEEKLY_REPORT_SOURCE_TIMEOUT_SECONDS", 45)),
    )


def _gsc_client() -> GoogleSearchConsoleClient | None:
    values = {
        "client_id": current_app.config.get("GSC_CLIENT_ID"),
        "client_secret": current_app.config.get("GSC_CLIENT_SECRET"),
        "refresh_token": current_app.config.get("GSC_REFRESH_TOKEN"),
        "property_uri": current_app.config.get(
            "GSC_PROPERTY", "sc-domain:rarecardsjapan.com"
        ),
    }
    if not all(values.values()):
        return None
    return GoogleSearchConsoleClient(
        **values,
        timeout=float(current_app.config.get("WEEKLY_REPORT_SOURCE_TIMEOUT_SECONDS", 45)),
    )


def _ensure_run_table():
    from app.models.weekly_report_run import WeeklyReportRun

    WeeklyReportRun.__table__.create(bind=db.engine, checkfirst=True)


def _claim_run(
    window: ReportWindow,
    revision: int,
    *,
    force_resend: bool,
):
    from app.models.weekly_report_run import WeeklyReportRun

    now = _utcnow()
    lease_token = str(uuid.uuid4())
    lease_seconds = int(current_app.config.get("WEEKLY_REPORT_LEASE_SECONDS", 3600))

    try:
        run = (
            WeeklyReportRun.query.filter_by(
                window_end=window.report_date,
                revision=revision,
            )
            .with_for_update()
            .one_or_none()
        )
        if run is None:
            run = WeeklyReportRun(
                window_end=window.report_date,
                revision=revision,
                status="pending",
                delivery_generation=1,
            )
            db.session.add(run)
            db.session.flush()
        else:
            # Never let a manual resend steal an active worker's lease.
            if run.lease_is_active(now):
                db.session.commit()
                return None, "active_run"
            if run.status == "delivering" and not force_resend:
                # A worker disappeared after entering the provider-delivery
                # phase. Re-sending automatically could create a duplicate
                # after the provider's idempotency window expires.
                run.mark_failed(
                    "Delivery worker lease expired before confirmation",
                    stage="email_delivery",
                    now=now,
                    delivery_unknown=True,
                )
                db.session.commit()
                return None, "delivery_unknown"
            if force_resend:
                run.delivery_generation = int(run.delivery_generation or 1) + 1
            elif run.status == "delivered":
                db.session.commit()
                return None, "already_sent"
            elif run.status == "delivery_unknown":
                db.session.commit()
                return None, "delivery_unknown"

        run.claim(lease_token, now=now, lease_seconds=lease_seconds)
        run.idempotency_key = (
            f"rcj-weekly/{window.report_date.isoformat()}/"
            f"r{revision}/g{run.delivery_generation}"
        )
        db.session.commit()
        return (run.id, lease_token), "claimed"
    except IntegrityError:
        db.session.rollback()
        run = WeeklyReportRun.query.filter_by(
            window_end=window.report_date,
            revision=revision,
        ).one_or_none()
        if run and run.status == "delivered":
            return None, "already_sent"
        return None, "active_run"


def _owned_run(run_id: int, lease_token: str):
    from app.models.weekly_report_run import WeeklyReportRun

    run = WeeklyReportRun.query.filter_by(id=run_id).one()
    if run.lease_token != lease_token:
        raise WeeklyReportError("weekly report lease was lost")
    return run


def _persist_generated(
    run_id: int,
    lease_token: str,
    *,
    snapshot: dict,
    subject: str,
    html: str,
    partial_sources: list[str],
):
    run = _owned_run(run_id, lease_token)
    run.snapshot = snapshot
    run.report_payload = {
        "subject": subject,
        "partial_sources": partial_sources,
        "content_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
    }
    run.generated_at = _utcnow()
    run.status = "generated"
    db.session.commit()


def _mark_sending(run_id: int, lease_token: str):
    run = _owned_run(run_id, lease_token)
    run.prepare_delivery(now=_utcnow())
    db.session.commit()
    return run.idempotency_key


def _mark_delivered(run_id: int, lease_token: str, provider_id: str | None):
    run = _owned_run(run_id, lease_token)
    run.mark_delivered(provider_id=provider_id, now=_utcnow())
    db.session.commit()


def _mark_failed(
    run_id: int | None,
    lease_token: str | None,
    exc: Exception,
    *,
    stage: str | None = None,
    delivery_unknown: bool = False,
):
    if run_id is None or lease_token is None:
        return
    try:
        run = _owned_run(run_id, lease_token)
        run.mark_failed(
            _safe_error(exc),
            stage=stage,
            now=_utcnow(),
            delivery_unknown=delivery_unknown,
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Could not persist weekly report failure state")


def _atomic_write(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_preview(output: str | os.PathLike, rendered) -> tuple[str, ...]:
    destination = Path(output).expanduser().resolve()
    if destination.suffix.lower() == ".html":
        directory = destination.parent
        html_path = destination
    else:
        directory = destination
        html_path = directory / "weekly-report.html"
    text_path = directory / "weekly-report.txt"
    _atomic_write(html_path, rendered.html.encode("utf-8"))
    _atomic_write(text_path, rendered.text.encode("utf-8"))
    files = [str(html_path), str(text_path)]
    for attachment in rendered.attachments:
        attachment_path = directory / attachment.filename
        _atomic_write(attachment_path, attachment.content)
        files.append(str(attachment_path))
    return tuple(files)


def _failure_notice(window: ReportWindow, exc: Exception):
    from app.reporting.email import RenderedEmail, send_rendered_email

    api_key = current_app.config.get("RESEND_API_KEY")
    from_address = (
        current_app.config.get("WEEKLY_REPORT_EMAIL_FROM")
        or current_app.config.get("COMPANY_EMAIL")
    )
    recipients = _split_csv(
        current_app.config.get("WEEKLY_REPORT_EMAIL_TO")
        or current_app.config.get("COMPANY_EMAIL")
    )
    if not all([api_key, from_address, recipients]):
        return
    error = _safe_error(exc)
    error_html = escape(error)
    message = RenderedEmail(
        subject=f"RCJ Weekly Business Pulse failed · {window.report_date.isoformat()}",
        html=(
            "<h1>RCJ weekly report failed</h1>"
            f"<p>The sales dashboard could not be generated for the window ending "
            f"{window.report_date.isoformat()}.</p><p>{error_html}</p>"
        ),
        text=(
            "RCJ weekly report failed\n\n"
            f"Window ending: {window.report_date.isoformat()}\n"
            f"Error: {error}\n"
        ),
        attachments=(),
    )
    send_rendered_email(
        message,
        api_key=api_key,
        from_address=from_address,
        recipients=recipients,
        idempotency_key=f"rcj-weekly-failure/{window.report_date.isoformat()}",
    )


def _build_snapshot(window: ReportWindow) -> tuple[dict, list[str]]:
    partial: list[str] = []
    source_status: dict[str, dict] = {}
    shopify = _shopify_client()
    bootstrap = shopify.validate_access()
    orders = shopify.fetch_orders(window.fetch_start, window.current_end)
    source_status["shopify_sales"] = {
        "status": "ok" if not shopify.warnings else "partial",
        "as_of": window.current_end.isoformat(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "api_version": bootstrap["api_version"],
        "record_count": len(orders),
        "warnings": list(shopify.warnings),
    }
    if shopify.warnings:
        partial.append("Shopify attribution/country")

    try:
        catalog = shopify.fetch_catalog()
        source_status["shopify_stock"] = {
            "status": "ok",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "record_count": sum(
                len(((product.get("variants") or {}).get("nodes") or []))
                for product in catalog
            ),
        }
    except Exception as exc:
        catalog = []
        partial.append("Stock")
        source_status["shopify_stock"] = {
            "status": "unavailable",
            "error": _safe_error(exc),
        }

    snapshot = summarize_shopify(
        orders,
        catalog,
        window,
        b2b_tags=_split_csv(
            current_app.config.get("WEEKLY_REPORT_B2B_TAGS", "B2B,Wholesale")
        ),
    )
    gsc = _gsc_client()
    if gsc is None:
        partial.append("Google Search")
        snapshot["gsc"] = {
            "status": "unavailable",
            "reason": "Google Search Console credentials are not configured",
        }
    else:
        try:
            snapshot["gsc"] = gsc.fetch_report()
        except Exception as exc:
            partial.append("Google Search")
            snapshot["gsc"] = {
                "status": "unavailable",
                "error": _safe_error(exc),
            }
    source_status["gsc"] = {
        key: snapshot["gsc"].get(key)
        for key in ("status", "as_of", "fetched_at", "error", "reason")
        if snapshot["gsc"].get(key) is not None
    }
    snapshot["source_status"] = source_status
    return snapshot, partial


def run_weekly_business_report(
    *,
    window_end: date | str | None = None,
    revision: int | None = None,
    dry_run: bool = False,
    output: str | os.PathLike | None = None,
    force_resend: bool = False,
) -> WeeklyReportResult:
    """Build and optionally deliver one weekly report."""

    from app.reporting.ai import generate_weekly_narrative
    from app.reporting.email import render_weekly_email, send_rendered_email

    if revision is None:
        revision = int(current_app.config.get("WEEKLY_REPORT_REVISION", 1))
    if revision < 1:
        raise ValueError("revision must be at least 1")
    window = build_report_window(
        window_end,
        timezone=current_app.config.get(
            "WEEKLY_REPORT_TIMEZONE", "Asia/Hong_Kong"
        ),
    )
    if not dry_run and not current_app.config.get("WEEKLY_REPORT_ENABLED", False):
        return WeeklyReportResult(
            status="disabled",
            window_end=window.report_date.isoformat(),
            revision=revision,
            message="WEEKLY_REPORT_ENABLED is false",
        )

    claim = None
    if not dry_run:
        try:
            _ensure_run_table()
            claim, claim_status = _claim_run(
                window,
                revision,
                force_resend=force_resend,
            )
        except Exception as exc:
            try:
                _failure_notice(window, exc)
            except Exception:
                logger.exception(
                    "Could not send weekly report database failure notice"
                )
            raise
        if claim is None:
            return WeeklyReportResult(
                status=claim_status,
                window_end=window.report_date.isoformat(),
                revision=revision,
            )
    run_id, lease_token = claim if claim else (None, None)

    stage = "source_collection"
    try:
        snapshot, partial_sources = _build_snapshot(window)
        stage = "ai_narrative"
        narrative = generate_weekly_narrative(
            snapshot,
            api_key=None if dry_run else current_app.config.get("OPENAI_API_KEY"),
            model=current_app.config.get(
                "OPENAI_WEEKLY_REPORT_MODEL", "gpt-5.6-terra"
            ),
            timeout=float(
                current_app.config.get("OPENAI_WEEKLY_REPORT_TIMEOUT_SECONDS", 30)
            ),
        )
        if not narrative.generated_by_ai and not dry_run:
            partial_sources.append("AI commentary")
        stage = "email_render"
        rendered = render_weekly_email(
            snapshot,
            narrative,
            partial_sources=tuple(dict.fromkeys(partial_sources)),
        )
        output_files = _write_preview(output, rendered) if output else ()

        if dry_run:
            return WeeklyReportResult(
                status="previewed",
                window_end=window.report_date.isoformat(),
                revision=revision,
                partial_sources=tuple(dict.fromkeys(partial_sources)),
                subject=rendered.subject,
                output_files=output_files,
            )

        stage = "checkpoint"
        _persist_generated(
            run_id,
            lease_token,
            snapshot=snapshot,
            subject=rendered.subject,
            html=rendered.html,
            partial_sources=partial_sources,
        )
        idempotency_key = _mark_sending(run_id, lease_token)
        recipients = _split_csv(
            current_app.config.get("WEEKLY_REPORT_EMAIL_TO")
            or current_app.config.get("COMPANY_EMAIL")
        )
        stage = "email_delivery"
        result = send_rendered_email(
            rendered,
            api_key=_required(
                current_app.config.get("RESEND_API_KEY"), "RESEND_API_KEY"
            ),
            from_address=_required(
                current_app.config.get("WEEKLY_REPORT_EMAIL_FROM")
                or current_app.config.get("COMPANY_EMAIL"),
                "WEEKLY_REPORT_EMAIL_FROM",
            ),
            recipients=_required(recipients, "WEEKLY_REPORT_EMAIL_TO"),
            idempotency_key=idempotency_key,
        )
        stage = "delivery_confirmation"
        _mark_delivered(run_id, lease_token, result.provider_id)
        return WeeklyReportResult(
            status="sent",
            window_end=window.report_date.isoformat(),
            revision=revision,
            partial_sources=tuple(dict.fromkeys(partial_sources)),
            provider_id=result.provider_id,
            subject=rendered.subject,
            output_files=output_files,
        )
    except (ReportSourceError, WeeklyReportError) as exc:
        delivery_unknown = stage == "delivery_confirmation"
        _mark_failed(
            run_id,
            lease_token,
            exc,
            stage=stage,
            delivery_unknown=delivery_unknown,
        )
        if stage not in {"email_delivery", "delivery_confirmation"}:
            try:
                _failure_notice(window, exc)
            except Exception:
                logger.exception("Could not send weekly report failure notice")
        if delivery_unknown:
            raise DeliveryStateUnknown(
                "Email was accepted but delivery state could not be persisted; "
                "reconcile in Resend before forcing another send"
            ) from exc
        raise
    except Exception as exc:
        delivery_unknown = (
            stage == "delivery_confirmation"
            or (
                stage == "email_delivery"
                and _delivery_state_is_unknown(exc)
            )
        )
        _mark_failed(
            run_id,
            lease_token,
            exc,
            stage=stage,
            delivery_unknown=delivery_unknown,
        )
        if stage not in {"email_delivery", "delivery_confirmation"}:
            try:
                _failure_notice(window, exc)
            except Exception:
                logger.exception("Could not send weekly report failure notice")
        if delivery_unknown:
            raise DeliveryStateUnknown(
                "Email delivery state is unknown; reconcile in Resend before forcing another send"
            ) from exc
        raise
