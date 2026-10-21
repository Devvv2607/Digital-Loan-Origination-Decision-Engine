"""Mock implementations of the four provider interfaces.

All behaviour is deterministic (see profiles.py). Latency is simulated with
MOCK_LATENCY_MS. Session and consent IDs are random, but the KYC OTP for a session
is derived from its ID, so no server-side session state is needed.
"""

import hashlib
import re
import secrets
import time
from collections.abc import Callable
from datetime import date
from typing import Any, Literal

from app.core.clock import Clock
from app.integrations.base import (
    PAN_FORMAT,
    AaConsent,
    AaDecisionResult,
    BureauReport,
    KycResult,
    KycStartResult,
    PanResult,
    ProviderError,
    ProviderTimeout,
)
from app.integrations.mock.profiles import ResolvedProfile, resolve_profile, uniform

FixtureLookup = Callable[[str], dict[str, Any] | None]


def kyc_otp_for(session_id: str) -> str:
    return f"{int(hashlib.sha256(f'kyc-otp:{session_id}'.encode()).hexdigest(), 16) % 1_000_000:06d}"


class _MockBase:
    def __init__(self, latency_ms: int, fixtures: FixtureLookup):
        self._latency_ms = latency_ms
        self._fixtures = fixtures

    def _wait(self) -> None:
        if self._latency_ms > 0:
            time.sleep(self._latency_ms / 1000)

    def _profile(self, pan: str) -> ResolvedProfile:
        if not re.fullmatch(PAN_FORMAT, pan):
            raise ProviderError("PAN format invalid")
        return resolve_profile(pan, self._fixtures(pan))


class MockPanProvider(_MockBase):
    def verify(self, pan: str) -> PanResult:
        self._wait()
        p = self._profile(pan)
        if p.pan_status != "VALID":
            return PanResult(status="INVALID", name=None, date_of_birth=None)
        return PanResult(status="VALID", name=p.pan_name, date_of_birth=p.pan_dob)


class MockKycProvider(_MockBase):
    def start(self, pan: str) -> KycStartResult:
        self._wait()
        self._profile(pan)
        session_id = f"k-{secrets.token_hex(8)}"
        return KycStartResult(session_id=session_id, status="OTP_SENT", demo_otp=kyc_otp_for(session_id))

    def complete(self, session_id: str, pan: str, otp: str) -> KycResult:
        self._wait()
        p = self._profile(pan)
        if p.kyc_behaviour == "TIMEOUT":
            raise ProviderTimeout("e-KYC provider timed out")
        if otp != kyc_otp_for(session_id):
            return KycResult(status="OTP_INVALID")
        if p.kyc_behaviour == "INCOMPLETE":
            return KycResult(status="INCOMPLETE", name=p.kyc_name, date_of_birth=p.kyc_dob, missing_fields=["address"])
        return KycResult(status="COMPLETE", name=p.kyc_name, date_of_birth=p.kyc_dob, address=p.kyc_address)


class MockBureauProvider(_MockBase):
    def report(self, pan: str) -> BureauReport:
        self._wait()
        p = self._profile(pan)
        if p.bureau_behaviour == "TIMEOUT":
            raise ProviderTimeout("Credit bureau timed out")
        if p.bureau_behaviour == "NTC":
            return BureauReport(ntc=True, score=None, existing_monthly_emis=0, active_loans=0, max_dpd_12m=None)
        return BureauReport(
            ntc=False,
            score=p.score,
            existing_monthly_emis=p.existing_monthly_emis,
            active_loans=p.active_loans,
            max_dpd_12m=p.max_dpd_12m,
        )


def _last_months(today: date, n: int) -> list[str]:
    """The n complete calendar months before `today`, oldest first, as 'YYYY-MM'."""
    year, month = today.year, today.month
    out = []
    for _ in range(n):
        month -= 1
        if month == 0:
            year, month = year - 1, 12
        out.append(f"{year:04d}-{month:02d}")
    return list(reversed(out))


def _credits_around(average: int, pan: str) -> list[int]:
    """Six monthly credits that vary a little but average exactly to `average`."""
    d1 = round(average * 0.03 * uniform(pan, "credit-d1") / 100) * 100
    d2 = round(average * 0.03 * uniform(pan, "credit-d2") / 100) * 100
    return [average + d1, average - d1, average + d2, average, average - d2, average]


class MockAaProvider(_MockBase):
    def __init__(self, latency_ms: int, fixtures: FixtureLookup, clock: Clock):
        super().__init__(latency_ms, fixtures)
        self._clock = clock

    def create_consent(self, pan: str, purpose: str, months: int) -> AaConsent:
        self._wait()
        self._profile(pan)
        return AaConsent(consent_id=f"aa-c-{secrets.token_hex(8)}", status="PENDING")

    def decide(self, consent_id: str, pan: str, decision: Literal["APPROVE", "DECLINE"]) -> AaDecisionResult:
        self._wait()
        p = self._profile(pan)
        if decision == "DECLINE":
            return AaDecisionResult(consent_id=consent_id, status="DECLINED")
        amounts = p.aa_credits or _credits_around(p.aa_average_income, pan)
        months = _last_months(self._clock.now().date(), len(amounts))
        return AaDecisionResult(
            consent_id=consent_id,
            status="APPROVED",
            income_credits=[{"month": m, "amount": a} for m, a in zip(months, amounts, strict=True)],
            average_monthly_income=round(sum(amounts) / len(amounts)),
        )
