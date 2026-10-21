"""Expiry rules (docs/STATE_MACHINE.md §5).

- DRAFT / KYC_PENDING with no activity for 30 days -> EXPIRED (EC-14).
- APPROVED with an offer not e-signed by expires_at -> offer EXPIRED, application EXPIRED (EC-15).

Applied lazily whenever an application is loaded, and in bulk by the expiry job.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import product
from app.models import Application, Offer
from app.state_machine.machine import check_offer_transition, record_event, transition
from app.state_machine.states import AppState, EventType, OfferStatus

ABANDONABLE_STATES = (AppState.DRAFT, AppState.KYC_PENDING)
OPEN_OFFER_STATUSES = (OfferStatus.GENERATED, OfferStatus.ACCEPTED)

REASON_ABANDONED = "ABANDONED_30D"
REASON_OFFER_EXPIRED = "OFFER_EXPIRED_7D"


def is_abandoned(application: Application, now: datetime) -> bool:
    return (
        application.state in ABANDONABLE_STATES
        and now - application.last_activity_at >= product.ABANDONMENT_PERIOD
    )


def expire_offer_if_due(db: Session, application: Application, offer: Offer | None, now: datetime) -> bool:
    if (
        application.state != AppState.APPROVED
        or offer is None
        or offer.status not in OPEN_OFFER_STATUSES
        or now < offer.expires_at
    ):
        return False
    check_offer_transition(offer.status, OfferStatus.EXPIRED)
    record_event(
        db,
        application,
        event_type=EventType.OFFER_STATUS,
        from_state=offer.status,
        to_state=OfferStatus.EXPIRED.value,
        actor="system",
        reason=REASON_OFFER_EXPIRED,
        metadata={"offer_id": str(offer.id)},
        now=now,
    )
    offer.status = OfferStatus.EXPIRED.value
    transition(db, application, AppState.EXPIRED, actor="system", reason=REASON_OFFER_EXPIRED, now=now)
    return True


def expire_if_due(db: Session, application: Application, now: datetime) -> bool:
    """Apply whichever expiry rule is due. Caller commits."""
    if is_abandoned(application, now):
        transition(db, application, AppState.EXPIRED, actor="system", reason=REASON_ABANDONED, now=now)
        return True
    if application.state == AppState.APPROVED:
        offer = db.scalar(select(Offer).where(Offer.application_id == application.id).with_for_update())
        return expire_offer_if_due(db, application, offer, now)
    return False


@dataclass
class ExpiryJobResult:
    expired_abandoned: int
    expired_offers: int


def run_expiry_job(db: Session, now: datetime) -> ExpiryJobResult:
    cutoff = now - product.ABANDONMENT_PERIOD
    abandoned = db.scalars(
        select(Application)
        .where(Application.state.in_(ABANDONABLE_STATES), Application.last_activity_at <= cutoff)
        .with_for_update(skip_locked=True)
    ).all()
    for app in abandoned:
        transition(db, app, AppState.EXPIRED, actor="system", reason=REASON_ABANDONED, now=now)

    due_offers = db.execute(
        select(Application, Offer)
        .join(Offer, Offer.application_id == Application.id)
        .where(
            Application.state == AppState.APPROVED,
            or_(*(Offer.status == s for s in OPEN_OFFER_STATUSES)),
            Offer.expires_at <= now,
        )
        .with_for_update(skip_locked=True)
    ).all()
    expired_offers = sum(expire_offer_if_due(db, app, offer, now) for app, offer in due_offers)

    db.commit()
    return ExpiryJobResult(expired_abandoned=len(abandoned), expired_offers=expired_offers)
