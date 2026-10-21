"""Unit tests for the 6 eligibility rules and fraud checks F2-F4, at their boundaries."""

from dataclasses import replace
from datetime import date

import pytest

from app.engine import reasons as rc
from app.engine.fraud.checks import f2_velocity, f3_identity, f4_income
from app.engine.policy import F2Params, F3Params, F4Params, R1Params, R2Params, R3Params, R4Params, R5Params, R6Params
from app.engine.rules import r1_age, r2_credit_score, r3_min_income, r4_foir, r5_employment, r6_cap
from app.engine.types import BureauData, DecisionInputs, add_months, age_on, birthday

TODAY = date(2026, 1, 15)
BASE = DecisionInputs(
    decision_date=TODAY, date_of_birth=date(1994, 3, 12), employment_type="SALARIED", months_in_current_job=30,
    requested_amount=500_000, tenure_months=36, declared_income=85_000, aa_status="APPROVED",
    verified_income=84_200, bureau=BureauData(available=True, score=781, existing_monthly_emis=6_000),
    applications_24h_phone=1, applications_24h_device=1, pan_kyc_name_similarity=1.0,
    pan_dob=date(1994, 3, 12), kyc_dob=date(1994, 3, 12), pan_name_mismatch_confirmed=False,
)


# ---------- date helpers ----------

def test_date_helpers():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 1, 15), 36) == date(2029, 1, 15)
    assert birthday(date(2000, 2, 29), 21) == date(2021, 3, 1)
    assert age_on(date(2000, 1, 16), TODAY) == 25 and age_on(date(2000, 1, 15), TODAY) == 26


# ---------- R1 age ----------

R1 = R1Params(min_age_now=21, max_age_at_maturity=60)


def test_r1_passes_on_21st_birthday():
    i = replace(BASE, date_of_birth=date(2005, 1, 15), tenure_months=12)
    assert r1_age(i, R1).result == "PASS"


def test_r1_declines_day_before_21st_birthday():
    res = r1_age(replace(BASE, date_of_birth=date(2005, 1, 16)), R1)
    assert (res.result, res.code) == ("DECLINE", rc.ELIG_AGE) and "below the minimum" in res.detail


def test_r1_maturity_on_60th_birthday_passes_day_after_declines():
    # 36-month loan from 2026-01-15 matures 2029-01-15.
    assert r1_age(replace(BASE, date_of_birth=date(1969, 1, 15)), R1).result == "PASS"
    res = r1_age(replace(BASE, date_of_birth=date(1969, 1, 14)), R1)
    assert (res.result, res.code) == ("DECLINE", rc.ELIG_AGE) and "maturity" in res.detail


def test_r1_outcome_can_be_configured_to_refer():
    assert r1_age(replace(BASE, date_of_birth=date(2010, 1, 1)), R1, "REFER").result == "REFER"


# ---------- R2 credit score ----------

R2 = R2Params(approve_threshold=631, refer_floor=608)


@pytest.mark.parametrize(
    ("score", "result", "code"),
    [(900, "PASS", None), (631, "PASS", None), (630, "REFER", rc.ELIG_SCORE_BORDERLINE),
     (608, "REFER", rc.ELIG_SCORE_BORDERLINE), (607, "DECLINE", rc.ELIG_SCORE_LOW), (300, "DECLINE", rc.ELIG_SCORE_LOW)],
)
def test_r2_bands(score, result, code):
    res = r2_credit_score(replace(BASE, bureau=BureauData(available=True, score=score)), R2)
    assert (res.result, res.code) == (result, code)


def test_r2_new_to_credit_refers_by_default_and_is_configurable():
    ntc = replace(BASE, bureau=BureauData(available=True, ntc=True))
    assert (r2_credit_score(ntc, R2).result, r2_credit_score(ntc, R2).code) == ("REFER", rc.ELIG_THIN_FILE)
    assert r2_credit_score(ntc, R2.model_copy(update={"ntc_outcome": "DECLINE"})).result == "DECLINE"


# ---------- R3 minimum income ----------

def test_r3_boundary():
    p = R3Params(min_monthly_income=25_000)
    assert r3_min_income(25_000, p).result == "PASS"
    res = r3_min_income(24_999, p)
    assert (res.result, res.code) == ("DECLINE", rc.ELIG_INCOME_LOW)
    assert r3_min_income(24_999, p, "REFER").result == "REFER"


# ---------- R4 FOIR ----------

R4 = R4Params(pass_max=0.5, refer_max=0.6)


@pytest.mark.parametrize(
    ("existing", "new", "income", "result"),
    [(20_000, 30_000, 100_000, "PASS"),      # exactly 50%
     (20_000, 30_010, 100_000, "REFER"),     # 50.01%
     (30_000, 30_000, 100_000, "REFER"),     # exactly 60%
     (30_000, 30_010, 100_000, "DECLINE"),   # 60.01%
     (0, 10_000, 0, "DECLINE")],             # no income
)
def test_r4_bands(existing, new, income, result):
    res = r4_foir(existing, new, income, R4)
    assert res.result == result
    if result != "PASS":
        assert res.code == rc.ELIG_FOIR_HIGH


# ---------- R5 employment ----------

R5 = R5Params(min_months_salaried=6, min_months_self_employed=24)


@pytest.mark.parametrize(
    ("kind", "months", "result"),
    [("SALARIED", 6, "PASS"), ("SALARIED", 5, "REFER"), ("SELF_EMPLOYED", 24, "PASS"), ("SELF_EMPLOYED", 23, "REFER")],
)
def test_r5_tenure(kind, months, result):
    res = r5_employment(replace(BASE, employment_type=kind, months_in_current_job=months), R5)
    assert res.result == result
    if result == "REFER":
        assert res.code == rc.ELIG_EMPLOYMENT_TENURE


# ---------- R6 cap ----------

def test_r6_cap_rounds_down_and_only_caps_when_needed():
    p = R6Params(max_multiple_of_monthly_income=20, round_down_to=1_000)
    assert r6_cap(1_000_000, 84_249, p) == (1_684_000, 1_000_000)   # under the cap
    assert r6_cap(2_000_000, 84_249, p) == (1_684_000, 1_684_000)   # capped, rounded down
    assert r6_cap(1_684_000, 84_200, p) == (1_684_000, 1_684_000)   # exactly at the cap


# ---------- F2 velocity ----------

F2 = F2Params(window_hours=24, max_applications=3)


@pytest.mark.parametrize(("phone", "device", "result"),
                         [(3, 1, "PASS"), (4, 1, "REFER"), (1, 3, "PASS"), (1, 4, "REFER"), (1, 0, "PASS")])
def test_f2_velocity(phone, device, result):
    res = f2_velocity(replace(BASE, applications_24h_phone=phone, applications_24h_device=device), F2)
    assert res.result == result
    if result == "REFER":
        assert res.code == rc.FRAUD_VELOCITY


# ---------- F3 identity ----------

F3 = F3Params(name_similarity_min=0.85)


@pytest.mark.parametrize(
    ("changes", "result"),
    [({"pan_kyc_name_similarity": 0.85}, "PASS"),
     ({"pan_kyc_name_similarity": 0.8499}, "REFER"),
     ({"kyc_dob": date(1994, 3, 13)}, "REFER"),
     ({"pan_name_mismatch_confirmed": True}, "REFER")],
)
def test_f3_identity(changes, result):
    res = f3_identity(replace(BASE, **changes), F3)
    assert res.result == result
    if result == "REFER":
        assert res.code == rc.FRAUD_IDENTITY_MISMATCH


# ---------- F4 income ----------

F4 = F4Params(income_diff_max=0.3)


@pytest.mark.parametrize(
    ("declared", "verified", "result"),
    [(100_000, 70_000, "PASS"),      # exactly 30%
     (100_000, 69_990, "REFER"),     # 30.01%
     (100_000, 130_000, "PASS"),     # higher verified income, exactly 30%
     (100_000, 131_000, "REFER"),
     (0, 50_000, "REFER")],
)
def test_f4_income(declared, verified, result):
    res = f4_income(replace(BASE, declared_income=declared, verified_income=verified), F4)
    assert res.result == result


def test_f4_not_evaluated_without_verified_income():
    res = f4_income(replace(BASE, aa_status="DECLINED", verified_income=None), F4)
    assert res.result == "NOT_EVALUATED"


# ---------- reason helpers ----------

@pytest.mark.parametrize(("amount", "text"), [(0, "₹0"), (999, "₹999"), (1_000, "₹1,000"), (100_000, "₹1,00,000"),
                                              (1_684_000, "₹16,84,000"), (25_000_000, "₹2,50,00,000")])
def test_indian_rupee_formatting(amount, text):
    assert rc.inr(amount) == text


def test_fraud_wording_never_reveals_the_check():
    for code in (rc.FRAUD_VELOCITY, rc.FRAUD_IDENTITY_MISMATCH, rc.FRAUD_INCOME_MISMATCH, rc.FRAUD_DUPLICATE_PAN):
        assert rc.applicant_message(code, rc.Severity.REFER) == "We need to review a few details."


def test_reason_code_families_are_distinct():
    families = {rc.family(c) for c in rc.ALL_CODES}
    assert families == {"SYS", "DATA", "FRAUD", "ELIG", "INFO"}
