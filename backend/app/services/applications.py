"""Application lifecycle for the applicant journey (US-02, US-09)."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.masking import mask_pan
from app.core.security import Principal, Role
from app.engine.policy import load_policy
from app.models import Application, ApplicationEvent, Offer
from app.schemas.applications import (
    DETAIL_FIELDS,
    ApplicationDetails,
    ApplicationDetailsPatch,
    ApplicationView,
    KycSummary,
    MyApplication,
    MyApplications,
    PanSummary,
    ResumableApplication,
    StatusSummary,
    TimelineEvent,
)
from app.services.expiry import ABANDONABLE_STATES, expire_if_due
from app.state_machine.machine import InvalidTransitionError, record_creation, transition
from app.state_machine.states import AppState

REQUIRED_FOR_SUBMIT = DETAIL_FIELDS
# Within APPROVED, the next step depends on the offer's status.
OFFER_NEXT_STEP = {"GENERATED": "OFFER", "ACCEPTED": "ESIGN", "ESIGNED": "DISBURSE"}


def _not_found() -> AppError:
    # The same answer whether the application doesn't exist or belongs to someone else,
    # so an applicant can't learn that another applicant's application ID exists.
    return AppError(404, "NOT_FOUND", "Application not found.")


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
    """Load an application the principal may access, applying any due expiry first.

    Applicants can only reach their own applications; anyone else's is a 404, never a 403.
    Ops and admin can reach every application.
    """
    stmt = select(Application).where(Application.id == application_id)
    if principal.role == Role.APPLICANT:
        stmt = stmt.where(Application.applicant_id == principal.applicant_id)
    if for_update:
        stmt = stmt.with_for_update()
    application = db.scalar(stmt)
    if application is None:
        raise _not_found()
    if expire_if_due(db, application, now):
        db.commit()
    return application


def ensure_access(db: Session, application_id: uuid.UUID, principal: Principal) -> None:
    """Ownership check with no side effects. Idempotent endpoints call this before looking up a
    stored response, so a replayed key can never return another applicant's response."""
    if principal.role != Role.APPLICANT:
        return
    owner = db.scalar(select(Application.applicant_id).where(Application.id == application_id))
    if owner != principal.applicant_id:
        raise _not_found()


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
    errors = []
    dob = changes.get("date_of_birth")
    if dob is not None and (dob >= now.date() or dob.year < 1900):
        errors.append({"field": "date_of_birth", "message": "Enter a valid date of birth in the past."})
    if changes.get("loan_amount") is not None or changes.get("tenure_months") is not None:
        pricing = load_policy(db).pricing
        amount, tenure = changes.get("loan_amount"), changes.get("tenure_months")
        if amount is not None and not pricing.loan_amount_min <= amount <= pricing.loan_amount_max:
            errors.append({"field": "loan_amount", "message":
                           f"Choose an amount between {pricing.loan_amount_min} and {pricing.loan_amount_max}."})
        if tenure is not None and not pricing.tenure_months_min <= tenure <= pricing.tenure_months_max:
            errors.append({"field": "tenure_months", "message":
                           f"Choose a tenure between {pricing.tenure_months_min} and {pricing.tenure_months_max} months."})
    if errors:
        raise AppError(422, "VALIDATION_ERROR", "Some fields need attention.", {"fields": errors})
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


def kyc_on_file(db: Session, applicant_id: uuid.UUID) -> bool:
    return db.scalar(
        select(Application.id)
        .where(Application.applicant_id == applicant_id, Application.kyc_status == "COMPLETE")
        .limit(1)
    ) is not None


def my_applications(db: Session, applicant_id: uuid.UUID, now: datetime) -> MyApplications:
    """US-09 enhancement: every application of this applicant, with its status and next step."""
    apps = db.scalars(
        select(Application)
        .where(Application.applicant_id == applicant_id)
        .order_by(Application.last_activity_at.desc(), Application.created_at.desc())
    ).all()
    if any(expire_if_due(db, app, now) for app in apps):
        db.commit()
    offer_status = dict(
        db.execute(select(Offer.application_id, Offer.status).where(Offer.application_id.in_([a.id for a in apps])))
        .all()
    ) if apps else {}
    items = []
    for app in apps:
        step = next_step(app)
        if app.state == AppState.APPROVED:
            step = OFFER_NEXT_STEP.get(offer_status.get(app.id, ""), step)
        items.append(
            MyApplication(
                id=app.id, state=app.state, next_step=step, loan_amount=app.loan_amount,
                tenure_months=app.tenure_months, purpose=app.purpose,
                kyc_reused=app.kyc_reused_from_application_id is not None,
                created_at=app.created_at, last_activity_at=app.last_activity_at,
            )
        )
    return MyApplications(items=items, kyc_on_file=kyc_on_file(db, applicant_id))


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
        kyc=KycSummary(status=application.kyc_status,
                       reused=application.kyc_reused_from_application_id is not None),
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
