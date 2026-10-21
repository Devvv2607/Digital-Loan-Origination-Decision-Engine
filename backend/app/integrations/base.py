"""Provider interfaces (adapter pattern).

The app depends only on these Protocols. Phase 2 ships deterministic mock
implementations; a real provider would implement the same methods.
"""

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal, Protocol

PAN_FORMAT = r"^[A-Z]{5}[0-9]{4}[A-Z]$"


class ProviderTimeout(Exception):
    """The provider did not answer in time. Callers may retry."""


class ProviderError(Exception):
    """The provider failed in a way that retrying will not fix."""


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


class _Result:
    call_status = "SUCCESS"

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


# ---------- PAN ----------

@dataclass
class PanResult(_Result):
    status: Literal["VALID", "INVALID"]
    name: str | None
    date_of_birth: date | None


class PanProvider(Protocol):
    def verify(self, pan: str) -> PanResult: ...


# ---------- e-KYC ----------

@dataclass
class KycStartResult(_Result):
    session_id: str
    status: Literal["OTP_SENT"]
    demo_otp: str | None = None


@dataclass
class KycResult(_Result):
    status: Literal["COMPLETE", "INCOMPLETE", "OTP_INVALID"]
    name: str | None = None
    date_of_birth: date | None = None
    address: dict[str, str] | None = None
    missing_fields: list[str] = field(default_factory=list)

    @property
    def call_status(self) -> str:  # type: ignore[override]
        return "INCOMPLETE" if self.status == "INCOMPLETE" else "SUCCESS"


class KycProvider(Protocol):
    def start(self, pan: str) -> KycStartResult: ...

    def complete(self, session_id: str, pan: str, otp: str) -> KycResult: ...


# ---------- Credit bureau ----------

@dataclass
class BureauReport(_Result):
    ntc: bool
    score: int | None
    existing_monthly_emis: int
    active_loans: int
    max_dpd_12m: int | None


class BureauProvider(Protocol):
    def report(self, pan: str) -> BureauReport: ...


# ---------- Account Aggregator ----------

@dataclass
class AaConsent(_Result):
    consent_id: str
    status: Literal["PENDING"]


@dataclass
class AaDecisionResult(_Result):
    consent_id: str
    status: Literal["APPROVED", "DECLINED"]
    income_credits: list[dict[str, Any]] = field(default_factory=list)
    average_monthly_income: int | None = None


class AaProvider(Protocol):
    def create_consent(self, pan: str, purpose: str, months: int) -> AaConsent: ...

    def decide(self, consent_id: str, pan: str, decision: Literal["APPROVE", "DECLINE"]) -> AaDecisionResult: ...
