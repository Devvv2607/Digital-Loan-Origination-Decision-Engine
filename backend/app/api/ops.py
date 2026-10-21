"""Ops referral queue (US-11) and PM metrics (US-12)."""

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.clock import Clock, get_clock
from app.core.db import get_db
from app.core.security import Principal, require_internal_read, require_ops_or_admin
from app.schemas.common import error_responses
from app.services import metrics, ops
from app.services.idempotency import run_idempotent

router = APIRouter(tags=["Ops"])


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["APPROVE", "DECLINE"]
    notes: str = Field(max_length=2000)


@router.get("/ops/referrals", responses=error_responses(401, 403),
            summary="Referred applications, oldest first (paginated; read-only in demo mode)")
def list_referrals(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    reason_code: str | None = None,
    viewer: Principal | None = Depends(require_internal_read),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return ops.queue(db, viewer, clock.now(), page, page_size, reason_code)


@router.get("/ops/referrals/{application_id}", responses=error_responses(401, 403, 404),
            summary="Referral detail: reason codes, inputs, masked integration results, timeline")
def referral_detail(
    application_id: uuid.UUID,
    viewer: Principal | None = Depends(require_internal_read),
    db: Session = Depends(get_db),
) -> dict:
    return ops.detail(db, application_id, viewer)


@router.post("/ops/referrals/{application_id}/review", responses=error_responses(401, 403, 404, 409, 422),
             summary="Approve or decline a referral with notes (ops/admin; idempotent)")
def review_referral(
    application_id: uuid.UUID,
    body: ReviewRequest,
    principal: Principal = Depends(require_ops_or_admin),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> JSONResponse:
    now = clock.now()
    result = run_idempotent(
        db, key=idempotency_key, endpoint="ops.review", scope=str(application_id), payload=body.model_dump(), now=now,
        handler=lambda: (200, ops.review(db, application_id, body.action, body.notes, principal, now)),
    )
    return JSONResponse(status_code=result.status_code, content=result.body,
                        headers={"Idempotent-Replay": "true"} if result.replayed else None)


@router.get("/metrics/funnel", tags=["Metrics"], responses=error_responses(401, 403),
            summary="Funnel, conversion, decision mix, referral and fraud-flag rates, top reason codes")
def funnel(
    frm: date | None = Query(None, alias="from"),
    to: date | None = None,
    _: Principal | None = Depends(require_internal_read),
    db: Session = Depends(get_db),
) -> dict:
    return metrics.funnel(db, frm, to)


@router.get("/metrics/tat", tags=["Metrics"], responses=error_responses(401, 403),
            summary="Median and P90 time in each state, from the event log")
def tat(
    frm: date | None = Query(None, alias="from"),
    to: date | None = None,
    _: Principal | None = Depends(require_internal_read),
    db: Session = Depends(get_db),
) -> dict:
    return metrics.tat(db, frm, to)
