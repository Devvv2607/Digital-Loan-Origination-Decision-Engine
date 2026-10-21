import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.clock import Clock, get_clock
from app.core.config import Settings
from app.core.db import get_db
from app.core.security import Principal, get_settings_dep, require_applicant
from app.integrations.registry import Providers, get_providers
from app.schemas.common import error_responses
from app.schemas.verification import (
    AaConsentRequest,
    AaConsentResponse,
    KycCompleteRequest,
    KycCompleteResponse,
    KycStartResponse,
    PanVerifyRequest,
    PanVerifyResponse,
)
from app.services import verification
from app.services.applications import load_application

router = APIRouter(prefix="/applications/{application_id}", tags=["Applicant verification"])


@router.post(
    "/pan/verify",
    response_model=PanVerifyResponse,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Verify PAN (format check, duplicate check F1, name match EC-04)",
)
def verify_pan(
    application_id: uuid.UUID,
    body: PanVerifyRequest,
    principal: Principal = Depends(require_applicant),
    db: Session = Depends(get_db),
    providers: Providers = Depends(get_providers),
    clock: Clock = Depends(get_clock),
) -> PanVerifyResponse:
    now = clock.now()
    app = load_application(db, application_id, principal, now, for_update=True)
    return verification.verify_pan(db, app, body.pan, body.name_confirmation, providers, now)


@router.post(
    "/kyc/start",
    response_model=KycStartResponse,
    responses=error_responses(401, 403, 404, 409),
    summary="Start e-KYC (simulated OTP)",
)
def start_kyc(
    application_id: uuid.UUID,
    principal: Principal = Depends(require_applicant),
    db: Session = Depends(get_db),
    providers: Providers = Depends(get_providers),
    settings: Settings = Depends(get_settings_dep),
    clock: Clock = Depends(get_clock),
) -> KycStartResponse:
    now = clock.now()
    app = load_application(db, application_id, principal, now, for_update=True)
    return verification.start_kyc(db, app, providers, settings, now)


@router.post(
    "/kyc/complete",
    response_model=KycCompleteResponse,
    responses={202: {"model": KycCompleteResponse, "description": "Provider timed out after retries (EC-05)"},
               **error_responses(400, 401, 403, 404, 409, 422)},
    summary="Complete e-KYC (retries on timeout; EC-05, EC-06)",
)
def complete_kyc(
    application_id: uuid.UUID,
    body: KycCompleteRequest,
    principal: Principal = Depends(require_applicant),
    db: Session = Depends(get_db),
    providers: Providers = Depends(get_providers),
    settings: Settings = Depends(get_settings_dep),
    clock: Clock = Depends(get_clock),
) -> JSONResponse:
    now = clock.now()
    app = load_application(db, application_id, principal, now, for_update=True)
    status, response = verification.complete_kyc(
        db, app, body.kyc_session_id, body.otp, providers, settings, now
    )
    return JSONResponse(status_code=status, content=response.model_dump(mode="json"))


@router.post(
    "/aa/consent",
    response_model=AaConsentResponse,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Record Account Aggregator consent (approve fetches 6 months of income)",
)
def aa_consent(
    application_id: uuid.UUID,
    body: AaConsentRequest,
    principal: Principal = Depends(require_applicant),
    db: Session = Depends(get_db),
    providers: Providers = Depends(get_providers),
    clock: Clock = Depends(get_clock),
) -> AaConsentResponse:
    now = clock.now()
    app = load_application(db, application_id, principal, now, for_update=True)
    return verification.record_aa_consent(db, app, body.decision, providers, now)
