"""Application lifecycle for the applicant journey (US-02, US-09)."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.masking import mask_pan
from app.core.security import Principal, Role
from app.models import Application, ApplicationEvent
from app.schemas.applications import (
    DETAIL_FIELDS,
    ApplicationDetails,
    ApplicationDetailsPatch,
    ApplicationView,
    PanSummary,
    ResumableApplication,
    StatusSummary,
    TimelineEvent,
)
from app.services.expiry import ABANDONABLE_STATES, expire_if_due
from app.state_machine.machine import InvalidTransitionError, record_creation, transition
from app.state_machine.states import AppState

REQUIRED_FOR_SUBMIT = DETAIL_FIELDS


def touch(application: Application, now: datetime) -> None:
    """Record applicant activity (resets the 30-day abandonment clock)."""
    application.last_activity_at = now
    application.updated_at = now


def create_application(
    db: Session, applicant_id: uuid.UUID, device_id: str | None, now: datetime
) -> Application:
    application = Application(
        applicant_id=applicant_id,
        state=AppState.DRAFT.value,
        device_id=device_id,
        pan_status="NOT_STARTED",
        kyc_status="NOT_STARTED",
        aa_status="NOT_STARTED",
        created_at=now,
        updated_at=now,
        last_activity_at=now,
        state_changed_at=now,
    )
    db.add(application)
    db.flush()
    record_creation(db, application, actor="applicant", now=now)
    db.commit()
    return application


def load_application(
    db: Session,
    application_id: uuid.UUID,
    principal: Principal,
    now: datetime,
    *,
    for_update: bool = False,
) -> Application:
    """Load an application the principal may access, applying any due expiry first."""
    stmt = select(Application).where(Application.id == application_id)
    if for_update:
        stmt = stmt.with_for_update()
    application = db.scalar(stmt)
    if application is None:
        raise AppError(404, "NOT_FOUND", "Application not found.")
    if principal.role == Role.APPLICANT and application.applicant_id != principal.applicant_id:
        raise AppError(403, "FORBIDDEN", "You don't have access to this application.")
    if expire_if_due(db, application, now):
        db.commit()
    return application


def next_step(application: Application) -> str:
    state = AppState(application.state)
    if state == AppState.DRAFT:
        missing = [f for f in REQUIRED_FOR_SUBMIT if getattr(application, f) is None]
        return "DETAILS" if missing else "SUBMIT"
    if state == AppState.KYC_PENDING:
        if application.pan_status != "VERIFIED":
            return "PAN"
        if application.kyc_status != "COMPLETE":
            return "EKYC"
        if application.aa_status not in ("APPROVED", "DECLINED"):
            return "AA_CONSENT"
        return "ASSESS"
    return {
        AppState.UNDER_ASSESSMENT: "ASSESS",
        AppState.APPROVED: "OFFER",
        AppState.REFERRED: "UNDER_REVIEW",
        AppState.DECLINED: "DECISION",
        AppState.DISBURSED: "DONE",
        AppState.EXPIRED: "START_NEW",
    }[state]


def update_details(
    db: Session, application: Application, patch: ApplicationDetailsPatch, now: datetime
) -> Application:
    if application.state != AppState.DRAFT:
        raise AppError(
            409,
            "INVALID_STATE_TRANSITION",
            "Details can't be changed after the application is submitted.",
            {"state": application.state},
        )
    changes = patch.model_dump(exclude_unset=True)
    if "date_of_birth" in changes and changes["date_of_birth"] is not None:
        dob = changes["date_of_birth"]
        if dob >= now.date() or dob.year < 1900:
            raise AppError(
                422,
                "VALIDATION_ERROR",
                "Some fields need attention.",
                {"fields": [{"field": "date_of_birth", "message": "Enter a valid date of birth in the past."}]},
            )
    for field, value in changes.items():
        setattr(application, field, value.value if hasattr(value, "value") else value)
    touch(application, now)
    db.commit()
    return application


def submit(db: Session, application: Application, now: datetime) -> Application:
    """DRAFT -> KYC_PENDING. Naturally idempotent: re-submitting a submitted application is a no-op."""
    if application.state == AppState.KYC_PENDING:
        return application
    if application.state != AppState.DRAFT:
        raise InvalidTransitionError(application.state, AppState.KYC_PENDING)
    missing = [f for f in REQUIRED_FOR_SUBMIT if getattr(application, f) is None]
    if missing:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "Please complete all required details before submitting.",
            {"missing_fields": missing},
        )
    touch(application, now)
    transition(db, application, AppState.KYC_PENDING, actor="applicant", reason="SUBMITTED", now=now)
    return application


def resumable_applications(
    db: Session, applicant_id: uuid.UUID, now: datetime
) -> list[ResumableApplication]:
    apps = db.scalars(
        select(Application)
        .where(Application.applicant_id == applicant_id, Application.state.in_(ABANDONABLE_STATES))
        .order_by(Application.last_activity_at.desc())
    ).all()
    result = []
    changed = False
    for app in apps:
        if expire_if_due(db, app, now):
            changed = True
            continue
        result.append(
            ResumableApplication(
                id=app.id, state=app.state, next_step=next_step(app), last_activity_at=app.last_activity_at
            )
        )
    if changed:
        db.commit()
    return result


def to_view(db: Session, application: Application) -> ApplicationView:
    events = db.scalars(
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == application.id)
        .order_by(ApplicationEvent.seq)
    ).all()
    return ApplicationView(
        id=application.id,
        state=application.state,
        next_step=next_step(application),
        details=ApplicationDetails(**{f: getattr(application, f) for f in DETAIL_FIELDS}),
        pan=PanSummary(masked=mask_pan(application.pan), status=application.pan_status),
        kyc=StatusSummary(status=application.kyc_status),
        aa=StatusSummary(status=application.aa_status),
        policy_version=application.policy_version,
        created_at=application.created_at,
        last_activity_at=application.last_activity_at,
        timeline=[
            TimelineEvent(
                event_type=e.event_type,
                from_state=e.from_state,
                to_state=e.to_state,
                actor=e.actor,
                reason=e.reason,
                created_at=e.created_at,
            )
            for e in events
        ],
    )
