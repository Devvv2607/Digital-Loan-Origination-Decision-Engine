from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.clock import Clock, get_clock
from app.core.db import get_db
from app.core.security import Principal, require_admin
from app.schemas.common import error_responses
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
