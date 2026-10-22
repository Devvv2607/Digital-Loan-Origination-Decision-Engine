import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__
from app.core.db import get_db
from app.core.errors import error_body
from app.models import RuleConfig

router = APIRouter(tags=["Health"])
logger = logging.getLogger(__name__)


@router.get("/ping", operation_id="ping", summary="Liveness only (no database); for uptime monitors")
@router.head("/ping", operation_id="ping_head", summary="Liveness only (no database); HEAD for uptime monitors")
def ping() -> dict:
    # Deliberately no database access and no rate limit: an external monitor can keep the API
    # awake without keeping the (scale-to-zero) database compute running. Use /health for a full check.
    return {"status": "ok"}


@router.get("/health", summary="Liveness and database connectivity")
def health(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        db.execute(text("SELECT 1"))
        policy_version = db.scalar(select(func.max(RuleConfig.version)))
    except SQLAlchemyError as exc:
        logger.error("Health check: database unreachable (%s)", type(exc).__name__)
        return JSONResponse(
            status_code=503,
            content=error_body(
                "DEPENDENCY_UNAVAILABLE",
                "The service is temporarily unavailable.",
                {"status": "degraded", "database": "unreachable"},
            ),
        )
    clock = request.app.state.clock
    return JSONResponse({
        "status": "ok", "database": "ok", "version": __version__, "policy_version": policy_version,
        "clock": {"kind": clock.kind, "now": clock.now().isoformat()},
    })
