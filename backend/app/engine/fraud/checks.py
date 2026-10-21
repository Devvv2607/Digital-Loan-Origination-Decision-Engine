"""Fraud checks F2-F4, run at assessment (F1 runs at the PAN step; see f1_duplicate_pan.py)."""

from app.engine import reasons as rc
from app.engine.policy import F2Params, F3Params, F4Params
from app.engine.types import DecisionInputs, RuleResult


def f2_velocity(i: DecisionInputs, p: F2Params) -> RuleResult:
    count = max(i.applications_24h_phone, i.applications_24h_device)
    value = {"phone": i.applications_24h_phone, "device": i.applications_24h_device}
    if count > p.max_applications:
        return RuleResult(
            "F2", "REFER", rc.FRAUD_VELOCITY,
            f"{count} applications from the same phone or device within {p.window_hours}h (> {p.max_applications}).",
            value,
        )
    return RuleResult("F2", "PASS", value=value)


def f3_identity(i: DecisionInputs, p: F3Params) -> RuleResult:
    problems = []
    sim = i.pan_kyc_name_similarity
    if sim is not None and sim < p.name_similarity_min:
        problems.append(f"PAN vs e-KYC name similarity {sim:.2f} < {p.name_similarity_min:.2f}")
    if i.pan_dob and i.kyc_dob and i.pan_dob != i.kyc_dob:
        problems.append(f"PAN DOB {i.pan_dob.isoformat()} differs from e-KYC DOB {i.kyc_dob.isoformat()}")
    if i.pan_name_mismatch_confirmed:
        problems.append("Applicant kept an entered name that differs from the PAN name")
    value = {"name_similarity": sim, "dob_match": (i.pan_dob == i.kyc_dob) if i.pan_dob and i.kyc_dob else None}
    if problems:
        return RuleResult("F3", "REFER", rc.FRAUD_IDENTITY_MISMATCH, "; ".join(problems) + ".", value)
    return RuleResult("F3", "PASS", value=value)


def f4_income(i: DecisionInputs, p: F4Params) -> RuleResult:
    if i.aa_status != "APPROVED" or i.verified_income is None:
        return RuleResult("F4", "NOT_EVALUATED", detail="No verified income (AA consent not given).")
    declared, verified = i.declared_income, i.verified_income
    diff = abs(declared - verified) / declared if declared > 0 else float("inf")
    value = round(diff, 4) if diff != float("inf") else None
    if diff > p.income_diff_max:
        return RuleResult(
            "F4", "REFER", rc.FRAUD_INCOME_MISMATCH,
            f"Declared income {rc.inr(declared)} vs AA-verified {rc.inr(verified)} "
            f"({diff:.1%} difference > {p.income_diff_max:.0%}).",
            value,
        )
    return RuleResult("F4", "PASS", value=value)
