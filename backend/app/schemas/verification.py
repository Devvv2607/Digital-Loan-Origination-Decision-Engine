from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PanVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pan: str = Field(min_length=1, max_length=20, examples=["ZZZPZ1234Q"])
    name_confirmation: Literal["USE_PAN_NAME", "KEEP_ENTERED_NAME"] | None = None


class PanVerifyResponse(BaseModel):
    status: Literal["VERIFIED", "NAME_CONFIRMATION_REQUIRED", "INVALID", "UNAVAILABLE"]
    pan_masked: str | None = None
    name_on_pan: str | None = None
    name_entered: str | None = None
    options: list[str] | None = None
    message: str | None = None
    next_step: str
    kyc_reused: bool = Field(
        default=False,
        description="True when e-KYC from your earlier application for this PAN was reused, so the "
        "e-KYC step is skipped (D-47).",
    )


class KycStartResponse(BaseModel):
    kyc_session_id: str
    status: Literal["OTP_SENT"]
    demo_kyc_otp: str | None = None
    demo_notice: str | None = None


class KycCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kyc_session_id: str = Field(min_length=1, max_length=64)
    otp: str = Field(pattern=r"^\d{6}$")


class KycCompleteResponse(BaseModel):
    status: Literal["COMPLETE", "DELAYED", "INCOMPLETE"]
    message: str | None = None
    state: str
    next_step: str


class AaConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["APPROVE", "DECLINE"]


class AaConsentResponse(BaseModel):
    consent_id: str
    status: Literal["APPROVED", "DECLINED"]
    months_of_data: int | None = None
    average_monthly_income: int | None = None
    notice: str | None = None
    next_step: str
