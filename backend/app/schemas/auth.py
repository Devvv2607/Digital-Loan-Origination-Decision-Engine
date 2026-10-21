from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.applications import ResumableApplication

# Indian mobile format. Demo numbers like 9000000001 are fine; no SMS is ever sent.
Phone = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[6-9]\d{9}$")]


class OtpSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: Phone


class OtpSendResponse(BaseModel):
    otp_request_id: UUID
    expires_at: datetime
    resends_remaining_this_hour: int
    demo_otp: str | None = None
    demo_notice: str | None = None


class OtpVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: Phone
    otp: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{6}$")]


class OtpVerifyResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str = "applicant"
    applicant_id: UUID
    resumable_applications: list[ResumableApplication]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    expires_in: int
