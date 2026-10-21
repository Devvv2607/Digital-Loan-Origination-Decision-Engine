"""The decision engine as a pure function: sequence, precedence, completeness, counter-offers."""

from dataclasses import replace
from datetime import date

from app.engine import reasons as rc
from app.engine.decision import EVALUATED_IDS, applicant_reasons, evaluate
from app.engine.types import BureauData
from tests.helpers import make_policy
from tests.test_rules_and_checks import BASE

POLICY = make_policy()


def codes(result):
    return result.reason_codes


def test_strong_applicant_is_approved_with_every_check_evaluated():
    r = evaluate(BASE, POLICY)
    assert (r.outcome, codes(r), r.primary_reason_code) == ("APPROVED", [], None)
    assert [x.rule_id for x in r.rule_results] == list(EVALUATED_IDS)
    assert all(x.result == "PASS" for x in r.rule_results)
    snap = r.snapshot
    assert (snap["income_used"], snap["income_source"], snap["annual_rate"], snap["emi"]) == (84_200, "AA", "12.99", 16_845)
    assert snap["foir"] == round((6_000 + 16_845) / 84_200, 4)


def test_bureau_unavailable_stops_with_sys_code_and_no_rule_marked_failed():
    # Even an applicant who would fail R1 is referred, not declined, when the bureau is down.
    i = replace(BASE, bureau=BureauData(available=False), date_of_birth=date(2010, 1, 1))
    r = evaluate(i, POLICY)
    assert (r.outcome, codes(r)) == ("REFERRED", [rc.SYS_BUREAU_UNAVAILABLE])
    assert {x.result for x in r.rule_results} == {"NOT_EVALUATED"}


def test_aa_declined_uses_declared_income_and_caps_at_referred():
    r = evaluate(replace(BASE, aa_status="DECLINED", verified_income=None), POLICY)
    assert (r.outcome, codes(r)) == ("REFERRED", [rc.DATA_INCOME_UNVERIFIED])
    assert (r.snapshot["income_used"], r.snapshot["income_source"]) == (85_000, "DECLARED")


def test_aa_declined_still_declines_when_declared_income_too_low():
    r = evaluate(replace(BASE, aa_status="DECLINED", verified_income=None, declared_income=20_000), POLICY)
    assert r.outcome == "DECLINED"
    assert r.primary_reason_code == rc.ELIG_INCOME_LOW
    assert rc.DATA_INCOME_UNVERIFIED in codes(r)


def test_verified_income_replaces_declared_and_f4_fires():
    r = evaluate(replace(BASE, declared_income=120_000, verified_income=72_400), POLICY)
    assert r.outcome == "REFERRED"
    assert codes(r) == [rc.FRAUD_INCOME_MISMATCH]
    assert r.snapshot["income_used"] == 72_400


def test_decline_beats_refer_and_all_reasons_are_kept():
    i = replace(BASE, date_of_birth=date(2006, 1, 1), applications_24h_phone=5, months_in_current_job=2,
                bureau=BureauData(available=True, score=500, existing_monthly_emis=0), declared_income=20_000,
                verified_income=20_000)
    r = evaluate(i, POLICY)
    assert r.outcome == "DECLINED"
    # ₹20,000 income also caps the amount at ₹4,00,000 (R6) and the EMI on that still breaches FOIR (R4).
    assert codes(r) == [rc.ELIG_AGE, rc.ELIG_SCORE_LOW, rc.ELIG_INCOME_LOW, rc.ELIG_FOIR_HIGH,
                        rc.FRAUD_VELOCITY, rc.ELIG_EMPLOYMENT_TENURE, rc.INFO_AMOUNT_CAPPED]
    assert r.primary_reason_code == rc.ELIG_AGE
    # Applicant sees only the reasons that caused the decline, and nothing about fraud.
    shown = applicant_reasons(r.outcome, r.reasons)
    assert [s["code"] for s in shown] == [rc.ELIG_AGE, rc.ELIG_SCORE_LOW, rc.ELIG_INCOME_LOW, rc.ELIG_FOIR_HIGH]


def test_refer_reasons_are_ordered_by_priority():
    i = replace(BASE, aa_status="DECLINED", verified_income=None, applications_24h_device=4,
                bureau=BureauData(available=True, score=620, existing_monthly_emis=0), months_in_current_job=3)
    r = evaluate(i, POLICY)
    assert r.outcome == "REFERRED"
    assert codes(r) == [rc.FRAUD_VELOCITY, rc.DATA_INCOME_UNVERIFIED, rc.ELIG_SCORE_BORDERLINE,
                        rc.ELIG_EMPLOYMENT_TENURE]
    shown = applicant_reasons(r.outcome, r.reasons)
    assert shown[0] == {"code": None, "message": "We need to review a few details."}
    assert all(s["code"] is None or not s["code"].startswith("FRAUD") for s in shown)


def test_new_to_credit_refers_and_is_priced_at_fallback_rate():
    r = evaluate(replace(BASE, bureau=BureauData(available=True, ntc=True)), POLICY)
    assert (r.outcome, codes(r)) == ("REFERRED", [rc.ELIG_THIN_FILE])
    assert r.snapshot["annual_rate"] == "21.99"


def test_counter_offer_reruns_foir_on_capped_amount_and_approves():
    # Requested 25L > 20x income (20L). FOIR on 25L would be ~57% (refer); on 20L it is ~45% (pass).
    i = replace(BASE, declared_income=100_000, verified_income=100_000, requested_amount=2_500_000,
                tenure_months=60, bureau=BureauData(available=True, score=781, existing_monthly_emis=0))
    r = evaluate(i, POLICY)
    assert (r.outcome, codes(r)) == ("APPROVED", [rc.INFO_AMOUNT_CAPPED])
    assert r.primary_reason_code == rc.INFO_AMOUNT_CAPPED
    assert (r.snapshot["offer_amount"], r.snapshot["amount_capped"]) == (2_000_000, True)
    assert r.snapshot["foir"] < 0.5
    assert applicant_reasons(r.outcome, r.reasons)[0]["message"].startswith("Based on your income, we can offer up to ₹20,00,000")


def test_counter_offer_not_made_when_capped_amount_still_unaffordable():
    i = replace(BASE, declared_income=100_000, verified_income=100_000, requested_amount=2_500_000,
                bureau=BureauData(available=True, score=781, existing_monthly_emis=20_000))
    r = evaluate(i, POLICY)
    assert r.outcome == "DECLINED"
    assert codes(r) == [rc.ELIG_FOIR_HIGH, rc.INFO_AMOUNT_CAPPED]
    r4 = next(x for x in r.rule_results if x.rule_id == "R4")
    assert r4.result == "DECLINE" and r.snapshot["offer_amount"] == 2_000_000  # R4 judged on the capped amount


def test_income_too_low_for_minimum_loan_declines_via_r6():
    policy = make_policy(params={"R3": {"min_monthly_income": 1_000}})
    i = replace(BASE, declared_income=2_000, verified_income=2_000, requested_amount=100_000)
    r = evaluate(i, policy)
    assert r.outcome == "DECLINED"
    r6 = next(x for x in r.rule_results if x.rule_id == "R6")
    assert (r6.result, r6.code) == ("DECLINE", rc.ELIG_INCOME_LOW)
    messages = [m["message"] for m in applicant_reasons(r.outcome, r.reasons)]
    assert any("minimum loan amount" in m for m in messages)


def test_disabled_rules_are_skipped_and_recorded():
    policy = make_policy(disabled={"R5", "F2"})
    r = evaluate(replace(BASE, months_in_current_job=1, applications_24h_phone=9), policy)
    assert r.outcome == "APPROVED"
    results = {x.rule_id: x.result for x in r.rule_results}
    assert results["R5"] == results["F2"] == "SKIPPED"


def test_disabled_r6_never_caps():
    policy = make_policy(disabled={"R6"})
    i = replace(BASE, requested_amount=2_500_000, tenure_months=60)
    r = evaluate(i, policy)
    assert r.snapshot["offer_amount"] == 2_500_000 and rc.INFO_AMOUNT_CAPPED not in codes(r)


def test_configured_fail_outcome_is_respected():
    policy = make_policy(outcomes={"R5": "DECLINE"})
    assert evaluate(replace(BASE, months_in_current_job=1), policy).outcome == "DECLINED"


def test_thresholds_come_from_policy_not_code():
    strict = make_policy(params={"R2": {"approve_threshold": 800, "refer_floor": 700}})
    r = evaluate(BASE, strict)  # score 781
    assert (r.outcome, codes(r)) == ("REFERRED", [rc.ELIG_SCORE_BORDERLINE])
    assert r.snapshot["policy_version"] == strict.version


def test_reason_codes_complete_for_outcome():
    """The simulation assertion, checked on a spread of inputs."""
    variants = [
        BASE,
        replace(BASE, bureau=BureauData(available=False)),
        replace(BASE, aa_status="DECLINED", verified_income=None),
        replace(BASE, date_of_birth=date(2008, 1, 1)),
        replace(BASE, requested_amount=2_500_000, tenure_months=60, declared_income=100_000, verified_income=100_000),
    ]
    for i in variants:
        r = evaluate(i, POLICY)
        sev = {x.severity for x in r.reasons}
        if r.outcome == "DECLINED":
            assert rc.Severity.DECLINE in sev
        elif r.outcome == "REFERRED":
            assert rc.Severity.REFER in sev and rc.Severity.DECLINE not in sev
        else:
            assert sev <= {rc.Severity.INFO}
