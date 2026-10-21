"""The 6 eligibility rules (docs/RULES.md §3). Each is a pure function returning a RuleResult."""

from app.engine import reasons as rc
from app.engine.policy import R1Params, R2Params, R3Params, R4Params, R5Params, R6Params
from app.engine.types import DecisionInputs, RuleResult, add_months, age_on, birthday


def r1_age(i: DecisionInputs, p: R1Params, outcome_on_fail: str = "DECLINE") -> RuleResult:
    """Pass if the min-age birthday has been reached and maturity is on/before the max-age birthday."""
    maturity = add_months(i.decision_date, i.tenure_months)
    old_enough = i.decision_date >= birthday(i.date_of_birth, p.min_age_now)
    young_enough = maturity <= birthday(i.date_of_birth, p.max_age_at_maturity)
    age_now = age_on(i.date_of_birth, i.decision_date)
    age_at_maturity = age_on(i.date_of_birth, maturity)
    value = {"age_now": age_now, "age_at_maturity": age_at_maturity, "maturity_date": maturity.isoformat()}
    if old_enough and young_enough:
        return RuleResult("R1", "PASS", value=value)
    why = (
        f"Age {age_now} is below the minimum of {p.min_age_now}."
        if not old_enough
        else f"Age at maturity ({maturity.isoformat()}) would exceed {p.max_age_at_maturity}."
    )
    return RuleResult("R1", outcome_on_fail, rc.ELIG_AGE, why, value)


def r2_credit_score(i: DecisionInputs, p: R2Params) -> RuleResult:
    b = i.bureau
    if b.ntc or b.score is None:
        return RuleResult("R2", p.ntc_outcome, rc.ELIG_THIN_FILE, "No credit history with the bureau (new to credit).")
    if b.score >= p.approve_threshold:
        return RuleResult("R2", "PASS", value=b.score)
    if b.score >= p.refer_floor:
        return RuleResult(
            "R2", "REFER", rc.ELIG_SCORE_BORDERLINE,
            f"Score {b.score} is in the refer band [{p.refer_floor}, {p.approve_threshold}).", b.score,
        )
    return RuleResult("R2", "DECLINE", rc.ELIG_SCORE_LOW, f"Score {b.score} is below the refer floor {p.refer_floor}.", b.score)


def r3_min_income(income: int, p: R3Params, outcome_on_fail: str = "DECLINE") -> RuleResult:
    if income >= p.min_monthly_income:
        return RuleResult("R3", "PASS", value=income)
    return RuleResult(
        "R3", outcome_on_fail, rc.ELIG_INCOME_LOW,
        f"Monthly income {rc.inr(income)} is below the minimum {rc.inr(p.min_monthly_income)}.", income,
    )


def r4_foir(existing_emis: int, new_emi: int, income: int, p: R4Params) -> RuleResult:
    foir = (existing_emis + new_emi) / income if income > 0 else float("inf")
    value = round(foir, 4) if foir != float("inf") else None
    detail = (
        f"FOIR {foir:.1%} = (existing EMIs {rc.inr(existing_emis)} + new EMI {rc.inr(new_emi)}) / income {rc.inr(income)}."
        if income > 0
        else "No income to measure obligations against."
    )
    if foir <= p.pass_max:
        return RuleResult("R4", "PASS", value=value, detail=detail)
    if foir <= p.refer_max:
        return RuleResult("R4", "REFER", rc.ELIG_FOIR_HIGH, detail, value)
    return RuleResult("R4", "DECLINE", rc.ELIG_FOIR_HIGH, detail, value)


def r5_employment(i: DecisionInputs, p: R5Params, outcome_on_fail: str = "REFER") -> RuleResult:
    needed = p.min_months_salaried if i.employment_type == "SALARIED" else p.min_months_self_employed
    if i.months_in_current_job >= needed:
        return RuleResult("R5", "PASS", value=i.months_in_current_job)
    kind = "in current job" if i.employment_type == "SALARIED" else "in business"
    return RuleResult(
        "R5", outcome_on_fail, rc.ELIG_EMPLOYMENT_TENURE,
        f"{i.employment_type.replace('_', ' ').title()}, {i.months_in_current_job} months {kind} (< {needed}).",
        i.months_in_current_job,
    )


def r6_cap(requested: int, income: int, p: R6Params) -> tuple[int, int]:
    """Return (cap, amount to offer). The amount is the request, or the cap if the request exceeds it."""
    cap = int(p.max_multiple_of_monthly_income * income) // p.round_down_to * p.round_down_to
    return cap, min(requested, cap)
