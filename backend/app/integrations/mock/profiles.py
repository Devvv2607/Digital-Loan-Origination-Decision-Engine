"""Deterministic mock identities.

Resolution order for a PAN (docs/DECISIONS.md D-17):
1. A registered fixture (`PUT /mock/profiles/{pan}`), like a provider sandbox test identity.
2. Otherwise a profile derived from a hash of the PAN, with "magic" last letters
   forcing failure modes:
     X = PAN invalid   T = KYC timeout   I = KYC incomplete   M = KYC name differs
     D = KYC DOB differs   B = bureau timeout   N = bureau no history (NTC)
Same PAN in, same profile out — every time.
"""

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.mock.population import NTC_SHARE, score_from_uniform

FIRST_NAMES = [
    "AARAV", "ANANYA", "ARJUN", "DIYA", "ISHAAN", "KAVYA", "KABIR", "MEERA", "NIKHIL", "PRIYA",
    "RAHUL", "RIYA", "ROHAN", "SANYA", "SIDDHARTH", "TANVI", "VARUN", "ZOYA", "ADITYA", "NEHA",
]
LAST_NAMES = [
    "AGARWAL", "BANERJEE", "CHOPRA", "DESAI", "GUPTA", "IYER", "JOSHI", "KAPOOR", "KULKARNI", "MEHTA",
    "MENON", "NAIR", "PATEL", "RAO", "REDDY", "SAXENA", "SHARMA", "SINGH", "TRIVEDI", "VERMA",
]
CITIES = [
    ("Pune", "MH", "411001"), ("Bengaluru", "KA", "560001"), ("Chennai", "TN", "600001"),
    ("Hyderabad", "TS", "500001"), ("Jaipur", "RJ", "302001"), ("Kochi", "KL", "682001"),
    ("Lucknow", "UP", "226001"), ("Indore", "MP", "452001"),
]
DOB_START = date(1972, 1, 1)
DOB_SPAN_DAYS = 365 * 28


# ---------- fixture schema ----------

class KycFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    behaviour: Literal["OK", "TIMEOUT", "INCOMPLETE"] = "OK"
    name: str | None = None          # defaults to the PAN name
    dob: date | None = None          # defaults to the PAN DOB
    address: dict[str, str] | None = None


class BureauFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    behaviour: Literal["OK", "TIMEOUT", "NTC"] = "OK"
    score: int | None = Field(default=None, ge=300, le=900)
    existing_monthly_emis: int = Field(default=0, ge=0)
    active_loans: int = Field(default=0, ge=0)
    max_dpd_12m: int = Field(default=0, ge=0)


class AaFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    average_monthly_income: int | None = Field(default=None, ge=0)
    income_credits: list[int] | None = Field(default=None, min_length=6, max_length=6)


class MockProfileIn(BaseModel):
    """Body of PUT /mock/profiles/{pan}."""

    model_config = ConfigDict(extra="forbid")
    pan_name: str = Field(min_length=2, max_length=120)
    pan_dob: date
    pan_status: Literal["VALID", "INVALID"] = "VALID"
    kyc: KycFixture = Field(default_factory=KycFixture)
    bureau: BureauFixture = Field(default_factory=BureauFixture)
    aa: AaFixture = Field(default_factory=AaFixture)


# ---------- resolved profile ----------

@dataclass
class ResolvedProfile:
    source: Literal["fixture", "hash"]
    pan_status: str
    pan_name: str
    pan_dob: date
    kyc_behaviour: str
    kyc_name: str
    kyc_dob: date
    kyc_address: dict[str, str]
    bureau_behaviour: str
    score: int | None
    existing_monthly_emis: int
    active_loans: int
    max_dpd_12m: int
    aa_average_income: int
    aa_credits: list[int] | None


def uniform(pan: str, salt: str) -> float:
    """Deterministic pseudo-random number in [0, 1) from the PAN."""
    digest = hashlib.sha256(f"{salt}:{pan}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _pick(options: list, pan: str, salt: str):
    return options[int(uniform(pan, salt) * len(options))]


def _address(pan: str) -> dict[str, str]:
    city, state, pincode = _pick(CITIES, pan, "city")
    return {"city": city, "state": state, "pincode": pincode}


def _hash_profile(pan: str) -> ResolvedProfile:
    name = f"{_pick(FIRST_NAMES, pan, 'first')} {_pick(LAST_NAMES, pan, 'last')}"
    dob = DOB_START + timedelta(days=int(uniform(pan, "dob") * DOB_SPAN_DAYS))

    ntc = uniform(pan, "ntc") < NTC_SHARE
    has_loans = uniform(pan, "has_loans") >= 0.3
    emis = round(uniform(pan, "emis") * 25_000 / 500) * 500 if (has_loans and not ntc) else 0
    income_u = uniform(pan, "income")

    profile = ResolvedProfile(
        source="hash",
        pan_status="VALID",
        pan_name=name,
        pan_dob=dob,
        kyc_behaviour="OK",
        kyc_name=name,
        kyc_dob=dob,
        kyc_address=_address(pan),
        bureau_behaviour="NTC" if ntc else "OK",
        score=None if ntc else score_from_uniform(uniform(pan, "score")),
        existing_monthly_emis=emis,
        active_loans=(1 + int(uniform(pan, "loans") * 3)) if emis else 0,
        max_dpd_12m=30 if (emis and uniform(pan, "dpd") < 0.05) else 0,
        aa_average_income=int(round(25_000 + income_u * income_u * 175_000, -2)),
        aa_credits=None,
    )
    _apply_magic(pan, profile)
    return profile


def _apply_magic(pan: str, p: ResolvedProfile) -> None:
    last = pan[-1]
    if last == "X":
        p.pan_status = "INVALID"
    elif last == "T":
        p.kyc_behaviour = "TIMEOUT"
    elif last == "I":
        p.kyc_behaviour = "INCOMPLETE"
    elif last == "M":
        other = p.pan_name
        salt = 0
        while other == p.pan_name:
            other = f"{_pick(FIRST_NAMES, pan, f'alt-first-{salt}')} {_pick(LAST_NAMES, pan, f'alt-last-{salt}')}"
            salt += 1
        p.kyc_name = other
    elif last == "D":
        p.kyc_dob = p.pan_dob + timedelta(days=400)
    elif last == "B":
        p.bureau_behaviour = "TIMEOUT"
    elif last == "N":
        p.bureau_behaviour = "NTC"
        p.score = None
        p.existing_monthly_emis = 0
        p.active_loans = 0


def _fixture_profile(pan: str, fixture: MockProfileIn) -> ResolvedProfile:
    hashed = _hash_profile(pan)  # supplies defaults for anything the fixture leaves out
    bureau = fixture.bureau
    if bureau.behaviour == "OK" and bureau.score is None:
        bureau_score = hashed.score if hashed.score is not None else score_from_uniform(uniform(pan, "score"))
    else:
        bureau_score = bureau.score if bureau.behaviour == "OK" else None
    credits = fixture.aa.income_credits
    if fixture.aa.average_monthly_income is not None:
        average = fixture.aa.average_monthly_income
    elif credits:
        average = round(sum(credits) / len(credits))
    else:
        average = hashed.aa_average_income
    return ResolvedProfile(
        source="fixture",
        pan_status=fixture.pan_status,
        pan_name=fixture.pan_name.upper(),
        pan_dob=fixture.pan_dob,
        kyc_behaviour=fixture.kyc.behaviour,
        kyc_name=(fixture.kyc.name or fixture.pan_name).upper(),
        kyc_dob=fixture.kyc.dob or fixture.pan_dob,
        kyc_address=fixture.kyc.address or _address(pan),
        bureau_behaviour=bureau.behaviour,
        score=bureau_score,
        existing_monthly_emis=bureau.existing_monthly_emis if bureau.behaviour == "OK" else 0,
        active_loans=bureau.active_loans if bureau.behaviour == "OK" else 0,
        max_dpd_12m=bureau.max_dpd_12m,
        aa_average_income=average,
        aa_credits=credits,
    )


def resolve_profile(pan: str, fixture: dict[str, Any] | None) -> ResolvedProfile:
    if fixture is not None:
        return _fixture_profile(pan, MockProfileIn.model_validate(fixture))
    return _hash_profile(pan)
