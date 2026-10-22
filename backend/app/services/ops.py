"""Referral queue and analyst review (US-11)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.masking import mask_pan
from app.core.security import Principal
from app.engine.decision import Reason, reasons_from_stored, reasons_to_store
from app.engine.policy import load_policy
from app.engine.reasons import Severity
from app.models import (
    Applicant,
    Application,
    ApplicationEvent,
    Decision,
    IntegrationCall,
    Offer,
    ReferralReview,
)
from app.services.assessment import engine_decision, internal_decision_view
from app.services.offers import create_offer
from app.state_machine.machine import transition
from app.state_machine.states import AppState

MIN_NOTES = 10


def display_name(name: str | None, viewer: Principal | None) -> str | None:
    """Full name for signed-in ops/admin; initials for the public read-only demo (D-19)."""
    if not name or viewer is not None:
        return name
    return " ".join(f"{part[0]}." for part in name.split() if part)


def _phone_masked(db: Session, app: Application) -> str:
    last4 = db.scalar(select(Applicant.phone_last4).where(Applicant.id == app.applicant_id))
    return f"******{last4}" if last4 else "******"


def queue(
    db: Session, viewer: Principal | None, now: datetime, page: int, page_size: int, reason_code: str | None
) -> dict[str, Any]:
    base = (
        select(Application, Decision)
        .join(Decision, (Decision.application_id == Application.id) & (Decision.source == "ENGINE"))
        .where(Application.state == AppState.REFERRED.value)
    )
    if reason_code:
        base = base.where(Decision.reason_codes.contains([reason_code]))
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.execute(
        base.order_by(Application.state_changed_at.asc(), Application.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    items = []
    for app, decision in rows:
        codes = decision.reason_codes
        items.append({
            "application_id": str(app.id),
            "applicant_name": display_name(app.full_name, viewer),
            "phone_masked": _phone_masked(db, app),
            "pan_masked": mask_pan(app.pan),
            "primary_reason_code": decision.primary_reason_code,
            "reason_codes": codes,
            "income_unverified": "DATA_INCOME_UNVERIFIED" in codes,
            "fraud_signal": any(c.startswith("FRAUD_") for c in codes),
            "requested_amount": app.loan_amount,
            "referred_at": app.state_changed_at.isoformat(),
            "hours_in_queue": round((now - app.state_changed_at).total_seconds() / 3600, 1),
        })
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def _load(db: Session, application_id: uuid.UUID, *, for_update: bool = False) -> Application:
    stmt = select(Application).where(Application.id == application_id)
    if for_update:
        stmt = stmt.with_for_update()
    app = db.scalar(stmt)
    if app is None:
        raise AppError(404, "NOT_FOUND", "Application not found.")
    return app


def detail(db: Session, application_id: uuid.UUID, viewer: Principal | None) -> dict[str, Any]:
    app = _load(db, application_id)
    decision = engine_decision(db, app)
    if decision is None:
        raise AppError(404, "NOT_FOUND", "This application has not been assessed.")
    calls = db.scalars(
        select(IntegrationCall).where(IntegrationCall.application_id == app.id).order_by(IntegrationCall.created_at,
                                                                                         IntegrationCall.attempt)
    ).all()
    events = db.scalars(
        select(ApplicationEvent).where(ApplicationEvent.application_id == app.id).order_by(ApplicationEvent.seq)
    ).all()
    review = db.scalar(select(ReferralReview).where(ReferralReview.application_id == app.id))
    offer = db.scalar(select(Offer).where(Offer.application_id == app.id))
    return {
        "application": {
            "id": str(app.id),
            "state": app.state,
            "is_seeded": app.is_seeded,
            "applicant_name": display_name(app.full_name, viewer),
            "phone_masked": _phone_masked(db, app),
            "pan_masked": mask_pan(app.pan),
            "details": {
                "employment_type": app.employment_type,
                "employer_name": app.employer_name if viewer else None,
                "months_in_current_job": app.months_in_current_job,
                "declared_monthly_income": app.declared_monthly_income,
                "loan_amount": app.loan_amount,
                "tenure_months": app.tenure_months,
                "purpose": app.purpose,
            },
            "verification": {
                "pan_status": app.pan_status,
                "pan_name_confirmation": app.pan_name_confirmation,
                "kyc_status": app.kyc_status,
                "kyc_pan_name_similarity": app.kyc_pan_name_similarity,
                "aa_status": app.aa_status,
                "aa_average_monthly_income": app.aa_average_monthly_income,
            },
        },
        "decision": internal_decision_view(decision),
        "integration_results": [
            {"provider": c.provider, "operation": c.operation, "status": c.status, "attempt": c.attempt,
             "latency_ms": c.latency_ms, "response": c.response, "created_at": c.created_at.isoformat()}
            for c in calls
        ],
        "timeline": [
            {"event_type": e.event_type, "from_state": e.from_state, "to_state": e.to_state, "actor": e.actor,
             "reason": e.reason, "created_at": e.created_at.isoformat()}
            for e in events
        ],
        "review": (
            {"reviewer": review.reviewer, "action": review.action, "notes": review.notes,
             "created_at": review.created_at.isoformat()} if review else None
        ),
        "offer_id": str(offer.id) if offer else None,
    }


def review(
    db: Session, application_id: uuid.UUID, action: str, notes: str, reviewer: Principal, now: datetime
) -> dict[str, Any]:
    notes = notes.strip()
    if len(notes) < MIN_NOTES:
        raise AppError(422, "VALIDATION_ERROR", "Please explain your decision in the notes.",
                       {"fields": [{"field": "notes", "message": f"At least {MIN_NOTES} characters."}]})
    app = _load(db, application_id, for_update=True)
    existing = db.scalar(select(ReferralReview).where(ReferralReview.application_id == app.id))
    if existing is not None:
        raise AppError(409, "ALREADY_REVIEWED", "This referral has already been reviewed.",
                       {"reviewer": existing.reviewer, "action": existing.action})
    if app.state != AppState.REFERRED:
        raise AppError(409, "INVALID_STATE_TRANSITION", "Only referred applications can be reviewed.",
                       {"state": app.state})
    engine = engine_decision(db, app)
    policy = load_policy(db, engine.policy_version)  # the analyst decides under the decision-time policy

    snapshot = dict(engine.inputs_snapshot)
    if "offer_amount" not in snapshot:
        # The engine stopped early (bureau unavailable): price the requested amount at the fallback rate (D-38).
        snapshot.update(offer_amount=app.loan_amount, requested_amount=app.loan_amount,
                        tenure_months=app.tenure_months,
                        annual_rate=str(Decimal(str(policy.pricing.fallback_rate))))
    kept: list[Reason] = [r for r in reasons_from_stored(snapshot.get("reasons", [])) if r.severity == Severity.INFO]
    snapshot["reasons"] = reasons_to_store(kept)
    snapshot["analyst_notes"] = notes
    snapshot["engine_decision_id"] = str(engine.id)

    outcome = "APPROVED" if action == "APPROVE" else "DECLINED"
    decision = Decision(
        application_id=app.id, source="MANUAL", outcome=outcome, decided_by=reviewer.actor,
        primary_reason_code=kept[0].code if (kept and outcome == "APPROVED") else None,
        reason_codes=[r.code for r in kept] if outcome == "APPROVED" else [],
        explanations={"ANALYST": notes}, rule_results=engine.rule_results, inputs_snapshot=snapshot,
        policy_version=engine.policy_version, created_at=now,
    )
    db.add(decision)
    db.flush()
    rv = ReferralReview(application_id=app.id, decision_id=decision.id, reviewer=reviewer.actor, action=action,
                        notes=notes, created_at=now)
    db.add(rv)
    db.flush()
    transition(db, app, AppState.APPROVED if outcome == "APPROVED" else AppState.DECLINED, actor=reviewer.actor,
               reason=f"ANALYST_{outcome}", now=now,
               metadata={"review_id": str(rv.id), "decision_id": str(decision.id)})
    offer = create_offer(db, app, decision, policy, actor=reviewer.actor, now=now) if outcome == "APPROVED" else None
    return {"application_id": str(app.id), "state": app.state, "review_id": str(rv.id),
            "decision_id": str(decision.id), "offer_id": str(offer.id) if offer else None,
            "policy_version": engine.policy_version}
