"""Inputs and per-rule results shared by rules, fraud checks and the decision engine."""

from calendar import monthrange
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from app.engine.reasons import Severity


@dataclass(frozen=True)
class BureauData:
    available: bool
    ntc: bool = False
    score: int | None = None
    existing_monthly_emis: int = 0
    active_loans: int = 0
    max_dpd_12m: int | None = None


@dataclass(frozen=True)
class DecisionInputs:
    decision_date: date
    date_of_birth: date            # e-KYC DOB (D-27)
    employment_type: str           # SALARIED | SELF_EMPLOYED
    months_in_current_job: int
    requested_amount: int
    tenure_months: int
    declared_income: int
    aa_status: str                 # APPROVED | DECLINED
    verified_income: int | None    # AA average monthly income
    bureau: BureauData
    applications_24h_phone: int
    applications_24h_device: int
    pan_kyc_name_similarity: float | None
    pan_dob: date | None
    kyc_dob: date | None
    pan_name_mismatch_confirmed: bool  # EC-04 "keep my entered name"

    def snapshot(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("decision_date", "date_of_birth", "pan_dob", "kyc_dob"):
            data[key] = data[key].isoformat() if data[key] else None
        return data


@dataclass
class RuleResult:
    rule_id: str
    result: str                    # PASS | DECLINE | REFER | INFO | SKIPPED | NOT_EVALUATED
    code: str | None = None
    detail: str | None = None      # internal explanation (analysts only)
    value: Any = None
    extra_codes: list[tuple[str, Severity, str]] = field(default_factory=list)  # (code, severity, detail)

    @property
    def severity(self) -> Severity | None:
        return {"DECLINE": Severity.DECLINE, "REFER": Severity.REFER, "INFO": Severity.INFO}.get(self.result)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"rule_id": self.rule_id, "result": self.result}
        if self.code:
            out["code"] = self.code
        if self.value is not None:
            out["value"] = self.value
        if self.detail:
            out["detail"] = self.detail
        if self.extra_codes:
            out["extra_codes"] = [{"code": c, "severity": s.value, "detail": d} for c, s, d in self.extra_codes]
        return out


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, monthrange(year, month)[1]))


def birthday(dob: date, age: int) -> date:
    """Date of the `age`-th birthday. A 29 Feb birthday falls on 1 Mar in non-leap years."""
    try:
        return dob.replace(year=dob.year + age)
    except ValueError:
        return date(dob.year + age, 3, 1)


def age_on(dob: date, on: date) -> int:
    years = on.year - dob.year
    return years if on >= birthday(dob, years) else years - 1
