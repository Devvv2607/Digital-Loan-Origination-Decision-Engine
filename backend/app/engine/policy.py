"""Versioned, configurable policy (docs/RULES.md §1, DECISIONS.md D-14).

- `rule_configs` is append-only. Policy version N = the latest row per rule_id with version <= N.
- Editing any rule inserts one new row with version = current + 1. Old rows are never changed.
- Parameters are validated per rule before a version is created.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import RuleConfig

ELIGIBILITY_RULES = ("R1", "R2", "R3", "R4", "R5", "R6")
FRAUD_CHECKS = ("F1", "F2", "F3", "F4")
ALL_RULE_IDS = (*ELIGIBILITY_RULES, *FRAUD_CHECKS, "PRICING")
# Rules with a single fail outcome that a policy manager may switch between DECLINE and REFER.
OUTCOME_EDITABLE = {"R1", "R3", "R5"}

DEFAULT_SEED_PATH = Path(__file__).resolve().parents[2] / "policy" / "seed_policy.json"


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class R1Params(_Params):
    min_age_now: int = Field(ge=18, le=30)
    max_age_at_maturity: int = Field(ge=45, le=75)


class R2Params(_Params):
    approve_threshold: int = Field(ge=300, le=900)
    refer_floor: int = Field(ge=300, le=900)
    ntc_outcome: Literal["REFER", "DECLINE"] = "REFER"
    calibration: dict[str, Any] | None = None  # metadata from the seeding script

    @model_validator(mode="after")
    def _order(self):
        if self.refer_floor > self.approve_threshold:
            raise ValueError("refer_floor must not be above approve_threshold")
        return self


class R3Params(_Params):
    min_monthly_income: int = Field(ge=0, le=10_000_000)


class R4Params(_Params):
    pass_max: float = Field(gt=0, le=1)
    refer_max: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _order(self):
        if self.pass_max > self.refer_max:
            raise ValueError("pass_max must not be above refer_max")
        return self


class R5Params(_Params):
    min_months_salaried: int = Field(ge=0, le=120)
    min_months_self_employed: int = Field(ge=0, le=240)


class R6Params(_Params):
    max_multiple_of_monthly_income: float = Field(gt=0, le=100)
    round_down_to: int = Field(ge=1, le=100_000)


class F1Params(_Params):
    pass


class F2Params(_Params):
    window_hours: int = Field(ge=1, le=24 * 30)
    max_applications: int = Field(ge=1, le=100)


class F3Params(_Params):
    name_similarity_min: float = Field(gt=0, le=1)


class F4Params(_Params):
    income_diff_max: float = Field(gt=0, le=5)


class RateBand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_score: int = Field(ge=300, le=900)
    annual_rate: float = Field(gt=0, le=60)


class PricingParams(_Params):
    rate_bands: list[RateBand] = Field(min_length=1)
    fallback_rate: float = Field(gt=0, le=60)  # NTC or score unavailable
    processing_fee_rate: float = Field(ge=0, le=0.2)
    loan_amount_min: int = Field(ge=1_000)
    loan_amount_max: int = Field(le=100_000_000)
    tenure_months_min: int = Field(ge=1)
    tenure_months_max: int = Field(le=360)
    offer_validity_days: int = Field(ge=1, le=90)
    cooling_off_days: int = Field(ge=0, le=30)
    grievance_contact: str = Field(min_length=3, max_length=120)

    @model_validator(mode="after")
    def _order(self):
        if self.loan_amount_min > self.loan_amount_max:
            raise ValueError("loan_amount_min must not be above loan_amount_max")
        if self.tenure_months_min > self.tenure_months_max:
            raise ValueError("tenure_months_min must not be above tenure_months_max")
        scores = [b.min_score for b in self.rate_bands]
        if len(set(scores)) != len(scores):
            raise ValueError("rate_bands must have distinct min_score values")
        return self


PARAM_SCHEMAS: dict[str, type[_Params]] = {
    "R1": R1Params, "R2": R2Params, "R3": R3Params, "R4": R4Params, "R5": R5Params, "R6": R6Params,
    "F1": F1Params, "F2": F2Params, "F3": F3Params, "F4": F4Params, "PRICING": PricingParams,
}


@dataclass(frozen=True)
class RuleView:
    rule_id: str
    kind: str
    name: str
    enabled: bool
    parameters: dict[str, Any]
    outcome_on_fail: str | None
    reason_codes: list[str]
    version: int
    created_by: str
    change_comment: str | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: RuleConfig) -> "RuleView":
        return cls(
            rule_id=row.rule_id, kind=row.kind, name=row.name, enabled=row.enabled,
            parameters=dict(row.parameters), outcome_on_fail=row.outcome_on_fail,
            reason_codes=list(row.reason_codes), version=row.version, created_by=row.created_by,
            change_comment=row.change_comment, created_at=row.created_at,
        )


@dataclass(frozen=True)
class Policy:
    version: int
    rules: dict[str, RuleView]

    def rule(self, rule_id: str) -> RuleView:
        return self.rules[rule_id]

    def enabled(self, rule_id: str) -> bool:
        return self.rules[rule_id].enabled

    def params(self, rule_id: str) -> Any:
        """Typed parameters for a rule."""
        return PARAM_SCHEMAS[rule_id].model_validate(self.rules[rule_id].parameters)

    @property
    def pricing(self) -> PricingParams:
        return self.params("PRICING")


def validation_error(exc: ValidationError | ValueError, rule_id: str) -> AppError:
    if isinstance(exc, ValidationError):
        fields = [
            {"field": ".".join(str(p) for p in e["loc"]) or rule_id, "message": e["msg"]} for e in exc.errors()
        ]
    else:
        fields = [{"field": rule_id, "message": str(exc)}]
    return AppError(422, "POLICY_VALIDATION_ERROR", "Some policy values are invalid.", {"rule_id": rule_id, "fields": fields})


def validate_parameters(rule_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
    try:
        return PARAM_SCHEMAS[rule_id].model_validate(parameters).model_dump(mode="json", exclude_none=True)
    except ValidationError as exc:
        raise validation_error(exc, rule_id) from None


def current_version(db: Session) -> int | None:
    return db.scalar(select(func.max(RuleConfig.version)))


def load_policy(db: Session, version: int | None = None) -> Policy:
    latest = current_version(db)
    if latest is None:
        raise AppError(503, "POLICY_NOT_CONFIGURED", "The credit policy has not been loaded yet.")
    version = latest if version is None else version
    if version < 1 or version > latest:
        raise AppError(404, "NOT_FOUND", f"Policy version {version} does not exist.")
    rows = db.scalars(
        select(RuleConfig)
        .where(RuleConfig.version <= version)
        .order_by(RuleConfig.rule_id, RuleConfig.version.desc())
        .ext(distinct_on(RuleConfig.rule_id))
    ).all()
    return Policy(version=version, rules={r.rule_id: RuleView.from_row(r) for r in rows})


def read_seed_file(path: Path = DEFAULT_SEED_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def seed_policy(db: Session, now: datetime, path: Path = DEFAULT_SEED_PATH) -> bool:
    """Insert the seed policy as version 1 if no policy exists. Returns True if it seeded."""
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('policy'))"))
    if current_version(db) is not None:
        return False
    seed = read_seed_file(path)
    rule_ids = {r["rule_id"] for r in seed["rules"]}
    if rule_ids != set(ALL_RULE_IDS):
        raise ValueError(f"Seed policy must define exactly {sorted(ALL_RULE_IDS)}, got {sorted(rule_ids)}")
    for rule in seed["rules"]:
        db.add(
            RuleConfig(
                rule_id=rule["rule_id"],
                kind=rule["kind"],
                name=rule["name"],
                enabled=rule.get("enabled", True),
                parameters=validate_parameters(rule["rule_id"], rule["parameters"]),
                outcome_on_fail=rule.get("outcome_on_fail"),
                reason_codes=rule.get("reason_codes", []),
                version=1,
                created_by="seed",
                change_comment=seed.get("source"),
                created_at=now,
            )
        )
    db.commit()
    return True


def update_rule(
    db: Session,
    rule_id: str,
    *,
    enabled: bool | None,
    parameters: dict[str, Any] | None,
    outcome_on_fail: str | None,
    change_comment: str,
    actor: str,
    now: datetime,
) -> tuple[RuleView, int]:
    """Create a new policy version with one rule changed. Returns (new rule, previous rule version)."""
    if rule_id not in ALL_RULE_IDS:
        raise AppError(404, "NOT_FOUND", f"Unknown rule {rule_id}.")
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('policy'))"))  # serialise version numbers
    current = load_policy(db).rule(rule_id)

    new_params = validate_parameters(rule_id, parameters) if parameters is not None else current.parameters
    new_outcome = current.outcome_on_fail
    if outcome_on_fail is not None and outcome_on_fail != current.outcome_on_fail:
        if rule_id not in OUTCOME_EDITABLE:
            raise validation_error(ValueError(f"The fail outcome of {rule_id} can't be changed."), rule_id)
        new_outcome = outcome_on_fail
    new_enabled = current.enabled if enabled is None else enabled

    if (new_params, new_outcome, new_enabled) == (current.parameters, current.outcome_on_fail, current.enabled):
        raise AppError(422, "POLICY_VALIDATION_ERROR", "No changes to save.", {"rule_id": rule_id, "fields": []})

    version = (current_version(db) or 0) + 1
    row = RuleConfig(
        rule_id=rule_id, kind=current.kind, name=current.name, enabled=new_enabled, parameters=new_params,
        outcome_on_fail=new_outcome, reason_codes=current.reason_codes, version=version,
        created_by=actor, change_comment=change_comment, created_at=now,
    )
    db.add(row)
    db.commit()
    return RuleView.from_row(row), current.version
