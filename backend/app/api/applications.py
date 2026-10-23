import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.clock import Clock, get_clock
from app.core.db import get_db
from app.core.rate_limit import rate_limit
from app.core.security import Principal, require_applicant
from app.schemas.applications import (
    ApplicationCreated,
    ApplicationDetailsPatch,
    ApplicationView,
    MyApplications,
    SubmitResponse,
)
from app.schemas.common import error_responses
from app.services import applications as app_service
from app.services.idempotency import run_idempotent

router = APIRouter(prefix="/applications", tags=["Applications"])

IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.post(
    "",
    status_code=201,
    response_model=ApplicationCreated,
    dependencies=[Depends(rate_limit("app_create"))],
    responses=error_responses(401, 403, 429),
    summary="Start a new application (DRAFT)",
)
def create_application(
    principal: Principal = Depends(require_applicant),
    device_id: Annotated[str | None, Header(alias="X-Device-Id", max_length=128)] = None,
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> ApplicationCreated:
    app = app_service.create_application(db, principal.applicant_id, device_id, clock.now())
    return ApplicationCreated(
        id=app.id, state=app.state, next_step=app_service.next_step(app), created_at=app.created_at
    )


@router.get(
    "",
    response_model=MyApplications,
    responses=error_responses(401, 403),
    summary="My applications: your own applications with status and next step",
)
def list_my_applications(
    principal: Principal = Depends(require_applicant),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> MyApplications:
    return app_service.my_applications(db, principal.applicant_id, clock.now())


@router.get(
    "/{application_id}",
    response_model=ApplicationView,
    responses=error_responses(401, 403, 404),
    summary="Get an application with its timeline (used to resume)",
)
def get_application(
    application_id: uuid.UUID,
    principal: Principal = Depends(require_applicant),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> ApplicationView:
    app = app_service.load_application(db, application_id, principal, clock.now())
    return app_service.to_view(db, app)


@router.patch(
    "/{application_id}",
    response_model=ApplicationView,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Save applicant details (DRAFT only)",
)
def patch_application(
    application_id: uuid.UUID,
    body: ApplicationDetailsPatch,
    principal: Principal = Depends(require_applicant),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> ApplicationView:
    now = clock.now()
    app = app_service.load_application(db, application_id, principal, now, for_update=True)
    app_service.update_details(db, app, body, now)
    return app_service.to_view(db, app)


@router.post(
    "/{application_id}/submit",
    response_model=SubmitResponse,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Submit details: DRAFT -> KYC_PENDING (idempotent)",
)
def submit_application(
    application_id: uuid.UUID,
    principal: Principal = Depends(require_applicant),
    idempotency_key: IdempotencyKeyHeader = None,
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> JSONResponse:
    now = clock.now()
    app_service.ensure_access(db, application_id, principal)

    def handler() -> tuple[int, dict]:
        app = app_service.load_application(db, application_id, principal, now, for_update=True)
        app_service.submit(db, app, now)
        body = SubmitResponse(id=app.id, state=app.state, next_step=app_service.next_step(app))
        return 200, body.model_dump(mode="json")

    result = run_idempotent(
        db,
        key=idempotency_key,
        endpoint="applications.submit",
        scope=str(application_id),
        payload={},
        now=now,
        handler=handler,
    )
    return JSONResponse(
        status_code=result.status_code,
        content=result.body,
        headers={"Idempotent-Replay": "true"} if result.replayed else None,
    )
