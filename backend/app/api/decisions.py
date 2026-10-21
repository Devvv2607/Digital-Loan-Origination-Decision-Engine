"""Assessment, decision and offer endpoints (US-06, US-07, US-08)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.clock import Clock, get_clock
from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import AppError
from app.core.security import Principal, Role, get_principal, get_settings_dep, require_applicant
from app.engine.policy import load_policy
from app.integrations.registry import Providers, get_providers
from app.schemas.common import error_responses
from app.services import offers as offer_service
from app.services.applications import load_application, next_step
from app.services.assessment import (
    applicant_decision_view,
    assess,
    internal_decision_view,
    latest_decision,
)
from app.services.idempotency import run_idempotent

router = APIRouter(prefix="/applications/{application_id}", tags=["Decision and offer"])
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


class AcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kfs_acknowledged: bool = Field(description='Ticked "I have read the Key Fact Statement"')


class EsignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signature_name: str = Field(min_length=2, max_length=120)


def _respond(result) -> JSONResponse:
    return JSONResponse(status_code=result.status_code, content=result.body,
                        headers={"Idempotent-Replay": "true"} if result.replayed else None)


@router.post("/assess", responses=error_responses(401, 403, 404, 409),
             summary="Run the decision engine: KYC_PENDING -> APPROVED | REFERRED | DECLINED (idempotent)")
def assess_application(
    application_id: uuid.UUID,
    principal: Principal = Depends(require_applicant),
    idempotency_key: IdempotencyKeyHeader = None,
    db: Session = Depends(get_db),
    providers: Providers = Depends(get_providers),
    settings: Settings = Depends(get_settings_dep),
    clock: Clock = Depends(get_clock),
) -> JSONResponse:
    now = clock.now()

    def handler():
        app = load_application(db, application_id, principal, now, for_update=True)
        decision = assess(db, app, providers, settings, now)
        return 200, applicant_decision_view(app, decision)

    return _respond(run_idempotent(db, key=idempotency_key, endpoint="applications.assess",
                                   scope=str(application_id), payload={}, now=now, handler=handler))


@router.get("/decision", responses=error_responses(401, 403, 404),
            summary="Decision: applicant view (owner) or full internal view (ops/admin)")
def get_decision(
    application_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    app = load_application(db, application_id, principal, clock.now())
    decision = latest_decision(db, app)
    if decision is None:
        raise AppError(404, "NOT_FOUND", "No decision has been made on this application yet.")
    if principal.role == Role.APPLICANT:
        return applicant_decision_view(app, decision)
    return internal_decision_view(decision)


@router.get("/offer", responses=error_responses(401, 403, 404),
            summary="KFS-style offer (terms frozen at the decision's policy version)")
def get_offer(
    application_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    app = load_application(db, application_id, principal, clock.now())
    offer = offer_service.get_offer(db, app)
    pricing = load_policy(db, offer.policy_version).pricing
    return {**offer_service.offer_view(offer, pricing.grievance_contact), "application_state": app.state,
            "next_step": _offer_next_step(app, offer)}


OFFER_NEXT_STEP = {"GENERATED": "OFFER", "ACCEPTED": "ESIGN", "ESIGNED": "DISBURSE"}


def _offer_next_step(app, offer) -> str:
    """Within APPROVED, the next step depends on the offer's status."""
    if app.state == "APPROVED":
        return OFFER_NEXT_STEP.get(offer.status, next_step(app))
    return next_step(app)


def _offer_action(db, principal, application_id, now, endpoint, payload, key, action):
    def handler():
        app = load_application(db, application_id, principal, now, for_update=True)
        offer = action(app)
        return 200, {"offer_id": str(offer.id), "status": offer.status, "policy_version": offer.policy_version,
                     "application_state": app.state, "esign_reference": offer.esign_reference,
                     "disbursal_reference": offer.disbursal_reference,
                     "net_disbursed": offer.net_disbursal if offer.disbursed_at else None,
                     "cooling_off_days": offer.cooling_off_days, "next_step": _offer_next_step(app, offer)}

    try:
        return _respond(run_idempotent(db, key=key, endpoint=endpoint, scope=str(application_id),
                                       payload=payload, now=now, handler=handler))
    except AppError as exc:
        # Lazy offer expiry may have changed state before the error; keep that change.
        if exc.error_code == "OFFER_EXPIRED":
            db.commit()
        raise


@router.post("/offer/accept", responses=error_responses(400, 401, 403, 404, 409),
             summary="Accept the offer (requires KFS acknowledgement; idempotent)")
def accept_offer(
    application_id: uuid.UUID,
    body: AcceptRequest,
    principal: Principal = Depends(require_applicant),
    idempotency_key: IdempotencyKeyHeader = None,
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> JSONResponse:
    now = clock.now()
    return _offer_action(db, principal, application_id, now, "offer.accept", body.model_dump(), idempotency_key,
                         lambda app: offer_service.accept(db, app, body.kfs_acknowledged, now))


@router.post("/offer/esign", responses=error_responses(401, 403, 404, 409),
             summary="Mock e-sign of the accepted offer (idempotent)")
def esign_offer(
    application_id: uuid.UUID,
    body: EsignRequest,
    principal: Principal = Depends(require_applicant),
    idempotency_key: IdempotencyKeyHeader = None,
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> JSONResponse:
    now = clock.now()
    return _offer_action(db, principal, application_id, now, "offer.esign", body.model_dump(), idempotency_key,
                         lambda app: offer_service.esign(db, app, body.signature_name, now))


@router.post("/disburse", responses=error_responses(401, 403, 404, 409),
             summary="Mock disbursal after e-sign: APPROVED -> DISBURSED (idempotent)")
def disburse(
    application_id: uuid.UUID,
    principal: Principal = Depends(require_applicant),
    idempotency_key: IdempotencyKeyHeader = None,
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> JSONResponse:
    now = clock.now()
    return _offer_action(db, principal, application_id, now, "offer.disburse", {}, idempotency_key,
                         lambda app: offer_service.disburse(db, app, now))
