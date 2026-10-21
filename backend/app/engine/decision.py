"""Decision engine — evaluation sequence (docs/RULES.md §2):

1. Validate: if the bureau failed after retries, stop and REFER with SYS_BUREAU_UNAVAILABLE.
2. Resolve inputs: verified (AA) income, or declared income + DATA_INCOME_UNVERIFIED.
3. Fraud checks F2-F4 (F1 already ran at the PAN step).
4. Eligibility R1, R2, R3, R5.
5. Price and test affordability: score band -> rate -> EMI -> R4; if R6 caps the amount,
   recalculate EMI and run R4 on the capped amount.
6. Decide by precedence: any DECLINE -> DECLINED; else any REFER -> REFERRED; else APPROVED.

All applicable rules are evaluated (no short-circuit) so reason codes are complete.
`evaluate` is pure: no database, no clock.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.engine import reasons as rc
from app.engine.fraud import checks
from app.engine.policy import Policy
from app.engine.pricing import emi as calc_emi
from app.engine.pricing import rate_for_score
from app.engine.reasons import Severity
from app.engine.rules import r1_age, r2_credit_score, r3_min_income, r4_foir, r5_employment, r6_cap
from app.engine.types import DecisionInputs, RuleResult

EVALUATED_IDS = ("F2", "F3", "F4", "R1", "R2", "R3", "R4", "R5", "R6")


@dataclass
class Reason:
    code: str
    severity: Severity
    rule_id: str
    detail: str
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def sort_key(self) -> tuple[int, int]:
        return rc.priority(self.code, self.severity, self.rule_id)


@dataclass
class EngineResult:
    outcome: str
    reasons: list[Reason]
    rule_results: list[RuleResult]
    snapshot: dict[str, Any]

    @property
    def reason_codes(self) -> list[str]:
        return [r.code for r in self.reasons]

    @property
    def primary_reason_code(self) -> str | None:
        return self.reasons[0].code if self.reasons else None

    @property
    def explanations(self) -> dict[str, str]:
        return {r.code: r.detail for r in self.reasons}


def outcome_from(reasons: list[Reason]) -> str:
    severities = {r.severity for r in reasons}
    if Severity.DECLINE in severities:
        return "DECLINED"
    if Severity.REFER in severities:
        return "REFERRED"
    return "APPROVED"


def _ordered(reasons: list[Reason]) -> list[Reason]:
    """Sort by priority and keep one entry per code (the most severe one)."""
    seen: set[str] = set()
    out = []
    for r in sorted(reasons, key=lambda r: r.sort_key):
        if r.code not in seen:
            seen.add(r.code)
            out.append(r)
    return out


def _collect(result: RuleResult, reasons: list[Reason], context: dict[str, Any] | None = None) -> None:
    if result.code and result.severity is not None:
        reasons.append(Reason(result.code, result.severity, result.rule_id, result.detail or "", context or {}))


def evaluate(i: DecisionInputs, policy: Policy) -> EngineResult:
    reasons: list[Reason] = []
    results: list[RuleResult] = []
    snapshot: dict[str, Any] = {"inputs": i.snapshot(), "policy_version": policy.version}

    # 1. Validate provider responses. A missing bureau response is never a failed credit rule.
    if not i.bureau.available:
        reasons.append(Reason(rc.SYS_BUREAU_UNAVAILABLE, Severity.REFER, "SYS",
                              "Credit bureau did not respond after 3 attempts; credit rules were not evaluated."))
        results = [RuleResult(rid, "NOT_EVALUATED", detail="Stopped: bureau unavailable.") for rid in EVALUATED_IDS]
        return EngineResult("REFERRED", reasons, results, snapshot)

    # 2. Resolve inputs.
    if i.aa_status == "APPROVED" and i.verified_income is not None:
        income, income_source = i.verified_income, "AA"
    else:
        income, income_source = i.declared_income, "DECLARED"
        reasons.append(Reason(rc.DATA_INCOME_UNVERIFIED, Severity.REFER, "DATA",
                              "AA consent declined; declared income used and not verified."))
    existing_emis = i.bureau.existing_monthly_emis
    snapshot.update(income_used=income, income_source=income_source, existing_emis=existing_emis)

    def run(rule_id: str, fn, *args, context=None) -> RuleResult:
        if not policy.enabled(rule_id):
            res = RuleResult(rule_id, "SKIPPED", detail="Rule disabled in this policy version.")
        else:
            res = fn(*args)
        results.append(res)
        _collect(res, reasons, context)
        return res

    # 3. Fraud checks F2-F4.
    run("F2", checks.f2_velocity, i, policy.params("F2"))
    run("F3", checks.f3_identity, i, policy.params("F3"))
    run("F4", checks.f4_income, i, policy.params("F4"))

    # 4. Eligibility R1, R2, R3, R5.
    run("R1", r1_age, i, policy.params("R1"), policy.rule("R1").outcome_on_fail or "DECLINE")
    run("R2", r2_credit_score, i, policy.params("R2"))
    run("R3", r3_min_income, income, policy.params("R3"), policy.rule("R3").outcome_on_fail or "DECLINE")
    run("R5", r5_employment, i, policy.params("R5"), policy.rule("R5").outcome_on_fail or "REFER")

    # 5. Price and test affordability (R6 cap first, then R4 on the amount actually offered).
    pricing = policy.pricing
    score = None if i.bureau.ntc else i.bureau.score
    rate = rate_for_score(score, pricing)
    amount = i.requested_amount
    if policy.enabled("R6"):
        cap, amount = r6_cap(i.requested_amount, income, policy.params("R6"))
        if cap < pricing.loan_amount_min:
            amount = i.requested_amount
            r6 = RuleResult("R6", "DECLINE", rc.ELIG_AMOUNT_BELOW_MIN,
                            f"Income supports at most {rc.inr(cap)}, below the minimum loan {rc.inr(pricing.loan_amount_min)}.",
                            {"requested": i.requested_amount, "cap": cap})
            results.append(r6)
            _collect(r6, reasons)
        elif amount < i.requested_amount:
            r6 = RuleResult("R6", "INFO", rc.INFO_AMOUNT_CAPPED,
                            f"Requested {rc.inr(i.requested_amount)} exceeds the cap of "
                            f"{policy.params('R6').max_multiple_of_monthly_income:g}x income; counter-offer {rc.inr(amount)}.",
                            {"requested": i.requested_amount, "cap": cap})
            results.append(r6)
            _collect(r6, reasons, {"capped_amount": amount})
        else:
            results.append(RuleResult("R6", "PASS", value={"requested": i.requested_amount, "cap": cap}))
    else:
        results.append(RuleResult("R6", "SKIPPED", detail="Rule disabled in this policy version."))

    new_emi = calc_emi(amount, rate, i.tenure_months)
    r4 = run("R4", r4_foir, existing_emis, new_emi, income, policy.params("R4"))
    snapshot.update(
        annual_rate=str(rate), offer_amount=amount, requested_amount=i.requested_amount,
        tenure_months=i.tenure_months, emi=new_emi, foir=r4.value, amount_capped=amount < i.requested_amount,
    )

    ordered = _ordered(reasons)
    order = {rid: n for n, rid in enumerate(EVALUATED_IDS)}
    results.sort(key=lambda r: order.get(r.rule_id, 99))
    return EngineResult(outcome_from(ordered), ordered, results, snapshot)


def applicant_reasons(outcome: str, reasons: list[Reason]) -> list[dict[str, str | None]]:
    """Reasons an applicant may see: only those that drove the outcome, fraud collapsed to one
    neutral line, codes omitted for fraud."""
    wanted = {
        "DECLINED": {Severity.DECLINE},
        "REFERRED": {Severity.REFER, Severity.INFO},
        "APPROVED": {Severity.INFO},
    }[outcome]
    out: list[dict[str, str | None]] = []
    seen_messages: set[str] = set()
    for r in reasons:
        if r.severity not in wanted:
            continue
        message = rc.applicant_message(r.code, r.severity, r.context)
        if message in seen_messages:
            continue
        seen_messages.add(message)
        out.append({"code": None if rc.family(r.code) == "FRAUD" else r.code, "message": message})
    return out


def reasons_from_stored(reason_rows: list[dict[str, Any]]) -> list[Reason]:
    return [Reason(r["code"], Severity(r["severity"]), r["rule_id"], r.get("detail", ""), r.get("context", {}))
            for r in reason_rows]


def reasons_to_store(reasons: list[Reason]) -> list[dict[str, Any]]:
    return [{"code": r.code, "severity": r.severity.value, "rule_id": r.rule_id, "detail": r.detail,
             "context": r.context} for r in reasons]


def decimal_or_none(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None
