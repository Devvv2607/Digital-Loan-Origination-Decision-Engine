"""SQLAlchemy models for every table in the PRD data model (§7), plus idempotency keys.

Timestamps are always set explicitly from the injectable clock (no server defaults),
so tests and the simulation control time.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, tz_datetime, uuid_pk
from app.state_machine.states import AppState, OfferStatus


def _in(column: str, values) -> str:
    return f"{column} IN ({', '.join(repr(str(v)) for v in values)})"


class Applicant(Base):
    __tablename__ = "applicants"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Keyed hash of the phone number; the raw number is never stored.
    phone_hash: Mapped[str] = mapped_column(String(64), unique=True)
    phone_last4: Mapped[str] = mapped_column(String(4))
    created_at: Mapped[datetime] = tz_datetime()

    applications: Mapped[list["Application"]] = relationship(back_populates="applicant")


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (CheckConstraint(_in("state", AppState), name="state_valid"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    applicant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applicants.id"), index=True)
    state: Mapped[str] = mapped_column(String(24), index=True)
    device_id: Mapped[str | None] = mapped_column(String(128), index=True)

    # Applicant-entered details (US-02)
    full_name: Mapped[str | None] = mapped_column(String(120))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    employment_type: Mapped[str | None] = mapped_column(String(16))
    employer_name: Mapped[str | None] = mapped_column(String(120))
    months_in_current_job: Mapped[int | None] = mapped_column(Integer)
    declared_monthly_income: Mapped[int | None] = mapped_column(Integer)
    loan_amount: Mapped[int | None] = mapped_column(Integer)
    tenure_months: Mapped[int | None] = mapped_column(Integer)
    purpose: Mapped[str | None] = mapped_column(String(32))

    # PAN verification (US-03). Synthetic PANs only; never logged unmasked.
    pan: Mapped[str | None] = mapped_column(String(10), index=True)
    pan_status: Mapped[str] = mapped_column(String(32), default="NOT_STARTED")
    pan_name: Mapped[str | None] = mapped_column(String(120))
    pan_dob: Mapped[date | None] = mapped_column(Date)
    pan_name_similarity: Mapped[float | None] = mapped_column(Float)
    pan_name_confirmation: Mapped[str | None] = mapped_column(String(24))

    # e-KYC (US-04)
    kyc_status: Mapped[str] = mapped_column(String(32), default="NOT_STARTED")
    kyc_session_id: Mapped[str | None] = mapped_column(String(64))
    kyc_name: Mapped[str | None] = mapped_column(String(120))
    kyc_dob: Mapped[date | None] = mapped_column(Date)
    kyc_address: Mapped[dict | None] = mapped_column(JSONB)
    # PAN name vs KYC name similarity, kept for fraud check F3 (never shown to the applicant).
    kyc_pan_name_similarity: Mapped[float | None] = mapped_column(Float)

    # Account Aggregator (US-05)
    aa_status: Mapped[str] = mapped_column(String(32), default="NOT_STARTED")
    aa_consent_id: Mapped[str | None] = mapped_column(String(64))
    aa_average_monthly_income: Mapped[int | None] = mapped_column(Integer)
    aa_income_credits: Mapped[list | None] = mapped_column(JSONB)

    policy_version: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = tz_datetime()
    updated_at: Mapped[datetime] = tz_datetime()
    last_activity_at: Mapped[datetime] = tz_datetime()
    state_changed_at: Mapped[datetime] = tz_datetime()

    applicant: Mapped[Applicant] = relationship(back_populates="applications")
    events: Mapped[list["ApplicationEvent"]] = relationship(
        back_populates="application", order_by="ApplicationEvent.seq"
    )


class ApplicationEvent(Base):
    __tablename__ = "application_events"
    __table_args__ = (Index("ix_application_events_app_created", "application_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    # Monotonic per-row sequence: orders events that share a timestamp.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"))
    event_type: Mapped[str] = mapped_column(String(16))
    from_state: Mapped[str | None] = mapped_column(String(24))
    to_state: Mapped[str | None] = mapped_column(String(24))
    actor: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(String(64))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = tz_datetime()

    application: Mapped[Application] = relationship(back_populates="events")


class IntegrationCall(Base):
    __tablename__ = "integration_calls"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    provider: Mapped[str] = mapped_column(String(16))   # pan | kyc | bureau | aa
    operation: Mapped[str] = mapped_column(String(32))
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)   # masked
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # masked
    status: Mapped[str] = mapped_column(String(16))     # SUCCESS | TIMEOUT | INCOMPLETE | ERROR
    latency_ms: Mapped[int] = mapped_column(Integer)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = tz_datetime()


class RuleConfig(Base):
    """Append-only, versioned policy rows. See docs/RULES.md §1."""

    __tablename__ = "rule_configs"
    __table_args__ = (UniqueConstraint("rule_id", "version", name="uq_rule_configs_rule_version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    rule_id: Mapped[str] = mapped_column(String(16), index=True)
    kind: Mapped[str] = mapped_column(String(16))       # ELIGIBILITY | FRAUD | PRICING
    name: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    outcome_on_fail: Mapped[str | None] = mapped_column(String(8))
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    version: Mapped[int] = mapped_column(Integer, index=True)
    created_by: Mapped[str] = mapped_column(String(64))
    change_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = tz_datetime()


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (
        # At most one engine decision and one manual (analyst) decision per application.
        UniqueConstraint("application_id", "source", name="uq_decisions_application_source"),
        CheckConstraint(_in("outcome", ["APPROVED", "REFERRED", "DECLINED"]), name="outcome_valid"),
        CheckConstraint(_in("source", ["ENGINE", "MANUAL"]), name="source_valid"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    source: Mapped[str] = mapped_column(String(8))
    outcome: Mapped[str] = mapped_column(String(16))
    decided_by: Mapped[str] = mapped_column(String(64))
    primary_reason_code: Mapped[str | None] = mapped_column(String(48))
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    explanations: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    rule_results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    inputs_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    policy_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = tz_datetime()


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (CheckConstraint(_in("status", OfferStatus), name="status_valid"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), unique=True
    )
    decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decisions.id"))
    status: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[int] = mapped_column(Integer)

    requested_amount: Mapped[int] = mapped_column(Integer)
    loan_amount: Mapped[int] = mapped_column(Integer)
    tenure_months: Mapped[int] = mapped_column(Integer)
    interest_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    apr: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    emi: Mapped[int] = mapped_column(Integer)
    processing_fee: Mapped[int] = mapped_column(Integer)
    net_disbursal: Mapped[int] = mapped_column(Integer)
    total_interest: Mapped[int] = mapped_column(Integer)
    total_repayment: Mapped[int] = mapped_column(Integer)
    schedule: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    cooling_off_days: Mapped[int] = mapped_column(Integer)

    created_at: Mapped[datetime] = tz_datetime()
    expires_at: Mapped[datetime] = tz_datetime()
    accepted_at: Mapped[datetime | None] = tz_datetime(nullable=True)
    esigned_at: Mapped[datetime | None] = tz_datetime(nullable=True)
    esign_reference: Mapped[str | None] = mapped_column(String(32))
    disbursed_at: Mapped[datetime | None] = tz_datetime(nullable=True)
    disbursal_reference: Mapped[str | None] = mapped_column(String(32))


class ReferralReview(Base):
    __tablename__ = "referral_reviews"
    __table_args__ = (CheckConstraint(_in("action", ["APPROVE", "DECLINE"]), name="action_valid"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), unique=True
    )
    decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decisions.id"))
    reviewer: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(8))
    notes: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = tz_datetime()


class OtpAttempt(Base):
    """One row per OTP issued; tracks wrong attempts and lockout (EC-01, EC-02)."""

    __tablename__ = "otp_attempts"

    id: Mapped[uuid.UUID] = uuid_pk()
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = tz_datetime()
    expires_at: Mapped[datetime] = tz_datetime()
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    verified_at: Mapped[datetime | None] = tz_datetime(nullable=True)
    locked_until: Mapped[datetime | None] = tz_datetime(nullable=True)


class MockProfile(Base):
    """Registered sandbox identities for the mock providers (docs/DECISIONS.md D-17)."""

    __tablename__ = "mock_profiles"

    pan: Mapped[str] = mapped_column(String(10), primary_key=True)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = tz_datetime()
    updated_at: Mapped[datetime] = tz_datetime()


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("key", "endpoint", "scope", name="uq_idempotency_keys_key_endpoint_scope"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(128))
    endpoint: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = tz_datetime()


__all__ = [
    "Applicant",
    "Application",
    "ApplicationEvent",
    "Decision",
    "IdempotencyKey",
    "IntegrationCall",
    "MockProfile",
    "Offer",
    "OtpAttempt",
    "ReferralReview",
    "RuleConfig",
]
