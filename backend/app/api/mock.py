"""`/mock/*` — the four simulated providers, exposed for inspection in Swagger.

The backend calls the same mock code in-process through adapters; these routes just
make the behaviour visible. Every call is logged to integration_calls (PAN masked).
"""

import re
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.clock import Clock, get_clock
from app.core.db import get_db
from app.core.errors import AppError
from app.core.masking import mask_pan
from app.core.rate_limit import rate_limit
from app.core.security import Principal, require_admin
from app.integrations.base import PAN_FORMAT, ProviderTimeout
from app.integrations.calls import logged_call
from app.integrations.mock.profiles import MockProfileIn
from app.integrations.registry import MockProfileStore, Providers, get_providers
from app.schemas.common import error_responses

TAG = "Mock providers (simulated)"
router = APIRouter(prefix="/mock", tags=[TAG], dependencies=[Depends(rate_limit("mock"))])

PanField = Field(min_length=10, max_length=10, examples=["ZZZPZ1234Q"])


def _pan(raw: str) -> str:
    pan = raw.strip().upper()
    if not re.fullmatch(PAN_FORMAT, pan):
        raise AppError(422, "PAN_FORMAT_INVALID", "PAN must look like ABCDE1234F.")
    return pan


def _timeout(provider: str) -> AppError:
    return AppError(504, "PROVIDER_TIMEOUT", f"The simulated {provider} provider timed out.")


def _masked(result_dict: dict, pan: str) -> dict:
    return {"pan": mask_pan(pan), **result_dict}


class PanBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pan: str = PanField


class KycCompleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kyc_session_id: str = Field(min_length=1, max_length=64)
    pan: str = PanField
    otp: str = Field(pattern=r"^\d{6}$")


class AaConsentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pan: str = PanField
    purpose: str = Field(default="LOAN_UNDERWRITING", max_length=40)
    months: int = Field(default=6, ge=1, le=24)


class AaDecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pan: str = PanField
    decision: Literal["APPROVE", "DECLINE"]


@router.post("/pan/verify", summary="Mock PAN verification", responses=error_responses(422, 429))
def mock_pan(body: PanBody, db: Session = Depends(get_db), providers: Providers = Depends(get_providers),
             clock: Clock = Depends(get_clock)) -> dict:
    pan = _pan(body.pan)
    result = logged_call(db, provider="pan", operation="verify", request={"pan": pan, "channel": "mock_api"},
                         fn=lambda: providers.pan.verify(pan), now=clock.now())
    db.commit()
    return _masked(result.to_dict(), pan)


@router.post("/kyc/start", summary="Mock e-KYC start (returns a simulated OTP)", responses=error_responses(422, 429))
def mock_kyc_start(body: PanBody, db: Session = Depends(get_db), providers: Providers = Depends(get_providers),
                   clock: Clock = Depends(get_clock)) -> dict:
    pan = _pan(body.pan)
    result = logged_call(db, provider="kyc", operation="start", request={"pan": pan, "channel": "mock_api"},
                         fn=lambda: providers.kyc.start(pan), now=clock.now())
    db.commit()
    return {"kyc_session_id": result.session_id, "status": result.status, "demo_kyc_otp": result.demo_otp}


@router.post("/kyc/complete", summary="Mock e-KYC completion", responses=error_responses(422, 429, 504))
def mock_kyc_complete(body: KycCompleteBody, db: Session = Depends(get_db),
                      providers: Providers = Depends(get_providers), clock: Clock = Depends(get_clock)) -> dict:
    pan = _pan(body.pan)
    try:
        result = logged_call(
            db, provider="kyc", operation="complete",
            request={"pan": pan, "kyc_session_id": body.kyc_session_id, "channel": "mock_api"},
            fn=lambda: providers.kyc.complete(body.kyc_session_id, pan, body.otp), now=clock.now(),
        )
    except ProviderTimeout:
        db.commit()
        raise _timeout("e-KYC") from None
    db.commit()
    return result.to_dict()


@router.post("/bureau/report", summary="Mock credit bureau report", responses=error_responses(422, 429, 504))
def mock_bureau(body: PanBody, db: Session = Depends(get_db), providers: Providers = Depends(get_providers),
                clock: Clock = Depends(get_clock)) -> dict:
    pan = _pan(body.pan)
    try:
        result = logged_call(db, provider="bureau", operation="report", request={"pan": pan, "channel": "mock_api"},
                             fn=lambda: providers.bureau.report(pan), now=clock.now())
    except ProviderTimeout:
        db.commit()
        raise _timeout("credit bureau") from None
    db.commit()
    return _masked(result.to_dict(), pan)


@router.post("/aa/consent", summary="Mock Account Aggregator: create consent", responses=error_responses(422, 429))
def mock_aa_consent(body: AaConsentBody, db: Session = Depends(get_db),
                    providers: Providers = Depends(get_providers), clock: Clock = Depends(get_clock)) -> dict:
    pan = _pan(body.pan)
    result = logged_call(
        db, provider="aa", operation="consent_create",
        request={"pan": pan, "purpose": body.purpose, "months": body.months, "channel": "mock_api"},
        fn=lambda: providers.aa.create_consent(pan, body.purpose, body.months), now=clock.now(),
    )
    db.commit()
    return result.to_dict()


@router.post("/aa/consent/{consent_id}/decision", summary="Mock Account Aggregator: approve or decline consent",
             responses=error_responses(422, 429))
def mock_aa_decision(consent_id: str, body: AaDecisionBody, db: Session = Depends(get_db),
                     providers: Providers = Depends(get_providers), clock: Clock = Depends(get_clock)) -> dict:
    pan = _pan(body.pan)
    result = logged_call(
        db, provider="aa", operation="consent_decision",
        request={"pan": pan, "consent_id": consent_id, "decision": body.decision, "channel": "mock_api"},
        fn=lambda: providers.aa.decide(consent_id, pan, body.decision), now=clock.now(),
    )
    db.commit()
    return result.to_dict()


@router.put("/profiles/{pan}", summary="Register a deterministic sandbox identity (admin)",
            responses=error_responses(401, 403, 422, 429))
def put_profile(pan: str, body: MockProfileIn, principal: Principal = Depends(require_admin),
                db: Session = Depends(get_db), clock: Clock = Depends(get_clock)) -> dict:
    pan = _pan(pan)
    MockProfileStore(db).upsert(pan, body.model_dump(mode="json"), principal.actor, clock.now())
    db.commit()
    return {"pan": mask_pan(pan), "registered": True}
