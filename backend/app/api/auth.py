from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.clock import Clock, get_clock
from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import AppError
from app.core.rate_limit import rate_limit
from app.core.security import Role, check_internal_credentials, create_token, get_settings_dep
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    OtpSendRequest,
    OtpSendResponse,
    OtpVerifyRequest,
    OtpVerifyResponse,
)
from app.schemas.common import error_responses
from app.services import otp as otp_service
from app.services.applications import resumable_applications

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/otp/send",
    response_model=OtpSendResponse,
    dependencies=[Depends(rate_limit("otp_send"))],
    responses=error_responses(422, 423, 429),
    summary="Send a (simulated) OTP to a mobile number",
)
def send_otp(
    body: OtpSendRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    clock: Clock = Depends(get_clock),
) -> OtpSendResponse:
    issued = otp_service.send_otp(db, settings, body.phone, clock.now())
    response = OtpSendResponse(
        otp_request_id=issued.otp.id,
        expires_at=issued.otp.expires_at,
        resends_remaining_this_hour=issued.sends_remaining,
    )
    if settings.demo_mode:
        response.demo_otp = issued.code
        response.demo_notice = "Simulated OTP — no SMS sent."
    return response


@router.post(
    "/otp/verify",
    response_model=OtpVerifyResponse,
    dependencies=[Depends(rate_limit("otp_verify"))],
    responses=error_responses(400, 422, 423, 429),
    summary="Verify the OTP and get an applicant session",
)
def verify_otp(
    body: OtpVerifyRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    clock: Clock = Depends(get_clock),
) -> OtpVerifyResponse:
    now = clock.now()
    applicant = otp_service.verify_otp(db, settings, body.phone, body.otp, now)
    return OtpVerifyResponse(
        access_token=create_token(settings, clock, str(applicant.id), Role.APPLICANT),
        applicant_id=applicant.id,
        resumable_applications=resumable_applications(db, applicant.id, now),
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    dependencies=[Depends(rate_limit("login"))],
    responses=error_responses(401, 422, 429),
    summary="Ops/admin login (credentials from environment variables)",
)
def login(
    body: LoginRequest,
    settings: Settings = Depends(get_settings_dep),
    clock: Clock = Depends(get_clock),
) -> LoginResponse:
    role = check_internal_credentials(settings, body.username, body.password)
    if role is None:
        raise AppError(401, "UNAUTHENTICATED", "Incorrect username or password.")
    return LoginResponse(
        access_token=create_token(settings, clock, body.username, role),
        role=role.value,
        expires_in=settings.jwt_ttl_minutes * 60,
    )
