"""Assessment (US-06): KYC_PENDING -> UNDER_ASSESSMENT -> APPROVED | REFERRED | DECLINED in one
transaction, so no applicant is ever left in UNDER_ASSESSMENT (DECISIONS.md D-02).
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.engine.decision import (
    EngineResult,
    applicant_reasons,
    evaluate,
    reasons_from_stored,
    reasons_to_store,
)
from app.engine.policy import Policy, load_policy
from app.engine.types import BureauData, DecisionInputs
from app.integrations.registry import Providers
from app.models import Application, Decision
from app.services.applications import next_step
from app.services.offers import create_offer
from app.services.verification import fetch_bureau_report
from app.state_machine.machine import transition
from app.state_machine.states import AppState

OUTCOME_STATE = {"APPROVED": AppState.APPROVED, "REFERRED": AppState.REFERRED, "DECLINED": AppState.DECLINED}


def velocity_counts(db: Session, app: Application, window_hours: int) -> tuple[int, int]:
    """Applications created by the same phone (applicant) / same device in the window up to and
    including this one (F2, DECISIONS.md D-22)."""
    start = app.created_at - timedelta(hours=window_hours)
    base = select(func.count()).select_from(Application).where(
        Application.created_at > start, Application.created_at <= app.created_at
    )
    by_phone = db.scalar(base.where(Application.applicant_id == app.applicant_id)) or 0
    by_device = 0
    if app.device_id:
        by_device = db.scalar(base.where(Application.device_id == app.device_id)) or 0
    return by_phone, by_device


def build_inputs(db: Session, app: Application, bureau: BureauData, policy: Policy, now: datetime) -> DecisionInputs:
    phone, device = velocity_counts(db, app, policy.params("F2").window_hours)
    return DecisionInputs(
        decision_date=now.date(),
        date_of_birth=app.kyc_dob or app.pan_dob or app.date_of_birth,
        employment_type=app.employment_type,
        months_in_current_job=app.months_in_current_job,
        requested_amount=app.loan_amount,
        tenure_months=app.tenure_months,
        declared_income=app.declared_monthly_income,
        aa_status=app.aa_status,
        verified_income=app.aa_average_monthly_income,
        bureau=bureau,
        applications_24h_phone=phone,
        applications_24h_device=device,
        pan_kyc_name_similarity=app.kyc_pan_name_similarity,
        pan_dob=app.pan_dob,
        kyc_dob=app.kyc_dob,
        pan_name_mismatch_confirmed=app.pan_name_confirmation == "KEEP_ENTERED_NAME",
    )


def engine_decision(db: Session, app: Application) -> Decision | None:
    return db.scalar(select(Decision).where(Decision.application_id == app.id, Decision.source == "ENGINE"))


def latest_decision(db: Session, app: Application) -> Decision | None:
    """The decision that currently stands: the analyst's if there is one, else the engine's."""
    return db.scalar(
        select(Decision).where(Decision.application_id == app.id)
        .order_by((Decision.source == "MANUAL").desc(), Decision.created_at.desc()).limit(1)
    )


def assess(db: Session, app: Application, providers: Providers, settings: Settings, now: datetime) -> Decision:
    existing = engine_decision(db, app)
    if existing is not None:
        return existing  # naturally idempotent: never a second decision or offer
    if app.state != AppState.KYC_PENDING or next_step(app) != "ASSESS":
        raise AppError(409, "INVALID_STATE_TRANSITION",
                       "Please complete PAN, e-KYC and the bank-data consent step first.",
                       {"state": app.state, "next_step": next_step(app)})

    policy = load_policy(db)
    transition(db, app, AppState.UNDER_ASSESSMENT, actor="applicant", reason="ASSESSMENT_STARTED", now=now,
               metadata={"policy_version": policy.version})

    outcome = fetch_bureau_report(db, app, providers, settings, now)
    r = outcome.report
    bureau = (
        BureauData(available=True, ntc=r.ntc, score=r.score, existing_monthly_emis=r.existing_monthly_emis,
                   active_loans=r.active_loans, max_dpd_12m=r.max_dpd_12m)
        if r is not None else BureauData(available=False)
    )
    result: EngineResult = evaluate(build_inputs(db, app, bureau, policy, now), policy)

    snapshot = {**result.snapshot, "reasons": reasons_to_store(result.reasons),
                "bureau": {"available": bureau.available, "ntc": bureau.ntc, "score": bureau.score,
                           "existing_monthly_emis": bureau.existing_monthly_emis,
                           "active_loans": bureau.active_loans, "max_dpd_12m": bureau.max_dpd_12m}}
    decision = Decision(
        application_id=app.id,
        source="ENGINE",
        outcome=result.outcome,
        decided_by="engine",
        primary_reason_code=result.primary_reason_code,
        reason_codes=result.reason_codes,
        explanations=result.explanations,
        rule_results=[rr.to_dict() for rr in result.rule_results],
        inputs_snapshot=snapshot,
        policy_version=policy.version,
        created_at=now,
    )
    db.add(decision)
    db.flush()
    app.policy_version = policy.version
    transition(db, app, OUTCOME_STATE[result.outcome], actor="system",
               reason=result.primary_reason_code or result.outcome, now=now,
               metadata={"decision_id": str(decision.id), "policy_version": policy.version})
    if result.outcome == "APPROVED":
        create_offer(db, app, decision, policy, actor="system", now=now)
    return decision


# ---------- views ----------

def applicant_decision_view(app: Application, decision: Decision) -> dict:
    reasons = reasons_from_stored(decision.inputs_snapshot.get("reasons", []))
    visible = applicant_reasons(decision.outcome, reasons)
    primary = decision.primary_reason_code
    if primary and primary.startswith("FRAUD_"):
        primary = None
    return {
        "decision_id": str(decision.id),
        "outcome": decision.outcome,
        "decided_by": "analyst" if decision.source == "MANUAL" else "engine",
        "primary_reason_code": primary if any(v["code"] == primary for v in visible) else None,
        "reasons": visible,
        "policy_version": decision.policy_version,
        "offer_available": app.state == AppState.APPROVED,
        "next_step": next_step(app),
        "created_at": decision.created_at.isoformat(),
    }


def internal_decision_view(decision: Decision) -> dict:
    return {
        "decision_id": str(decision.id),
        "outcome": decision.outcome,
        "source": decision.source,
        "decided_by": decision.decided_by,
        "primary_reason_code": decision.primary_reason_code,
        "reason_codes": decision.reason_codes,
        "explanations": decision.explanations,
        "rule_results": decision.rule_results,
        "policy_version": decision.policy_version,
        "inputs_snapshot": {k: v for k, v in decision.inputs_snapshot.items() if k != "reasons"},
        "created_at": decision.created_at.isoformat(),
    }

