"""Reason codes: five distinct families, priority order, and applicant-facing wording.

SYS_*   technical failure          DATA_*  missing or unverified data
FRAUD_* fraud signal               ELIG_*  credit policy
INFO_*  informational (e.g. counter-offer)
"""

from enum import StrEnum


class Severity(StrEnum):
    DECLINE = "DECLINE"
    REFER = "REFER"
    INFO = "INFO"


SYS_BUREAU_UNAVAILABLE = "SYS_BUREAU_UNAVAILABLE"
DATA_INCOME_UNVERIFIED = "DATA_INCOME_UNVERIFIED"
FRAUD_DUPLICATE_PAN = "FRAUD_DUPLICATE_PAN"
FRAUD_VELOCITY = "FRAUD_VELOCITY"
FRAUD_IDENTITY_MISMATCH = "FRAUD_IDENTITY_MISMATCH"
FRAUD_INCOME_MISMATCH = "FRAUD_INCOME_MISMATCH"
ELIG_AGE = "ELIG_AGE"
ELIG_SCORE_LOW = "ELIG_SCORE_LOW"
ELIG_SCORE_BORDERLINE = "ELIG_SCORE_BORDERLINE"
ELIG_THIN_FILE = "ELIG_THIN_FILE"
ELIG_INCOME_LOW = "ELIG_INCOME_LOW"
ELIG_FOIR_HIGH = "ELIG_FOIR_HIGH"
ELIG_EMPLOYMENT_TENURE = "ELIG_EMPLOYMENT_TENURE"
INFO_AMOUNT_CAPPED = "INFO_AMOUNT_CAPPED"

ALL_CODES = {
    SYS_BUREAU_UNAVAILABLE, DATA_INCOME_UNVERIFIED, FRAUD_DUPLICATE_PAN, FRAUD_VELOCITY,
    FRAUD_IDENTITY_MISMATCH, FRAUD_INCOME_MISMATCH, ELIG_AGE, ELIG_SCORE_LOW, ELIG_SCORE_BORDERLINE,
    ELIG_THIN_FILE, ELIG_INCOME_LOW, ELIG_FOIR_HIGH, ELIG_EMPLOYMENT_TENURE, INFO_AMOUNT_CAPPED,
}

# Rule order used to break ties inside a priority group.
RULE_ORDER = ["SYS", "F2", "F3", "F4", "DATA", "R1", "R2", "R3", "R4", "R5", "R6"]


def family(code: str) -> str:
    return code.split("_", 1)[0]


def priority(code: str, severity: Severity, rule_id: str) -> tuple[int, int]:
    """Primary reason ordering (docs/RULES.md §5):
    DECLINE ELIG -> SYS -> FRAUD -> DATA -> REFER ELIG -> INFO."""
    fam = family(code)
    if fam == "ELIG" and severity == Severity.DECLINE:
        group = 0
    elif fam == "SYS":
        group = 1
    elif fam == "FRAUD":
        group = 2
    elif fam == "DATA":
        group = 3
    elif fam == "ELIG":
        group = 4
    else:
        group = 5
    return group, RULE_ORDER.index(rule_id) if rule_id in RULE_ORDER else 99


GENERIC_REVIEW = "We need to review a few details."


def inr(amount: int) -> str:
    """Indian digit grouping: 1684000 -> '₹16,84,000'."""
    s = str(abs(int(amount)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    return ("-₹" if amount < 0 else "₹") + s


def applicant_message(code: str, severity: Severity, context: dict | None = None) -> str:
    """Polite, non-technical wording. Fraud reasoning is never exposed."""
    context = context or {}
    if family(code) == "FRAUD":
        return GENERIC_REVIEW
    if code == ELIG_FOIR_HIGH:
        return (
            "Your existing repayments are too high relative to your income for this loan."
            if severity == Severity.DECLINE
            else "Your existing repayments are on the high side, so our team will review your application."
        )
    if code == ELIG_INCOME_LOW and context.get("below_minimum_loan"):
        return "Based on your income, we can't offer the minimum loan amount right now."
    if code == INFO_AMOUNT_CAPPED:
        return (
            f"Based on your income, we can offer up to {inr(context.get('capped_amount', 0))} "
            "instead of the amount you asked for."
        )
    return {
        ELIG_AGE: "You don't meet our age criteria for this loan and tenure.",
        ELIG_SCORE_LOW: "Based on your credit history, we can't offer you a loan right now.",
        ELIG_SCORE_BORDERLINE: "Our team will take a closer look at your credit history.",
        ELIG_THIN_FILE: "You're new to credit, so our team will review your application.",
        ELIG_INCOME_LOW: "Your monthly income is below the minimum for this loan.",
        ELIG_EMPLOYMENT_TENURE: "Our team will review your employment details.",
        DATA_INCOME_UNVERIFIED: "Without bank data we need to review your income manually.",
        SYS_BUREAU_UNAVAILABLE: "Your application needs a quick review. We'll update you soon.",
    }[code]
