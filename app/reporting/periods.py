"""Reporting-window calculations for the Friday RCJ business pulse."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ReportWindow:
    """All sales windows use inclusive starts and exclusive ends."""

    timezone: str
    report_date: date
    current_start: datetime
    current_end: datetime
    previous_start: datetime
    previous_end: datetime
    four_week_start: datetime
    trend_start: datetime
    month_start: datetime
    month_end: datetime
    prior_month_matched_start: datetime
    prior_month_matched_end: datetime
    last_full_month_start: datetime
    last_full_month_end: datetime
    velocity_start: datetime
    slow_stock_start: datetime
    fetch_start: datetime

    def to_dict(self) -> dict:
        values = asdict(self)
        for key, value in list(values.items()):
            if isinstance(value, (date, datetime)):
                values[key] = value.isoformat()
        return values


def _month_start(value: datetime) -> datetime:
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _previous_month_start(value: datetime) -> datetime:
    current = _month_start(value)
    return (current - timedelta(days=1)).replace(day=1)


def _parse_report_date(value: date | str | None, now: datetime) -> date:
    if isinstance(value, str):
        value = date.fromisoformat(value)
    if value is not None:
        if value.weekday() != 4:
            raise ValueError("window end must be a Friday (YYYY-MM-DD)")
        return value

    today = now.date()
    return today - timedelta(days=(today.weekday() - 4) % 7)


def build_report_window(
    window_end: date | str | None = None,
    *,
    now: datetime | None = None,
    timezone: str = "Asia/Hong_Kong",
) -> ReportWindow:
    """Build the completed Friday-through-Thursday sales windows.

    ``window_end`` is the Friday at 00:00 that closes the report.  When omitted,
    the most recent Friday in the configured timezone is used.
    """

    tz = ZoneInfo(timezone)
    current_now = now.astimezone(tz) if now else datetime.now(tz)
    report_date = _parse_report_date(window_end, current_now)
    current_end = datetime.combine(report_date, time.min, tzinfo=tz)
    current_start = current_end - timedelta(days=7)
    previous_end = current_start
    previous_start = previous_end - timedelta(days=7)
    four_week_start = current_start - timedelta(days=28)
    trend_start = current_end - timedelta(weeks=8)

    month_start = _month_start(current_end)
    month_end = current_end
    prior_start = _previous_month_start(current_end)
    elapsed_days = max((month_end.date() - month_start.date()).days, 0)
    next_month_after_prior = month_start
    prior_matched_end = min(
        prior_start + timedelta(days=elapsed_days),
        next_month_after_prior,
    )

    velocity_start = current_end - timedelta(days=28)
    slow_stock_start = current_end - timedelta(days=90)
    fetch_start = min(
        trend_start,
        prior_start,
        velocity_start,
        slow_stock_start,
    )

    return ReportWindow(
        timezone=timezone,
        report_date=report_date,
        current_start=current_start,
        current_end=current_end,
        previous_start=previous_start,
        previous_end=previous_end,
        four_week_start=four_week_start,
        trend_start=trend_start,
        month_start=month_start,
        month_end=month_end,
        prior_month_matched_start=prior_start,
        prior_month_matched_end=prior_matched_end,
        last_full_month_start=prior_start,
        last_full_month_end=month_start,
        velocity_start=velocity_start,
        slow_stock_start=slow_stock_start,
        fetch_start=fetch_start,
    )
