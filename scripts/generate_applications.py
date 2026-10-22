"""Generate exactly 500 synthetic loan applications with expected outcomes.

Each record carries a persona, the inputs the simulation will submit through the API, the
mock-provider fixture it registers, and an EXPECTED outcome and reason codes derived from the
persona definition (inputs are placed deliberately inside or outside the policy thresholds,
away from boundaries). Expectations are never computed by calling the decision engine; the
only engine-adjacent arithmetic is a standard EMI formula implemented independently below.

Thresholds and rate bands are read from backend/policy/seed_policy.json, because personas
are defined relative to the seeded policy (e.g. "score in the refer band").

Usage (repo root):  backend/.venv/Scripts/python scripts/generate_applications.py
Writes reports/synthetic_applications.json.
"""

import argparse
import json
import math
import random
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED_POLICY = ROOT / "backend" / "policy" / "seed_policy.json"
OUTPUT = ROOT / "reports" / "synthetic_applications.json"
GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20261022
TOTAL = 500

# Persona mix (DECISIONS.md D-29). Counts must sum to 500.
MIX = {
    "strong": 145,
    "borderline_score": 40,
    "new_to_credit": 30,
    "high_foir": 35,
    "low_income": 30,
    "age_ineligible": 25,
    "short_tenure": 30,
    "high_loan_to_income": 35,
    "duplicate_pan": 20,
    "velocity": 20,
    "identity_mismatch": 25,
    "income_mismatch": 25,
    "integration_timeout": 20,
    "aa_declined": 20,
}
assert sum(MIX.values()) == TOTAL

FIRST = ["Aarav", "Ananya", "Arjun", "Diya", "Ishaan", "Kavya", "Kabir", "Meera", "Nikhil", "Priya", "Rahul",
         "Riya", "Rohan", "Sanya", "Siddharth", "Tanvi", "Varun", "Zoya", "Aditya", "Neha", "Farhan", "Lakshmi"]
LAST = ["Agarwal", "Banerjee", "Chopra", "Desai", "Gupta", "Iyer", "Joshi", "Kapoor", "Kulkarni", "Mehta",
        "Menon", "Nair", "Patel", "Rao", "Reddy", "Saxena", "Sharma", "Singh", "Trivedi", "Verma", "Bose", "Pillai"]
ALT_FIRST = ["Bhavesh", "Chitra", "Devendra", "Gauri", "Harish", "Jyoti", "Manohar", "Omkar", "Pallavi", "Yamini"]
ALT_LAST = ["Dutta", "Ghosh", "Hegde", "Khanna", "Lal", "Mishra", "Oberoi", "Puri", "Thakur", "Wadia"]
EMPLOYERS = ["Example Systems Pvt Ltd", "Sample Retail Ltd", "Demo Logistics", "Placeholder Pharma", "Mock Textiles"]
PURPOSES = ["HOME_RENOVATION", "MEDICAL", "EDUCATION", "TRAVEL", "WEDDING", "DEBT_CONSOLIDATION", "OTHER"]
TENURES = [12, 24, 36, 48, 60]


# ---------------------------------------------------------------- policy-relative helpers

def load_policy() -> dict:
    seed = json.loads(SEED_POLICY.read_text(encoding="utf-8"))
    rules = {r["rule_id"]: r["parameters"] for r in seed["rules"]}
    return {"rules": rules, "version": seed["policy_version"]}


def annual_rate(score: int | None, pricing: dict) -> float:
    if score is not None:
        for band in sorted(pricing["rate_bands"], key=lambda b: b["min_score"], reverse=True):
            if score >= band["min_score"]:
                return band["annual_rate"]
    return pricing["fallback_rate"]


def emi(principal: float, annual_pct: float, months: int) -> float:
    """Standard reducing-balance EMI (independent of the engine's implementation)."""
    r = annual_pct / 1200
    return principal * r * (1 + r) ** months / ((1 + r) ** months - 1)


def similarity(a: str, b: str) -> float:
    norm = lambda s: " ".join(sorted(s.upper().split()))  # noqa: E731
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


class Gen:
    def __init__(self, seed: int, as_of: date):
        self.rng = random.Random(seed)
        self.as_of = as_of
        self.policy = load_policy()
        self.pans: set[str] = set()
        self.n = 0
        P = self.policy["rules"]
        self.approve, self.floor = P["R2"]["approve_threshold"], P["R2"]["refer_floor"]
        self.min_income = P["R3"]["min_monthly_income"]
        self.foir_pass, self.foir_refer = P["R4"]["pass_max"], P["R4"]["refer_max"]
        self.lti = P["R6"]["max_multiple_of_monthly_income"]
        self.round_to = P["R6"]["round_down_to"]
        self.pricing = P["PRICING"]

    # -- primitives
    def pan(self) -> str:
        L = "ABCDEFGHJKLMNOPQRSUVWYZ"  # no magic letters needed (fixtures win), but avoid lookalikes
        while True:
            p = "".join(self.rng.choice(L) for _ in range(3)) + "P" + self.rng.choice(L) + f"{self.rng.randrange(10_000):04d}" + self.rng.choice(L)
            if p not in self.pans:
                self.pans.add(p)
                return p

    def dob_for_age(self, years_lo: float, years_hi: float) -> date:
        age_days = self.rng.uniform(years_lo, years_hi) * 365.25
        return self.as_of - timedelta(days=int(age_days))

    def name(self) -> str:
        return f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}"

    def money(self, lo: float, hi: float, step: int = 500) -> int:
        return int(self.rng.uniform(lo, hi) // step * step)

    # -- a clean applicant who passes every rule with margin
    def clean(self, *, score_range=(700, 880), ntc=False, income_range=(40_000, 200_000), foir_range=(0.10, 0.40),
              age_range=(25.0, 50.0), tenure=None, amount_multiple=15) -> dict:
        score = None if ntc else self.rng.randint(*score_range)
        declared = self.money(*income_range)
        verified = int(round(declared * self.rng.uniform(0.92, 1.08), -2))
        months = tenure or self.rng.choice(TENURES)
        rate = annual_rate(score, self.pricing)
        cap = min(amount_multiple * min(declared, verified), self.pricing["loan_amount_max"])
        amount = max(self.pricing["loan_amount_min"], int(self.rng.uniform(0.2, 1.0) * cap // 10_000 * 10_000))
        while emi(amount, rate, months) > 0.35 * min(declared, verified) and amount > self.pricing["loan_amount_min"]:
            amount = max(self.pricing["loan_amount_min"], amount - 10_000)
        new_emi = emi(amount, rate, months)
        target = self.rng.uniform(*foir_range)
        existing = 0 if ntc else max(0, int((target * verified - new_emi) // 500 * 500))
        salaried = self.rng.random() < 0.7
        return {
            "full_name": self.name(),
            "dob": self.dob_for_age(*age_range),
            "salaried": salaried,
            "months_in_job": self.rng.randint(12, 120) if salaried else self.rng.randint(30, 180),
            "declared": declared, "verified": verified, "amount": amount, "tenure": months,
            "score": score, "ntc": ntc, "existing": existing, "rate": rate,
            "kyc_behaviour": "OK", "bureau_behaviour": "NTC" if ntc else "OK",
            "kyc_name": None, "kyc_dob": None, "aa_decision": "APPROVE",
        }

    def record(self, persona: str, a: dict, expected: str, codes: list[str], note: str, **extra) -> dict:
        self.n += 1
        pan = extra.pop("pan", None) or self.pan()
        details = {
            "full_name": a["full_name"],
            "date_of_birth": a["dob"].isoformat(),
            "employment_type": "SALARIED" if a["salaried"] else "SELF_EMPLOYED",
            "employer_name": self.rng.choice(EMPLOYERS),
            "months_in_current_job": a["months_in_job"],
            "declared_monthly_income": a["declared"],
            "loan_amount": a["amount"],
            "tenure_months": a["tenure"],
            "purpose": self.rng.choice(PURPOSES),
        }
        fixture = {
            "pan_name": a["full_name"],
            "pan_dob": a["dob"].isoformat(),
            "kyc": {"behaviour": a["kyc_behaviour"],
                    **({"name": a["kyc_name"]} if a["kyc_name"] else {}),
                    **({"dob": a["kyc_dob"].isoformat()} if a["kyc_dob"] else {})},
            "bureau": ({"behaviour": "OK", "score": a["score"], "existing_monthly_emis": a["existing"],
                        "active_loans": 0 if a["existing"] == 0 else 1 + a["existing"] // 8000}
                       if a["bureau_behaviour"] == "OK" else {"behaviour": a["bureau_behaviour"]}),
            "aa": {"average_monthly_income": a["verified"]},
        }
        rec = {
            "id": f"SIM-{self.n:04d}",
            "persona": persona,
            "phone": f"9001{self.n:06d}",
            "device_id": f"sim-device-{self.n:04d}",
            "pan": pan,
            "details": details,
            "fixture": fixture,
            "aa_decision": a["aa_decision"],
            "hold_offer": False,
            "duplicate_of": None,
            "expected_outcome": expected,
            "expected_reason_codes": sorted(codes),
            "expectation_note": note,
            "design": {"score": a["score"], "verified_income": a["verified"], "existing_emis": a["existing"],
                       "rate_band": a["rate"]},
        }
        rec.update(extra)
        return rec

    def capped(self, verified: int) -> int:
        return math.floor(self.lti * verified / self.round_to) * self.round_to

    # ---------------------------------------------------------------- personas
    def strong(self, n):
        out = []
        for i in range(n):
            a = self.clean()
            out.append(self.record("strong", a, "APPROVED", [], "All rules pass with margin.", hold_offer=i < 20))
        return out

    def borderline_score(self, n):
        out = []
        for _ in range(n):
            a = self.clean(score_range=(self.floor, self.approve - 1))
            out.append(self.record("borderline_score", a, "REFERRED", ["ELIG_SCORE_BORDERLINE"],
                                   f"Score in the refer band [{self.floor}, {self.approve})."))
        return out

    def new_to_credit(self, n):
        return [self.record("new_to_credit", self.clean(ntc=True), "REFERRED", ["ELIG_THIN_FILE"],
                            "Bureau has no credit history (NTC).") for _ in range(n)]

    def high_foir(self, n):
        out = []
        for i in range(n):
            refer = i < 20
            a = self.clean(foir_range=(0.10, 0.20))
            new_emi = emi(a["amount"], a["rate"], a["tenure"])
            target = self.rng.uniform(0.53, 0.57) if refer else self.rng.uniform(0.66, 0.85)
            a["existing"] = int((target * a["verified"] - new_emi) // 500 * 500)
            assert a["existing"] > 0
            out.append(self.record(
                "high_foir", a, "REFERRED" if refer else "DECLINED", ["ELIG_FOIR_HIGH"],
                f"FOIR ~{target:.0%}: {'refer band (50-60%]' if refer else 'above 60%'}."))
        return out

    def low_income(self, n):
        out = []
        for _ in range(n):
            a = self.clean(income_range=(12_000, 23_500), tenure=self.rng.choice([48, 60]))
            a["verified"] = min(int(round(a["declared"] * self.rng.uniform(0.97, 1.03), -2)), self.min_income - 500)
            a["amount"] = self.pricing["loan_amount_min"] + self.rng.randrange(0, 4) * 10_000
            a["existing"] = 0
            assert emi(a["amount"], a["rate"], a["tenure"]) <= 0.4 * a["verified"]
            assert a["amount"] <= self.capped(a["verified"])
            out.append(self.record("low_income", a, "DECLINED", ["ELIG_INCOME_LOW"],
                                   f"Verified income below ₹{self.min_income:,}."))
        return out

    def age_ineligible(self, n):
        out = []
        for i in range(n):
            young = i < 13
            if young:
                a = self.clean(age_range=(19.1, 20.8))
                note = "Under 21 today."
            else:
                a = self.clean(age_range=(56.5, 58.5), tenure=60)
                note = "Over 60 at maturity (age 56.5-58.5 + 60 months)."
            out.append(self.record("age_ineligible", a, "DECLINED", ["ELIG_AGE"], note))
        return out

    def short_tenure(self, n):
        out = []
        for i in range(n):
            a = self.clean()
            a["salaried"] = i % 2 == 0
            a["months_in_job"] = self.rng.randint(0, 5) if a["salaried"] else self.rng.randint(3, 23)
            out.append(self.record("short_tenure", a, "REFERRED", ["ELIG_EMPLOYMENT_TENURE"],
                                   "Below 6 months (salaried) or 24 months (self-employed)."))
        return out

    def high_loan_to_income(self, n):
        out = []
        for i in range(n):
            approve = i < 25
            a = self.clean(income_range=(40_000, 100_000), score_range=(750, 880), tenure=60)
            cap = self.capped(a["verified"])
            a["amount"] = min(int(cap * self.rng.uniform(1.15, 1.6) // 10_000 * 10_000), self.pricing["loan_amount_max"])
            assert a["amount"] > cap
            cap_emi = emi(cap, a["rate"], 60)
            if approve:
                room = 0.47 * a["verified"] - cap_emi
                a["existing"] = max(0, int(room * self.rng.uniform(0, 0.8) // 500 * 500))
                foir = (a["existing"] + cap_emi) / a["verified"]
                assert foir < 0.48, foir
                out.append(self.record("high_loan_to_income", a, "APPROVED", ["INFO_AMOUNT_CAPPED"],
                                       f"Request above {self.lti:g}x income; counter-offer at ₹{cap:,} passes FOIR (~{foir:.0%})."))
            else:
                target = self.rng.uniform(0.53, 0.57)
                a["existing"] = int((target * a["verified"] - cap_emi) // 500 * 500)
                assert a["existing"] > 0
                out.append(self.record("high_loan_to_income", a, "REFERRED", ["ELIG_FOIR_HIGH", "INFO_AMOUNT_CAPPED"],
                                       f"Request above {self.lti:g}x income; FOIR on the capped amount ~{target:.0%} (refer band)."))
        return out

    def duplicate_pan(self, n, held: list[dict]):
        out = []
        for i in range(n):
            original = held[i]
            a = self.clean()
            out.append(self.record("duplicate_pan", a, "BLOCKED_AT_PAN", ["FRAUD_DUPLICATE_PAN"],
                                   f"Reuses the PAN of {original['id']}, whose offer is still open (F1).",
                                   pan=original["pan"], duplicate_of=original["id"]))
            out[-1]["fixture"] = None  # the original's fixture stays in place
        return out

    def velocity(self, n):
        out = []
        groups = n // 5
        for g in range(groups):
            shared_phone = g < groups // 2
            for pos in range(5):
                a = self.clean()
                flagged = pos >= 3
                rec = self.record(
                    "velocity", a, "REFERRED" if flagged else "APPROVED", ["FRAUD_VELOCITY"] if flagged else [],
                    f"Application {pos + 1} of 5 from one {'phone' if shared_phone else 'device'} in 24h "
                    f"({'over' if flagged else 'within'} the limit of 3).")
                if shared_phone:
                    rec["phone"] = f"9002{g:06d}"
                    rec["session_group"] = f"velocity-phone-{g}"
                else:
                    rec["device_id"] = f"sim-shared-device-{g}"
                out.append(rec)
        return out

    def identity_mismatch(self, n):
        out = []
        for i in range(n):
            a = self.clean()
            if i < 15:
                while True:
                    other = f"{self.rng.choice(ALT_FIRST)} {self.rng.choice(ALT_LAST)}"
                    if similarity(other, a["full_name"]) < 0.6:
                        break
                a["kyc_name"] = other
                note = "e-KYC name is a different person (similarity < 0.6)."
            else:
                a["kyc_dob"] = a["dob"] + timedelta(days=400)
                note = "e-KYC date of birth differs from PAN by 400 days."
            out.append(self.record("identity_mismatch", a, "REFERRED", ["FRAUD_IDENTITY_MISMATCH"], note))
        return out

    def income_mismatch(self, n):
        out = []
        for _ in range(n):
            a = self.clean(income_range=(40_000, 120_000))
            factor = self.rng.uniform(0.45, 0.65)
            a["declared"] = int(round(a["verified"] / factor, -2))
            out.append(self.record("income_mismatch", a, "REFERRED", ["FRAUD_INCOME_MISMATCH"],
                                   f"Declared income ~{1 / factor - 1:.0%} above verified (difference {1 - factor:.0%} of declared, > 30%)."))
        return out

    def integration_timeout(self, n):
        out = []
        for i in range(n):
            a = self.clean()
            if i < n // 2:
                a["kyc_behaviour"] = "TIMEOUT"
                out.append(self.record("integration_timeout", a, "KYC_PENDING", [],
                                       "e-KYC times out on all 3 attempts; application waits in KYC_PENDING (EC-05)."))
            else:
                a["bureau_behaviour"] = "TIMEOUT"
                out.append(self.record("integration_timeout", a, "REFERRED", ["SYS_BUREAU_UNAVAILABLE"],
                                       "Bureau times out on all 3 attempts (EC-07)."))
        return out

    def aa_declined(self, n):
        out = []
        for _ in range(n):
            a = self.clean()
            a["aa_decision"] = "DECLINE"
            out.append(self.record("aa_declined", a, "REFERRED", ["DATA_INCOME_UNVERIFIED"],
                                   "AA consent declined; declared income passes R3/R4 (EC-09)."))
        return out


def generate(seed: int, as_of: date) -> dict:
    g = Gen(seed, as_of)
    strong = g.strong(MIX["strong"])
    held = [r for r in strong if r["hold_offer"]]
    blocks = [
        strong,
        g.borderline_score(MIX["borderline_score"]),
        g.new_to_credit(MIX["new_to_credit"]),
        g.high_foir(MIX["high_foir"]),
        g.low_income(MIX["low_income"]),
        g.age_ineligible(MIX["age_ineligible"]),
        g.short_tenure(MIX["short_tenure"]),
        g.high_loan_to_income(MIX["high_loan_to_income"]),
        g.identity_mismatch(MIX["identity_mismatch"]),
        g.income_mismatch(MIX["income_mismatch"]),
        g.integration_timeout(MIX["integration_timeout"]),
        g.aa_declined(MIX["aa_declined"]),
    ]
    singles = [r for b in blocks for r in b]
    g.rng.shuffle(singles)
    # Held originals first (their offers must be open before duplicates arrive), velocity groups kept
    # contiguous, duplicates last.
    held_ids = {r["id"] for r in held}
    ordered = [r for r in singles if r["id"] in held_ids] + [r for r in singles if r["id"] not in held_ids]
    ordered += g.velocity(MIX["velocity"])
    ordered += g.duplicate_pan(MIX["duplicate_pan"], held)
    assert len(ordered) == TOTAL and len({r["id"] for r in ordered}) == TOTAL
    return {
        "metadata": {
            "generator_version": GENERATOR_VERSION,
            "random_seed": seed,
            "as_of_date": as_of.isoformat(),
            "policy_version_assumed": g.policy["version"],
            "count": TOTAL,
            "persona_mix": MIX,
            "expected_outcomes": dict(Counter(r["expected_outcome"] for r in ordered)),
            "note": "Synthetic data only. Expected outcomes come from persona definitions, not from the engine.",
        },
        "applications": ordered,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(UTC).date(),
                    help="Decision date the ages are designed around (default: today, UTC).")
    ap.add_argument("--output", type=Path, default=OUTPUT)
    args = ap.parse_args()
    data = generate(args.seed, args.as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    m = data["metadata"]
    print(f"Wrote {m['count']} applications to {args.output} (seed {m['random_seed']}, as of {m['as_of_date']})")
    for k, v in sorted(m["expected_outcomes"].items()):
        print(f"  expected {k:<15} {v}")


if __name__ == "__main__":
    main()
