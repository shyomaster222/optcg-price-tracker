"""Persistence and delivery state for one weekly business report run."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.extensions import db


def _utcnow() -> datetime:
    """Return naive UTC, matching the project's existing DateTime columns."""

    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utc_naive(value: datetime | None) -> datetime:
    value = value or _utcnow()
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


class WeeklyReportRun(db.Model):
    """Durable state used to make report generation and delivery resumable.

    ``window_end`` and ``revision`` identify the logical report.  A lease keeps
    two workers from intentionally processing the same row at once, while the
    database uniqueness constraints remain the final concurrency guard.
    """

    __tablename__ = "weekly_report_runs"

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_GENERATED = "generated"
    STATUS_DELIVERING = "delivering"
    STATUS_DELIVERED = "delivered"
    STATUS_DELIVERY_UNKNOWN = "delivery_unknown"
    STATUS_FAILED = "failed"

    id = db.Column(db.Integer, primary_key=True)
    window_end = db.Column(db.Date, nullable=False, index=True)
    revision = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(
        db.String(32),
        nullable=False,
        default=STATUS_PENDING,
        index=True,
    )

    # Worker lease.  Claims should be committed before any remote API work.
    lease_token = db.Column(db.String(128), nullable=True, index=True)
    lease_expires_at = db.Column(db.DateTime, nullable=True, index=True)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)

    # Checkpointed inputs and rendered report allow a retry to resume without
    # silently collecting a different data window.
    snapshot = db.Column(db.JSON, nullable=True)
    report_payload = db.Column(db.JSON, nullable=True)

    # Delivery retries reuse the same key.  A caller must explicitly request a
    # new generation when it intentionally wants a distinct delivery.
    delivery_generation = db.Column(db.Integer, nullable=False, default=0)
    idempotency_key = db.Column(db.String(255), nullable=True, unique=True)
    provider_id = db.Column(db.String(255), nullable=True, index=True)

    # Failure and audit trail.
    error_stage = db.Column(db.String(64), nullable=True)
    last_error = db.Column(db.Text, nullable=True)
    last_error_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
    claimed_at = db.Column(db.DateTime, nullable=True)
    generated_at = db.Column(db.DateTime, nullable=True)
    delivery_started_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    failed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint(
            "window_end",
            "revision",
            name="uq_weekly_report_runs_window_end_revision",
        ),
        db.Index(
            "ix_weekly_report_runs_status_lease",
            "status",
            "lease_expires_at",
        ),
    )

    @property
    def run_key(self) -> str:
        """Stable key for the logical report, independent of delivery retries."""

        end = (
            self.window_end.isoformat()
            if isinstance(self.window_end, date)
            else str(self.window_end)
        )
        return f"weekly-report:{end}:r{self.revision}"

    def lease_is_active(self, now: datetime | None = None) -> bool:
        if not self.lease_token or not self.lease_expires_at:
            return False
        return _utc_naive(self.lease_expires_at) > _utc_naive(now)

    def can_claim(self, *, now: datetime | None = None) -> bool:
        return (
            self.status
            not in {self.STATUS_DELIVERED, self.STATUS_DELIVERY_UNKNOWN}
            and not self.lease_is_active(now=now)
        )

    def claim(
        self,
        lease_token: str,
        *,
        lease_seconds: int = 3600,
        now: datetime | None = None,
    ) -> bool:
        """Claim an already-selected row, or idempotently renew the same claim."""

        if not lease_token:
            raise ValueError("lease_token is required")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")

        claimed_at = _utc_naive(now)
        same_active_claim = (
            self.lease_token == lease_token
            and self.lease_is_active(now=claimed_at)
        )
        if self.lease_is_active(now=claimed_at) and not same_active_claim:
            return False

        if not same_active_claim:
            self.attempt_count = (self.attempt_count or 0) + 1
            self.claimed_at = claimed_at
        self.lease_token = lease_token
        self.lease_expires_at = claimed_at + timedelta(seconds=lease_seconds)
        self.status = self.STATUS_RUNNING
        self.updated_at = claimed_at
        return True

    def renew_lease(
        self,
        lease_token: str,
        *,
        lease_seconds: int = 3600,
        now: datetime | None = None,
    ) -> bool:
        if lease_token != self.lease_token or lease_seconds <= 0:
            return False
        renewed_at = _utc_naive(now)
        self.lease_expires_at = renewed_at + timedelta(seconds=lease_seconds)
        self.updated_at = renewed_at
        return True

    def release_lease(self, lease_token: str | None = None) -> bool:
        if lease_token is not None and lease_token != self.lease_token:
            return False
        self.lease_token = None
        self.lease_expires_at = None
        return True

    def mark_generated(
        self,
        *,
        snapshot: dict | None = None,
        report_payload: dict | None = None,
        now: datetime | None = None,
    ) -> None:
        generated_at = _utc_naive(now)
        if snapshot is not None:
            self.snapshot = snapshot
        if report_payload is not None:
            self.report_payload = report_payload
        self.status = self.STATUS_GENERATED
        self.generated_at = generated_at
        self.updated_at = generated_at
        self.error_stage = None
        self.last_error = None
        self.last_error_at = None
        self.failed_at = None

    def prepare_delivery(
        self,
        *,
        new_generation: bool = False,
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> str:
        """Return the stable provider key to use for this delivery attempt."""

        if self.status == self.STATUS_DELIVERED and not new_generation:
            if not self.idempotency_key:
                raise ValueError("delivered run is missing its idempotency key")
            return self.idempotency_key

        if new_generation or not self.idempotency_key:
            self.delivery_generation = (self.delivery_generation or 0) + 1
            self.idempotency_key = idempotency_key or (
                f"{self.run_key}:delivery:{self.delivery_generation}"
            )
            self.provider_id = None
        elif idempotency_key and idempotency_key != self.idempotency_key:
            raise ValueError(
                "changing an idempotency key requires new_generation=True"
            )

        started_at = _utc_naive(now)
        self.status = self.STATUS_DELIVERING
        self.delivery_started_at = started_at
        self.updated_at = started_at
        return self.idempotency_key

    def mark_delivered(
        self,
        provider_id: str | None,
        *,
        now: datetime | None = None,
    ) -> None:
        delivered_at = _utc_naive(now)
        self.provider_id = provider_id
        self.status = self.STATUS_DELIVERED
        self.delivered_at = delivered_at
        self.updated_at = delivered_at
        self.error_stage = None
        self.last_error = None
        self.last_error_at = None
        self.failed_at = None
        self.release_lease()

    def mark_failed(
        self,
        error: Exception | str,
        *,
        stage: str | None = None,
        now: datetime | None = None,
        delivery_unknown: bool = False,
    ) -> None:
        failed_at = _utc_naive(now)
        self.status = (
            self.STATUS_DELIVERY_UNKNOWN
            if delivery_unknown
            else self.STATUS_FAILED
        )
        self.error_stage = stage
        self.last_error = str(error)
        self.last_error_at = failed_at
        self.failed_at = failed_at
        self.updated_at = failed_at
        self.release_lease()

    def __repr__(self) -> str:
        return (
            f"<WeeklyReportRun window_end={self.window_end} "
            f"revision={self.revision} status={self.status}>"
        )
