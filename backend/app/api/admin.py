from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import Clock, get_clock
from app.core.db import get_db
from app.core.security import Principal, require_admin, require_internal_read
from app.engine.policy import ALL_RULE_IDS, OUTCOME_EDITABLE, RuleView, load_policy, update_rule
from app.models import RuleConfig
from app.schemas.common import error_responses
from app.services.demo_reset import reset_demo_data
from app.services.expiry import run_expiry_job

router = APIRouter(prefix="/admin", tags=["Admin"])


class ExpiryJobResponse(BaseModel):
    expired_abandoned: int
    expired_offers: int


@router.post(
    "/jobs/expire",
    response_model=ExpiryJobResponse,
    responses=error_responses(401, 403),
    summary="Apply 30-day abandonment and 7-day offer expiry rules",
)
def expire_job(
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> ExpiryJobResponse:
    result = run_expiry_job(db, clock.now())
    return ExpiryJobResponse(expired_abandoned=result.expired_abandoned, expired_offers=result.expired_offers)


@router.post("/demo/reset", responses=error_responses(401, 403),
             summary="Reset demo data: restore policy version 1 and, on the deployed demo, the 500 seeded applications")
def demo_reset(
    request: Request,
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    settings = request.app.state.settings
    result = reset_demo_data(db, clock.now(), pii_hash_key=settings.pii_hash_key if settings.demo_seed else None)
    request.app.state.rate_limiter.reset()
    return result


# ---------------------------------------------------------------- policy (US-10)

def _rule_dict(r: RuleView) -> dict[str, Any]:
    return {
        "rule_id": r.rule_id, "kind": r.kind, "name": r.name, "enabled": r.enabled,
        "parameters": r.parameters, "outcome_on_fail": r.outcome_on_fail,
        "outcome_editable": r.rule_id in OUTCOME_EDITABLE, "reason_codes": r.reason_codes,
        "version": r.version, "updated_by": r.created_by, "change_comment": r.change_comment,
        "updated_at": r.created_at.isoformat(),
    }


@router.get("/rules", responses=error_responses(401, 403), summary="Current policy (read-only in demo mode)")
def get_rules(
    viewer: Principal | None = Depends(require_internal_read),
    db: Session = Depends(get_db),
) -> dict:
    policy = load_policy(db)
    order = {rid: n for n, rid in enumerate(ALL_RULE_IDS)}
    rules = sorted(policy.rules.values(), key=lambda r: order[r.rule_id])
    return {"policy_version": policy.version, "read_only": viewer is None or viewer.role != "admin",
            "rules": [_rule_dict(r) for r in rules]}


class RuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    parameters: dict[str, Any] | None = None
    outcome_on_fail: Literal["DECLINE", "REFER"] | None = None
    change_comment: str = Field(min_length=3, max_length=500)


@router.put("/rules/{rule_id}", responses=error_responses(401, 403, 404, 422),
            summary="Edit a rule: creates a new policy version (admin)")
def put_rule(
    rule_id: str,
    body: RuleUpdate,
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    row, previous = update_rule(
        db, rule_id.upper(), enabled=body.enabled, parameters=body.parameters,
        outcome_on_fail=body.outcome_on_fail, change_comment=body.change_comment,
        actor=principal.actor, now=clock.now(),
    )
    return {"rule_id": row.rule_id, "version": row.version, "policy_version": row.version,
            "previous_version": previous, "rule": _rule_dict(row)}


@router.get("/rules/versions", responses=error_responses(401, 403),
            summary="Version history of rule changes, newest first (paginated)")
def rule_versions(
    rule_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: Principal | None = Depends(require_internal_read),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(RuleConfig)
    count = select(func.count()).select_from(RuleConfig)
    if rule_id:
        stmt = stmt.where(RuleConfig.rule_id == rule_id.upper())
        count = count.where(RuleConfig.rule_id == rule_id.upper())
    rows = db.scalars(
        stmt.order_by(RuleConfig.version.desc(), RuleConfig.rule_id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [
            {"policy_version": r.version, "rule_id": r.rule_id, "name": r.name, "enabled": r.enabled,
             "parameters": r.parameters, "outcome_on_fail": r.outcome_on_fail, "changed_by": r.created_by,
             "change_comment": r.change_comment, "created_at": r.created_at.isoformat()}
            for r in rows
        ],
        "page": page, "page_size": page_size, "total": db.scalar(count),
    }
