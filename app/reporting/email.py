"""Jinja rendering and raw Resend delivery for the weekly report."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape
import requests

from app.reporting.ai import NarrativeResult, generate_weekly_narrative
from app.reporting.charts import (
    ACQUISITION_CHART_CID,
    CHART_FILENAMES,
    COUNTRIES_STOCK_CHART_CID,
    SALES_CHART_CID,
    render_weekly_charts,
)


RESEND_EMAILS_URL = "https://api.resend.com/emails"
RESEND_TIMEOUT = 30
RCJ_LOGO_URL = (
    "https://rarecardsjapan.com/cdn/shop/files/"
    "Rare_Cards_Japan.png?v=1762075467&width=500"
)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_LONG_NUMBER_RE = re.compile(r"\b\d{7,}\b")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class InlineAttachment:
    """An inline MIME attachment referenced from HTML with ``cid:``."""

    filename: str
    content_type: str
    content_id: str
    content: bytes

    @property
    def cid(self) -> str:
        return self.content_id

    @property
    def data(self) -> bytes:
        return self.content

    @property
    def mime_type(self) -> str:
        return self.content_type


@dataclass(frozen=True)
class RenderedEmail:
    """Provider-neutral rendered weekly email."""

    subject: str
    html: str
    text: str
    attachments: tuple[InlineAttachment, ...]

    @property
    def html_body(self) -> str:
        return self.html

    @property
    def text_body(self) -> str:
        return self.text

    @property
    def inline_attachments(self) -> tuple[InlineAttachment, ...]:
        return self.attachments


@dataclass(frozen=True)
class EmailSendResult:
    """The acknowledgement returned by Resend."""

    provider_id: str
    status_code: int

    @property
    def id(self) -> str:
        return self.provider_id

    @property
    def accepted(self) -> bool:
        return 200 <= self.status_code < 300


class EmailDeliveryError(RuntimeError):
    """Resend could not truthfully acknowledge the email."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _money(value: Any, currency: str = "USD", decimals: int = 0) -> str:
    number = _number(value)
    if number is None:
        return "n/a"
    places = 2 if int(decimals or 0) == 2 else 0
    return f"{currency} {number:,.{places}f}"


def _percent(value: Any, signed: bool = False) -> str:
    number = _number(value)
    if number is None:
        return "n/a"
    prefix = "+" if bool(signed) and number > 0 else ""
    return f"{prefix}{number:.1%}"


def _integer(value: Any) -> str:
    number = _number(value)
    return f"{int(round(number)):,}" if number is not None else "n/a"


def _plural(value: Any, singular: str, plural: str | None = None) -> str:
    number = _number(value)
    return singular if number == 1 else (plural or f"{singular}s")


def _signed_integer(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "n/a"
    return f"{number:+,.0f}"


def _decimal(value: Any, places: int = 1) -> str:
    number = _number(value)
    return f"{number:,.{int(places)}f}" if number is not None else "n/a"


def _signed_decimal(value: Any, places: int = 1) -> str:
    number = _number(value)
    return f"{number:+,.{int(places)}f}" if number is not None else "n/a"


def _display_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y")
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    text = str(value or "")
    try:
        return date.fromisoformat(text[:10]).strftime("%d %b %Y")
    except ValueError:
        return text or "Date unavailable"


def _metric_change(current: Mapping[str, Any], key: str) -> float | None:
    comparison = _mapping(_mapping(current.get("comparison")).get(key))
    return _number(comparison.get("percent"))


_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
_JINJA = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(
        enabled_extensions=("html", "htm", "xml"),
        default_for_string=True,
        default=False,
    ),
    trim_blocks=True,
    lstrip_blocks=True,
)
_JINJA.filters.update(
    money=_money,
    percent=_percent,
    integer=_integer,
    plural=_plural,
    signed_integer=_signed_integer,
    decimal=_decimal,
    signed_decimal=_signed_decimal,
    display_date=_display_date,
)


def _normalise_narrative(
    snapshot: Mapping[str, Any],
    value: NarrativeResult | Mapping[str, Any] | Any,
) -> NarrativeResult:
    if isinstance(value, NarrativeResult):
        return value
    if isinstance(value, Mapping):
        return NarrativeResult(
            headline=str(value.get("headline") or "Sales update"),
            executive_summary=str(
                value.get("executive_summary")
                or value.get("summary")
                or "Verified totals are shown below."
            ),
            highlights=tuple(
                str(item)
                for item in (
                    value.get("highlights")
                    or value.get("insights")
                    or ()
                )
            ),
            actions=tuple(
                str(item)
                for item in (
                    value.get("actions")
                    or value.get("recommendations")
                    or ()
                )
            ),
            caveats=tuple(str(item) for item in (value.get("caveats") or ())),
            generated_by_ai=bool(value.get("generated_by_ai")),
            model=str(value.get("model")) if value.get("model") else None,
            error=str(value.get("error")) if value.get("error") else None,
        )
    if value is not None and hasattr(value, "executive_summary"):
        return NarrativeResult(
            headline=str(getattr(value, "headline", "Sales update")),
            executive_summary=str(getattr(value, "executive_summary")),
            highlights=tuple(getattr(value, "highlights", ()) or ()),
            actions=tuple(getattr(value, "actions", ()) or ()),
            caveats=tuple(getattr(value, "caveats", ()) or ()),
            generated_by_ai=bool(getattr(value, "generated_by_ai", False)),
            model=getattr(value, "model", None),
            error=getattr(value, "error", None),
        )
    return generate_weekly_narrative(snapshot, api_key=None)


def _normalise_partial_sources(value: Iterable[str] | str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    raw = (value,) if isinstance(value, str) else value
    seen: set[str] = set()
    result = []
    for item in raw:
        text = " ".join(str(item or "").split())
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return tuple(result)


def _safe_dimension(value: Any, *, limit: int = 160) -> str:
    """Sanitize a reporting dimension before it reaches an email template."""

    text = _CONTROL_RE.sub(" ", str(value or ""))
    text = _EMAIL_RE.sub("[redacted]", text)
    text = _LONG_NUMBER_RE.sub("[redacted]", text)
    return " ".join(text.split())[:limit]


def _query_text(value: Mapping[str, Any]) -> str:
    query = value.get("query")
    if query in (None, ""):
        keys = value.get("keys") or []
        if isinstance(keys, (list, tuple)) and keys:
            query = keys[0]
    return _safe_dimension(query or "Unknown query", limit=160)


def _gsc_row(value: Any, *, kind: str) -> dict[str, Any]:
    source = _mapping(value)
    result: dict[str, Any] = {"query": _query_text(source)}
    result.update(
        {
            key: _number(source.get(key))
            for key in (
            "clicks",
            "impressions",
            "ctr",
            "position",
            "click_delta",
            "impression_delta",
            "ctr_delta_pp",
            "position_improvement",
        )
        }
    )
    if kind == "mover":
        click_delta = result["click_delta"]
        if click_delta is not None and click_delta > 0:
            result["type"] = "More clicks"
        elif click_delta is not None and click_delta < 0:
            result["type"] = "Fewer clicks"
        else:
            result["type"] = "No change"
    elif kind == "opportunity":
        raw_type = _safe_dimension(source.get("type") or "", limit=60).lower()
        if "ctr" in raw_type or "click" in raw_type:
            result["type"] = "Low click rate"
        elif "striking" in raw_type or "position" in raw_type:
            result["type"] = "Close to top results"
        else:
            result["type"] = "Worth checking"
    else:
        result["type"] = "Top search"
    return result


def _gsc_view(value: Any) -> dict[str, Any]:
    """Keep only summary fields needed by the template; never retain page URLs."""

    source = _mapping(value)
    result: dict[str, Any] = {
        "status": _safe_dimension(source.get("status"), limit=30),
        "as_of": _safe_dimension(source.get("as_of"), limit=30),
        "timezone": _safe_dimension(source.get("timezone"), limit=60),
        "query_rows_are_partial": bool(source.get("query_rows_are_partial")),
    }
    for name in (
        "weekly_window",
        "previous_weekly_window",
        "query_window",
        "previous_query_window",
    ):
        raw_window = _mapping(source.get(name))
        result[name] = {
            "start": _safe_dimension(raw_window.get("start"), limit=30),
            "end": _safe_dimension(raw_window.get("end"), limit=30),
        }
    for period in ("current", "previous"):
        raw_period = _mapping(source.get(period))
        result[period] = {
            key: _number(raw_period.get(key))
            for key in ("clicks", "impressions", "ctr", "position")
        }
    comparison = {}
    for key in ("clicks", "impressions", "ctr", "position"):
        raw = _mapping(_mapping(source.get("comparison")).get(key))
        comparison[key] = {
            "absolute": _number(raw.get("absolute")),
            "percent": _number(raw.get("percent")),
        }
    result["comparison"] = comparison
    return result


def _landing_path(value: Any) -> str:
    text = _safe_dimension(value or "/", limit=240)
    if "://" in text:
        text = urlsplit(text).path
    text = text.split("?", 1)[0].split("#", 1)[0]
    return text[:160] or "/"


def _landing_page_rows(value: Any, *, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    for raw_row in value[:limit]:
        source = _mapping(raw_row)
        result.append(
            {
                "label": _landing_path(source.get("label")),
                "orders": _number(source.get("orders")),
                "net_sales": _number(source.get("net_sales")),
                "share": _number(source.get("share")),
            }
        )
    return result


def _view(
    snapshot: Mapping[str, Any],
    narrative: NarrativeResult,
    partial_sources: tuple[str, ...],
) -> dict[str, Any]:
    weekly = _mapping(snapshot.get("weekly"))
    current = _mapping(weekly.get("current"))
    monthly = _mapping(snapshot.get("monthly"))
    year_to_date = _mapping(snapshot.get("year_to_date"))
    analysis_window = _mapping(snapshot.get("analysis_window"))
    acquisition = _mapping(snapshot.get("acquisition"))
    stock = _mapping(snapshot.get("stock"))
    window = _mapping(snapshot.get("window"))
    raw_gsc = _mapping(snapshot.get("gsc"))
    gsc = _gsc_view(raw_gsc)
    landing = _mapping(snapshot.get("landing_pages"))
    landing_types = list(landing.get("types") or [])
    blog_assist = next(
        (
            row
            for row in landing_types
            if str(_mapping(row).get("label") or "").strip().lower() == "blog"
        ),
        {"label": "Blog", "orders": 0, "net_sales": 0, "share": 0},
    )
    report_caveats = [
        (
            "Sales collected means payments for orders processed in the period. "
            "It is not Shopify accounting net sales."
        ),
        (
            "Refund totals include all refunds linked to these orders, "
            "even if the refund happened later."
        ),
        (
            "The first known visit shows where an order started. "
            "It does not prove what caused the sale."
        ),
    ]
    report_date = window.get("report_date") or window.get("current_end") or ""
    return {
        "currency": str(snapshot.get("currency") or "USD"),
        "window": window,
        "report_date": report_date,
        "weekly": weekly,
        "current": current,
        "year_to_date": year_to_date,
        "analysis_window": analysis_window,
        "sales_change": _metric_change(current, "net_sales"),
        "orders_change": _metric_change(current, "orders"),
        "aov_change": _metric_change(current, "aov"),
        "units_change": _metric_change(current, "units"),
        "monthly": monthly,
        "channels": list(_mapping(snapshot.get("channels")).get("items") or []),
        "acquisition": acquisition,
        "acquisition_items": list(acquisition.get("items") or []),
        "countries": list(_mapping(snapshot.get("countries")).get("items") or []),
        "products": list(_mapping(snapshot.get("products")).get("items") or []),
        "stock": stock,
        "stock_actions": list(stock.get("action_items") or []),
        "landing_types": landing_types,
        "landing_top_pages": _landing_page_rows(
            landing.get("top_pages"),
            limit=6,
        ),
        "blog_assist": blog_assist,
        "gsc": gsc,
        "gsc_available": bool(gsc) and str(gsc.get("status") or "").lower() == "ok",
        "gsc_top_queries": [
            _gsc_row(row, kind="top")
            for row in list(raw_gsc.get("top_queries") or [])[:6]
        ],
        "gsc_query_movers": [
            _gsc_row(row, kind="mover")
            for row in list(raw_gsc.get("query_movers") or [])[:6]
        ],
        "gsc_opportunities": [
            _gsc_row(row, kind="opportunity")
            for row in list(raw_gsc.get("opportunities") or [])[:6]
        ],
        "data_quality": _mapping(snapshot.get("data_quality")),
        "narrative": narrative,
        "report_caveats": tuple(report_caveats),
        "partial_sources": partial_sources,
        "is_partial": bool(partial_sources),
        "sales_chart_cid": SALES_CHART_CID,
        "acquisition_chart_cid": ACQUISITION_CHART_CID,
        "countries_stock_chart_cid": COUNTRIES_STOCK_CHART_CID,
        "rcj_logo_url": RCJ_LOGO_URL,
    }


def render_weekly_email(
    snapshot: Mapping[str, Any] | None,
    narrative_result: NarrativeResult | Mapping[str, Any] | Any,
    *,
    partial_sources: Iterable[str] | str = (),
) -> RenderedEmail:
    """Render responsive HTML, plain text, and three matching inline charts."""

    source = _mapping(snapshot)
    narrative = _normalise_narrative(source, narrative_result)
    partial = _normalise_partial_sources(partial_sources)
    context = _view(source, narrative, partial)
    date_text = _display_date(context["report_date"])
    subject = f"RCJ sales update — {date_text}"
    if partial:
        subject = f"RCJ sales update (partial) — {date_text}"

    html = _JINJA.get_template("email/weekly_report.html").render(**context)
    text = _JINJA.get_template("email/weekly_report.txt").render(**context)
    charts = render_weekly_charts(source)
    attachments = tuple(
        InlineAttachment(
            filename=CHART_FILENAMES[content_id],
            content_type="image/png",
            content_id=content_id,
            content=charts[content_id],
        )
        for content_id in (
            SALES_CHART_CID,
            ACQUISITION_CHART_CID,
            COUNTRIES_STOCK_CHART_CID,
        )
    )
    missing_cids = [
        attachment.content_id
        for attachment in attachments
        if f"cid:{attachment.content_id}" not in html
    ]
    if missing_cids:
        raise RuntimeError(
            "Weekly email template omitted inline chart CID(s): "
            + ", ".join(missing_cids)
        )
    return RenderedEmail(
        subject=subject,
        html=html,
        text=text.rstrip() + "\n",
        attachments=attachments,
    )


def _recipients(value: Iterable[str] | str) -> list[str]:
    raw = (value,) if isinstance(value, str) else value
    result = []
    for recipient in raw:
        text = str(recipient or "").strip()
        if not text:
            continue
        if "\r" in text or "\n" in text:
            raise ValueError("Recipient addresses cannot contain line breaks")
        result.append(text)
    if not result:
        raise ValueError("At least one recipient is required")
    return result


def _error_detail(response: Any) -> str:
    try:
        body = response.json()
    except (TypeError, ValueError):
        body = None
    detail = ""
    if isinstance(body, Mapping):
        error = _mapping(body.get("error"))
        detail = str(
            error.get("message")
            or body.get("message")
            or error.get("type")
            or body.get("name")
            or ""
        )
    if not detail:
        detail = str(getattr(response, "text", "") or "")
    detail = " ".join(detail.split())
    return detail[:500]


def send_rendered_email(
    message: RenderedEmail,
    *,
    api_key: str,
    from_address: str,
    recipients: Iterable[str] | str,
    idempotency_key: str,
    session: Any = None,
) -> EmailSendResult:
    """Send a rendered message through Resend's HTTPS API.

    Attachment bytes are base64-encoded exactly once at this provider
    boundary.  Provider errors are raised; this function never reports a send
    unless Resend returns a successful status and an email id.
    """

    if not isinstance(message, RenderedEmail):
        raise TypeError("message must be a RenderedEmail")
    key = str(api_key or "").strip()
    sender = str(from_address or "").strip()
    idem = str(idempotency_key or "").strip()
    if not key:
        raise ValueError("Resend API key is required")
    if not sender:
        raise ValueError("From address is required")
    if any(character in sender for character in "\r\n"):
        raise ValueError("From address cannot contain line breaks")
    if not idem:
        raise ValueError("Idempotency key is required")
    if any(character in idem for character in "\r\n"):
        raise ValueError("Idempotency key cannot contain line breaks")
    to = _recipients(recipients)

    encoded_attachments = []
    for attachment in message.attachments:
        content = attachment.content
        if isinstance(content, (bytearray, memoryview)):
            content = bytes(content)
        if not isinstance(content, bytes):
            raise TypeError(
                f"Attachment {attachment.filename!r} content must be bytes"
            )
        encoded_attachments.append(
            {
                "filename": attachment.filename,
                "content": base64.b64encode(content).decode("ascii"),
                "content_type": attachment.content_type,
                "content_id": attachment.content_id,
            }
        )

    payload = {
        "from": sender,
        "to": to,
        "subject": message.subject,
        "html": message.html,
        "text": message.text,
        "attachments": encoded_attachments,
    }
    client = session or requests
    try:
        response = client.post(
            RESEND_EMAILS_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Idempotency-Key": idem,
            },
            json=payload,
            timeout=RESEND_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise EmailDeliveryError(f"Resend request failed: {exc}") from exc

    status = int(getattr(response, "status_code", 0) or 0)
    if status < 200 or status >= 300:
        detail = _error_detail(response)
        message_text = f"Resend returned HTTP {status}"
        if detail:
            message_text += f": {detail}"
        raise EmailDeliveryError(message_text, status_code=status)
    try:
        body = response.json()
    except (TypeError, ValueError) as exc:
        raise EmailDeliveryError(
            f"Resend returned HTTP {status} but the acknowledgement was not JSON",
            status_code=status,
        ) from exc
    provider_id = body.get("id") if isinstance(body, Mapping) else None
    if not provider_id:
        raise EmailDeliveryError(
            f"Resend returned HTTP {status} without an email id",
            status_code=status,
        )
    return EmailSendResult(provider_id=str(provider_id), status_code=status)


send_weekly_email = send_rendered_email


__all__ = [
    "EmailDeliveryError",
    "EmailSendResult",
    "InlineAttachment",
    "RenderedEmail",
    "render_weekly_email",
    "send_rendered_email",
    "send_weekly_email",
]
