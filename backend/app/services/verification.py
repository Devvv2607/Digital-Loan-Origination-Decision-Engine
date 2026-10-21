"""Pre-assessment verification while the application is KYC_PENDING:
PAN (US-03), e-KYC (US-04) and Account Aggregator consent (US-05).

Every provider call is logged to integration_calls; every outcome leaves the
application in KYC_PENDING with a clear status, never a crash.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.core.masking import mask_pan
from app.core.names import NAME_SIMILARITY_MIN, display_name, name_similarity
from app.engine.fraud import f1_duplicate_pan
from app.integrations.base import PAN_FORMAT, BureauReport, ProviderError, ProviderTimeout
from app.integrations.calls import call_with_retries, logged_call
from app.integrations.registry import Providers
from app.models import Application
from app.schemas.verification import (
    AaConsentResponse,
    KycCompleteResponse,
    KycStartResponse,
    PanVerifyResponse,
)
from app.services.applications import next_step, touch
from app.state_machine.machine import record_event
from app.state_machine.states import AppState, EventType

logger = logging.getLogger(__name__)

AA_MONTHS = 6
AA_PURPOSE = "LOAN_UNDERWRITING"


def _require_kyc_pending(application: Application) -> None:
    if application.state != AppState.KYC_PENDING:
        raise AppError(
            409,
            "INVALID_STATE_TRANSITION",
            "This step isn't available at the current stage of your application.",
            {"state": application.state},
        )


def _step_error(message: str, **details) -> AppError:
    return AppError(409, "INVALID_STATE_TRANSITION", message, details)


# ---------------------------------------------------------------- PAN

def normalize_pan(raw: str) -> str:
    return re.sub(r"\s+", "", raw).upper()


def _pan_response(app: Application, status: str, **extra) -> PanVerifyResponse:
    return PanVerifyResponse(status=status, pan_masked=mask_pan(app.pan), next_step=next_step(app), **extra)


def _confirmation_needed(app: Application) -> PanVerifyResponse:
    return _pan_response(
        app,
        "NAME_CONFIRMATION_REQUIRED",
        name_on_pan=app.pan_name,
        name_entered=app.full_name,
        options=["USE_PAN_NAME", "KEEP_ENTERED_NAME"],
        message="The name on your PAN looks different. Which is your legal name?",
    )


def _apply_name_confirmation(app: Application, choice: str) -> None:
    if choice == "USE_PAN_NAME":
        app.full_name = display_name(app.pan_name or "")
    app.pan_name_confirmation = choice
    app.pan_status = "VERIFIED"


def verify_pan(
    db: Session,
    app: Application,
    raw_pan: str,
    name_confirmation: str | None,
    providers: Providers,
    now: datetime,
) -> PanVerifyResponse:
    _require_kyc_pending(app)
    pan = normalize_pan(raw_pan)

    # EC-03: format checked before anything else; no provider call, no log row.
    if not re.fullmatch(PAN_FORMAT, pan):
        raise AppError(
            422,
            "PAN_FORMAT_INVALID",
            "Enter PAN as 5 letters, 4 digits, then 1 letter (e.g. ABCDE1234F).",
            {"fields": [{"field": "pan", "message": "Invalid PAN format"}]},
        )

    if app.pan_status == "VERIFIED":
        if pan != app.pan:
            raise _step_error("Your PAN is already verified for this application.")
        return _pan_response(app, "VERIFIED", name_on_pan=app.pan_name)

    # Waiting for the applicant's answer to a name mismatch (EC-04): no new provider call.
    if app.pan_status == "NAME_CONFIRMATION_REQUIRED" and pan == app.pan:
        if name_confirmation is None:
            return _confirmation_needed(app)
        _apply_name_confirmation(app, name_confirmation)
        touch(app, now)
        db.commit()
        return _pan_response(app, "VERIFIED", name_on_pan=app.pan_name)

    # Serialise concurrent verifications of the same PAN so the duplicate check is reliable.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"pan:{pan}"})

    # EC-11 / F1: another active application already holds this PAN.
    if f1_duplicate_pan.find_active_duplicate(db, pan, app.id) is not None:
        record_event(
            db,
            app,
            event_type=EventType.FRAUD_CHECK,
            actor="system",
            reason=f1_duplicate_pan.REASON_CODE,
            metadata={"check": f1_duplicate_pan.RULE_ID, "pan": mask_pan(pan)},
            now=now,
        )
        touch(app, now)
        db.commit()
        logger.info("F1 duplicate PAN blocked for application %s (%s)", app.id, mask_pan(pan))
        raise AppError(
            409,
            "APPLICATION_ALREADY_IN_PROGRESS",
            "An application with these details is already in progress. Please continue that application.",
        )

    try:
        result = logged_call(
            db, provider="pan", operation="verify", request={"pan": pan},
            fn=lambda: providers.pan.verify(pan), now=now, application_id=app.id,
        )
    except (ProviderTimeout, ProviderError):
        touch(app, now)
        db.commit()
        return _pan_response(app, "UNAVAILABLE", message="We couldn't reach the PAN service. Please try again.")

    touch(app, now)
    if result.status != "VALID":
        app.pan_status = "INVALID"
        db.commit()
        return _pan_response(app, "INVALID", message="We couldn't verify this PAN. Please check and try again.")

    app.pan = pan
    app.pan_name = result.name
    app.pan_dob = result.date_of_birth
    app.pan_name_similarity = name_similarity(app.full_name, result.name)
    app.pan_name_confirmation = None

    if app.pan_name_similarity >= NAME_SIMILARITY_MIN:
        app.pan_status = "VERIFIED"
        db.commit()
        return _pan_response(app, "VERIFIED", name_on_pan=app.pan_name)

    app.pan_status = "NAME_CONFIRMATION_REQUIRED"
    if name_confirmation is not None:
        _apply_name_confirmation(app, name_confirmation)
        db.commit()
        return _pan_response(app, "VERIFIED", name_on_pan=app.pan_name)
    db.commit()
    return _confirmation_needed(app)


# ---------------------------------------------------------------- e-KYC

def start_kyc(db: Session, app: Application, providers: Providers, settings: Settings, now: datetime) -> KycStartResponse:
    _require_kyc_pending(app)
    if app.pan_status != "VERIFIED":
        raise _step_error("Please verify your PAN first.")
    if app.kyc_status == "COMPLETE":
        raise _step_error("e-KYC is already complete.")

    pan = app.pan or ""
    result = logged_call(
        db, provider="kyc", operation="start", request={"pan": pan},
        fn=lambda: providers.kyc.start(pan), now=now, application_id=app.id,
    )
    app.kyc_session_id = result.session_id
    app.kyc_status = "OTP_SENT"
    touch(app, now)
    db.commit()

    response = KycStartResponse(kyc_session_id=result.session_id, status="OTP_SENT")
    if settings.demo_mode:
        response.demo_kyc_otp = result.demo_otp
        response.demo_notice = "Simulated e-KYC — no real identity data is used."
    return response


def complete_kyc(
    db: Session,
    app: Application,
    session_id: str,
    otp: str,
    providers: Providers,
    settings: Settings,
    now: datetime,
) -> tuple[int, KycCompleteResponse]:
    _require_kyc_pending(app)
    if app.kyc_status not in ("OTP_SENT", "DELAYED") or session_id != app.kyc_session_id:
        raise _step_error("This e-KYC session isn't active. Please start e-KYC again.")

    pan = app.pan or ""
    touch(app, now)
    try:
        result = call_with_retries(
            db,
            backoff_ms=settings.provider_retry_backoff_ms,
            provider="kyc",
            operation="complete",
            request={"pan": pan, "kyc_session_id": session_id},
            fn=lambda: providers.kyc.complete(session_id, pan, otp),
            now=now,
            application_id=app.id,
        )
    except ProviderTimeout:
        # EC-05: retried twice; stay in KYC_PENDING and let the applicant come back.
        app.kyc_status = "DELAYED"
        record_event(
            db, app, event_type=EventType.NOTE, actor="system", reason="KYC_PROVIDER_TIMEOUT",
            metadata={"attempts": 3}, now=now,
        )
        db.commit()
        return 202, KycCompleteResponse(
            status="DELAYED",
            message="We're having trouble reaching the verification service. We'll notify you when you can continue.",
            state=app.state,
            next_step=next_step(app),
        )

    if result.status == "OTP_INVALID":
        db.commit()  # keep the call log
        raise AppError(400, "KYC_OTP_INVALID", "That e-KYC code isn't right. Please try again.")

    if result.status == "INCOMPLETE":
        # EC-06: ask for a fresh e-KYC attempt.
        app.kyc_status = "INCOMPLETE"
        app.kyc_session_id = None
        db.commit()
        return 200, KycCompleteResponse(
            status="INCOMPLETE",
            message="We couldn't complete e-KYC. Please try again.",
            state=app.state,
            next_step=next_step(app),
        )

    app.kyc_status = "COMPLETE"
    app.kyc_name = result.name
    app.kyc_dob = result.date_of_birth
    app.kyc_address = result.address
    app.kyc_pan_name_similarity = name_similarity(app.pan_name, result.name)
    db.commit()
    return 200, KycCompleteResponse(status="COMPLETE", state=app.state, next_step=next_step(app))


# ---------------------------------------------------------------- Account Aggregator

def record_aa_consent(
    db: Session, app: Application, decision: str, providers: Providers, now: datetime
) -> AaConsentResponse:
    _require_kyc_pending(app)
    if app.kyc_status != "COMPLETE":
        raise _step_error("Please complete e-KYC first.")

    wanted = "APPROVED" if decision == "APPROVE" else "DECLINED"
    if app.aa_status in ("APPROVED", "DECLINED"):
        if app.aa_status != wanted:
            raise _step_error("Your consent choice is already recorded for this application.", aa_status=app.aa_status)
        return _aa_response(app)

    pan = app.pan or ""
    consent = logged_call(
        db, provider="aa", operation="consent_create",
        request={"pan": pan, "purpose": AA_PURPOSE, "months": AA_MONTHS},
        fn=lambda: providers.aa.create_consent(pan, AA_PURPOSE, AA_MONTHS), now=now, application_id=app.id,
    )
    result = logged_call(
        db, provider="aa", operation="consent_decision",
        request={"pan": pan, "consent_id": consent.consent_id, "decision": decision},
        fn=lambda: providers.aa.decide(consent.consent_id, pan, decision), now=now, application_id=app.id,
    )
    app.aa_consent_id = consent.consent_id
    app.aa_status = result.status
    if result.status == "APPROVED":
        app.aa_average_monthly_income = result.average_monthly_income
        app.aa_income_credits = result.income_credits
    touch(app, now)
    db.commit()
    return _aa_response(app)


def _aa_response(app: Application) -> AaConsentResponse:
    if app.aa_status == "APPROVED":
        return AaConsentResponse(
            consent_id=app.aa_consent_id or "",
            status="APPROVED",
            months_of_data=len(app.aa_income_credits or []),
            average_monthly_income=app.aa_average_monthly_income,
            next_step=next_step(app),
        )
    return AaConsentResponse(
        consent_id=app.aa_consent_id or "",
        status="DECLINED",
        notice="We'll use the income you declared. Your application will need a manual review.",
        next_step=next_step(app),
    )


# ---------------------------------------------------------------- Credit bureau

@dataclass
class BureauOutcome:
    report: BureauReport | None  # None = unavailable after retries (EC-07 -> SYS_BUREAU_UNAVAILABLE)


def fetch_bureau_report(
    db: Session, app: Application, providers: Providers, settings: Settings, now: datetime
) -> BureauOutcome:
    """Called by the assessment step (Phase 3). Retries timeouts twice; never raises for them."""
    pan = app.pan or ""
    try:
        report = call_with_retries(
            db,
            backoff_ms=settings.provider_retry_backoff_ms,
            provider="bureau",
            operation="report",
            request={"pan": pan},
            fn=lambda: providers.bureau.report(pan),
            now=now,
            application_id=app.id,
        )
    except (ProviderTimeout, ProviderError):
        return BureauOutcome(report=None)
    return BureauOutcome(report=report)
