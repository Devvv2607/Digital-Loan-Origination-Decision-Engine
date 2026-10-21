from datetime import date, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class EmploymentType(StrEnum):
    SALARIED = "SALARIED"
    SELF_EMPLOYED = "SELF_EMPLOYED"


class LoanPurpose(StrEnum):
    HOME_RENOVATION = "HOME_RENOVATION"
    MEDICAL = "MEDICAL"
    EDUCATION = "EDUCATION"
    TRAVEL = "TRAVEL"
    WEDDING = "WEDDING"
    DEBT_CONSOLIDATION = "DEBT_CONSOLIDATION"
    OTHER = "OTHER"


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]


class ApplicationDetailsPatch(BaseModel):
    """US-02 details. All optional so the applicant can save progress step by step."""

    model_config = ConfigDict(extra="forbid")

    full_name: Name | None = None
    date_of_birth: date | None = None
    employment_type: EmploymentType | None = None
    employer_name: Name | None = None
    months_in_current_job: int | None = Field(default=None, ge=0, le=600)
    declared_monthly_income: int | None = Field(default=None, ge=0, le=100_000_000)
    # Product limits come from the current PRICING policy and are checked in the service.
    loan_amount: int | None = Field(default=None, ge=1, le=100_000_000)
    tenure_months: int | None = Field(default=None, ge=1, le=360)
    purpose: LoanPurpose | None = None


DETAIL_FIELDS: tuple[str, ...] = tuple(ApplicationDetailsPatch.model_fields)


class ApplicationDetails(BaseModel):
    full_name: str | None
    date_of_birth: date | None
    employment_type: str | None
    employer_name: str | None
    months_in_current_job: int | None
    declared_monthly_income: int | None
    loan_amount: int | None
    tenure_months: int | None
    purpose: str | None


class PanSummary(BaseModel):
    masked: str | None
    status: str


class StatusSummary(BaseModel):
    status: str


class TimelineEvent(BaseModel):
    event_type: str
    from_state: str | None
    to_state: str | None
    actor: str
    reason: str | None
    created_at: datetime


class ApplicationCreated(BaseModel):
    id: UUID
    state: str
    next_step: str
    created_at: datetime


class ApplicationView(BaseModel):
    id: UUID
    state: str
    next_step: str
    details: ApplicationDetails
    pan: PanSummary
    kyc: StatusSummary
    aa: StatusSummary
    policy_version: int | None
    created_at: datetime
    last_activity_at: datetime
    timeline: list[TimelineEvent]


class SubmitResponse(BaseModel):
    id: UUID
    state: str
    next_step: str


class ResumableApplication(BaseModel):
    id: UUID
    state: str
    next_step: str
    last_activity_at: datetime
