"""KFS-style offer lifecycle inside APPROVED: GENERATED -> ACCEPTED -> ESIGNED, then mock
disbursal moves the application to DISBURSED (US-07, US-08, EC-15).

Offer terms are frozen at generation under the decision's policy version; later policy
changes never re-price an existing offer.
"""

import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.engine.policy import Policy
from app.engine.pricing import ASSUMPTIONS, quote
from app.models import Application, Decision, Offer
from app.state_machine.machine import check_offer_transition, record_event, transition
from app.state_machine.states import AppState, EventType, OfferStatus

KFS_DISCLAIMER = (
    "Simulated KFS-style disclosure for demonstration; not a legally compliant disclosure or a real offer."
)


def create_offer(db: Session, app: Application, decision: Decision, policy: Policy, actor: str, now: datetime) -> Offer:
    """Price the decision's recommended amount at its rate, under the decision's policy version."""
    if policy.version != decision.policy_version:
        raise ValueError("Offer must be priced under the decision's policy version")
    snap = decision.inputs_snapshot
    pricing = policy.pricing
    q = quote(int(snap["offer_amount"]), Decimal(snap["annual_rate"]), int(snap["tenure_months"]),
              pricing.processing_fee_rate)
    offer = Offer(
        application_id=app.id,
        decision_id=decision.id,
        status=OfferStatus.GENERATED.value,
        policy_version=decision.policy_version,
        requested_amount=int(snap["requested_amount"]),
        loan_amount=q.loan_amount,
        tenure_months=q.tenure_months,
        interest_rate=q.annual_rate,
        apr=q.apr,
        emi=q.emi,
        processing_fee=q.processing_fee,
        net_disbursal=q.net_disbursal,
        total_interest=q.total_interest,
        total_repayment=q.total_repayment,
        schedule=[row.to_dict() for row in q.schedule],
        cooling_off_days=pricing.cooling_off_days,
        created_at=now,
        expires_at=now + timedelta(days=pricing.offer_validity_days),
    )
    db.add(offer)
    db.flush()
    record_event(db, app, event_type=EventType.OFFER_STATUS, from_state=None, to_state=OfferStatus.GENERATED.value,
                 actor=actor, reason="OFFER_GENERATED", metadata={"offer_id": str(offer.id)}, now=now)
    return offer


def get_offer(db: Session, app: Application, *, for_update: bool = False) -> Offer:
    stmt = select(Offer).where(Offer.application_id == app.id)
    if for_update:
        stmt = stmt.with_for_update()
    offer = db.scalar(stmt)
    if offer is None:
        raise AppError(404, "NOT_FOUND", "There is no offer for this application.")
    return offer


def _guard_open(app: Application, offer: Offer) -> None:
    if offer.status == OfferStatus.EXPIRED or app.state == AppState.EXPIRED:
        raise AppError(409, "OFFER_EXPIRED", "This offer has expired. Please start a new application.",
                       {"expired_at": offer.expires_at.isoformat()})
    if app.state != AppState.APPROVED:
        raise AppError(409, "INVALID_STATE_TRANSITION", "This offer can no longer be changed.", {"state": app.state})


def _move(db: Session, app: Application, offer: Offer, to: OfferStatus, reason: str, now: datetime) -> None:
    check_offer_transition(offer.status, to)
    record_event(db, app, event_type=EventType.OFFER_STATUS, from_state=offer.status, to_state=to.value,
                 actor="applicant", reason=reason, metadata={"offer_id": str(offer.id)}, now=now)
    offer.status = to.value
    app.last_activity_at = now
    app.updated_at = now


def accept(db: Session, app: Application, kfs_acknowledged: bool, now: datetime) -> Offer:
    offer = get_offer(db, app, for_update=True)
    _guard_open(app, offer)
    if offer.status in (OfferStatus.ACCEPTED, OfferStatus.ESIGNED):
        return offer  # already accepted: no second event
    if not kfs_acknowledged:
        raise AppError(400, "KFS_NOT_ACKNOWLEDGED", "Please confirm you have read the Key Fact Statement.")
    _move(db, app, offer, OfferStatus.ACCEPTED, "OFFER_ACCEPTED", now)
    offer.accepted_at = now
    return offer


def esign(db: Session, app: Application, signature_name: str, now: datetime) -> Offer:
    offer = get_offer(db, app, for_update=True)
    _guard_open(app, offer)
    if offer.status == OfferStatus.ESIGNED:
        return offer
    if offer.status != OfferStatus.ACCEPTED:
        raise AppError(409, "INVALID_STATE_TRANSITION", "Please accept the offer before signing.",
                       {"offer_status": offer.status})
    _move(db, app, offer, OfferStatus.ESIGNED, "MOCK_ESIGN", now)
    offer.esigned_at = now
    offer.esign_reference = f"MOCK-ESIGN-{secrets.token_hex(3).upper()}"
    return offer


def disburse(db: Session, app: Application, now: datetime) -> Offer:
    offer = get_offer(db, app, for_update=True)
    if app.state == AppState.DISBURSED:
        return offer
    if offer.status != OfferStatus.ESIGNED:
        _guard_open(app, offer)
        raise AppError(409, "INVALID_STATE_TRANSITION", "The loan agreement must be signed before disbursal.",
                       {"offer_status": offer.status})
    offer.disbursed_at = now
    offer.disbursal_reference = f"MOCK-DISB-{secrets.token_hex(3).upper()}"
    transition(db, app, AppState.DISBURSED, actor="system", reason="MOCK_DISBURSAL_OK", now=now,
               metadata={"offer_id": str(offer.id), "disbursal_reference": offer.disbursal_reference})
    return offer


def offer_view(offer: Offer, grievance_contact: str) -> dict:
    return {
        "offer_id": str(offer.id),
        "status": offer.status,
        "policy_version": offer.policy_version,
        "requested_amount": offer.requested_amount,
        "loan_amount": offer.loan_amount,
        "amount_capped": offer.loan_amount < offer.requested_amount,
        "net_disbursal": offer.net_disbursal,
        "tenure_months": offer.tenure_months,
        "interest_rate": float(round(Decimal(offer.interest_rate), 2)),
        "apr": float(round(Decimal(offer.apr), 2)),
        "emi": offer.emi,
        "total_interest": offer.total_interest,
        "total_fees": offer.processing_fee,
        "total_cost": offer.total_interest + offer.processing_fee,
        "total_repayment": offer.total_repayment,
        "schedule": offer.schedule,
        "cooling_off_days": offer.cooling_off_days,
        "grievance_contact": grievance_contact,
        "assumptions": ASSUMPTIONS,
        "disclaimer": KFS_DISCLAIMER,
        "created_at": offer.created_at.isoformat(),
        "expires_at": offer.expires_at.isoformat(),
        "accepted_at": offer.accepted_at.isoformat() if offer.accepted_at else None,
        "esigned_at": offer.esigned_at.isoformat() if offer.esigned_at else None,
        "esign_reference": offer.esign_reference,
        "disbursed_at": offer.disbursed_at.isoformat() if offer.disbursed_at else None,
        "disbursal_reference": offer.disbursal_reference,
    }


def decision_for(db: Session, offer: Offer) -> Decision:
    return db.get(Decision, offer.decision_id)
