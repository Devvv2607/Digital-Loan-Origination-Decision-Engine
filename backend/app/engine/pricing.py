"""Risk-based pricing, EMI, repayment schedule and APR (docs/RULES.md §7).

Assumptions (also printed on the KFS screen):
1. The processing fee is deducted from the disbursed amount, not financed.
2. EMIs are monthly, paid in arrears.
3. Amounts are rounded to the nearest rupee (half up); the final EMI absorbs rounding differences.
4. No GST, insurance or other charges are modelled.
5. APR = 12 x the monthly IRR of the net disbursal against the EMI schedule.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, localcontext

from app.engine.policy import PricingParams

ASSUMPTIONS = [
    "Processing fee is deducted from disbursal, not financed.",
    "EMIs are monthly in arrears (first EMI one month after disbursal).",
    "Amounts are rounded to the nearest rupee; the final EMI absorbs rounding differences.",
    "No GST, insurance or other charges are modelled.",
    "APR is the annualised (x12) monthly internal rate of return of the net disbursal against the EMI schedule.",
]

_ONE = Decimal(1)


def _rupees(value: Decimal) -> int:
    return int(value.quantize(_ONE, rounding=ROUND_HALF_UP))


def _monthly_rate(annual_rate_pct: Decimal | float) -> Decimal:
    return Decimal(str(annual_rate_pct)) / Decimal(1200)


def rate_for_score(score: int | None, pricing: PricingParams) -> Decimal:
    """Highest band whose min_score the score reaches; NTC/unavailable/below all bands -> fallback."""
    if score is not None:
        for band in sorted(pricing.rate_bands, key=lambda b: b.min_score, reverse=True):
            if score >= band.min_score:
                return Decimal(str(band.annual_rate))
    return Decimal(str(pricing.fallback_rate))


def emi(principal: int, annual_rate_pct: Decimal | float, months: int) -> int:
    """Standard reducing-balance EMI, rounded half up to the rupee."""
    if principal <= 0 or months <= 0:
        raise ValueError("principal and months must be positive")
    with localcontext() as ctx:
        ctx.prec = 40
        r = _monthly_rate(annual_rate_pct)
        if r == 0:
            return _rupees(Decimal(principal) / months)
        growth = (1 + r) ** months
        return _rupees(Decimal(principal) * r * growth / (growth - 1))


@dataclass(frozen=True)
class Instalment:
    month: int
    emi: int
    interest: int
    principal: int
    balance: int

    def to_dict(self) -> dict[str, int]:
        return {"month": self.month, "emi": self.emi, "interest": self.interest,
                "principal": self.principal, "balance": self.balance}


def schedule(principal: int, annual_rate_pct: Decimal | float, months: int) -> list[Instalment]:
    level_emi = emi(principal, annual_rate_pct, months)
    r = _monthly_rate(annual_rate_pct)
    balance = principal
    rows: list[Instalment] = []
    with localcontext() as ctx:
        ctx.prec = 40
        for month in range(1, months + 1):
            interest = _rupees(Decimal(balance) * r)
            if month == months:
                principal_part = balance  # final EMI absorbs rounding
                payment = principal_part + interest
            else:
                principal_part = level_emi - interest
                payment = level_emi
            balance -= principal_part
            rows.append(Instalment(month, payment, interest, principal_part, balance))
    return rows


def apr(net_disbursal: int, payments: list[int], tolerance: float = 1e-12) -> Decimal:
    """Annualised rate (percent, x12 convention) at which PV(payments) == net disbursal. Bisection."""
    if net_disbursal <= 0 or not payments:
        raise ValueError("net_disbursal must be positive and payments non-empty")

    def pv(i: float) -> float:
        return sum(p / (1 + i) ** k for k, p in enumerate(payments, start=1))

    lo, hi = 0.0, 1.0
    if pv(lo) < net_disbursal:
        raise ValueError("payments do not cover the net disbursal; APR would be negative")
    for _ in range(200):
        mid = (lo + hi) / 2
        if pv(mid) > net_disbursal:
            lo = mid
        else:
            hi = mid
        if hi - lo < tolerance:
            break
    return Decimal(str(round(12 * 100 * (lo + hi) / 2, 6)))


@dataclass(frozen=True)
class Quote:
    loan_amount: int
    tenure_months: int
    annual_rate: Decimal
    emi: int
    processing_fee: int
    net_disbursal: int
    total_interest: int
    total_repayment: int
    total_cost: int
    apr: Decimal
    schedule: list[Instalment] = field(repr=False)


def quote(principal: int, annual_rate_pct: Decimal | float, months: int, fee_rate: float) -> Quote:
    rows = schedule(principal, annual_rate_pct, months)
    fee = _rupees(Decimal(principal) * Decimal(str(fee_rate)))
    total_repayment = sum(r.emi for r in rows)
    total_interest = total_repayment - principal
    net = principal - fee
    return Quote(
        loan_amount=principal,
        tenure_months=months,
        annual_rate=Decimal(str(annual_rate_pct)),
        emi=rows[0].emi,
        processing_fee=fee,
        net_disbursal=net,
        total_interest=total_interest,
        total_repayment=total_repayment,
        total_cost=total_interest + fee,
        apr=apr(net, [r.emi for r in rows]),
        schedule=rows,
    )
