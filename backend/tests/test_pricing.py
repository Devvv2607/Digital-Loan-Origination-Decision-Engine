"""EMI, schedule, APR and KFS invariants (docs/RULES.md §7).

Reference values:
- EMIs match the figures published by standard reducing-balance EMI calculators
  (e.g. 1,00,000 at 12% for 12 months = 8,885).
- APRs were computed outside the engine with an independent schedule implementation and a
  Newton-Raphson solver (the engine uses bisection), then recorded here to 4 decimals.
"""

from decimal import Decimal

import pytest

from app.engine.policy import PricingParams, RateBand
from app.engine.pricing import apr, emi, quote, rate_for_score, schedule

EMI_REFERENCES = [
    # principal, annual %, months, EMI
    (100_000, 12, 12, 8_885),
    (100_000, 10, 12, 8_792),
    (500_000, 10.5, 60, 10_747),
    (1_000_000, 11, 60, 21_742),
    (500_000, 12.99, 36, 16_845),
    (200_000, 21.99, 24, 10_375),
]

APR_REFERENCES = [
    # principal, annual %, months, fee rate, total repayment, APR %   (case)
    (100_000, 12, 12, 0.00, 106_619, Decimal("12.0009")),        # zero fee, short tenure
    (100_000, 12, 12, 0.02, 106_619, Decimal("15.8555")),        # short tenure
    (500_000, 12.99, 36, 0.02, 606_405, Decimal("14.4095")),     # typical
    (200_000, 21.99, 24, 0.10, 248_988, Decimal("33.3218")),     # high fee
    (1_000_000, 11, 60, 0.02, 1_304_550, Decimal("11.8844")),    # long tenure
]


@pytest.mark.parametrize(("principal", "rate", "months", "expected"), EMI_REFERENCES)
def test_emi_matches_reference(principal, rate, months, expected):
    assert emi(principal, rate, months) == expected


@pytest.mark.parametrize(("principal", "rate", "months", "fee", "total", "expected_apr"), APR_REFERENCES)
def test_apr_matches_independent_reference(principal, rate, months, fee, total, expected_apr):
    q = quote(principal, rate, months, fee)
    assert q.total_repayment == total
    assert abs(q.apr - expected_apr) < Decimal("0.001")


@pytest.mark.parametrize(("principal", "rate", "months", "fee", "_total", "_apr"), APR_REFERENCES)
def test_kfs_consistency_invariants(principal, rate, months, fee, _total, _apr):
    q = quote(principal, rate, months, fee)
    assert sum(row.principal for row in q.schedule) == principal          # principal sums to loan
    assert q.total_repayment == sum(row.emi for row in q.schedule)        # total = sum of EMIs
    assert q.net_disbursal == principal - q.processing_fee                # net = loan - fee
    assert q.total_interest == sum(row.interest for row in q.schedule)
    assert q.total_cost == q.total_interest + q.processing_fee
    assert q.schedule[-1].balance == 0
    assert all(row.emi == q.emi for row in q.schedule[:-1])               # level EMIs until the last
    assert abs(q.schedule[-1].emi - q.emi) <= months                       # last EMI absorbs rounding only
    if fee > 0:
        assert q.apr > q.annual_rate                                       # APR > rate when fee > 0
    else:
        assert abs(q.apr - q.annual_rate) < Decimal("0.01")


def test_first_month_interest_is_on_full_principal():
    first = schedule(500_000, 12.99, 36)[0]
    assert (first.interest, first.principal, first.balance) == (5_413, 11_432, 488_568)  # half-up rounding


def test_zero_rate_and_single_month_edge_cases():
    assert emi(120_000, 0, 12) == 10_000
    rows = schedule(50_000, 12, 1)
    assert len(rows) == 1 and rows[0].principal == 50_000 and rows[0].interest == 500


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        emi(0, 12, 12)
    with pytest.raises(ValueError):
        apr(0, [100])
    with pytest.raises(ValueError):
        apr(1_000, [10, 10])  # payments don't cover the loan


PRICING = PricingParams(
    rate_bands=[RateBand(min_score=800, annual_rate=10.99), RateBand(min_score=750, annual_rate=12.99),
                RateBand(min_score=700, annual_rate=14.99), RateBand(min_score=650, annual_rate=17.99)],
    fallback_rate=21.99, processing_fee_rate=0.02, loan_amount_min=50_000, loan_amount_max=2_500_000,
    tenure_months_min=12, tenure_months_max=60, offer_validity_days=7, cooling_off_days=3,
    grievance_contact="grievance@lendwise.example",
)


@pytest.mark.parametrize(
    ("score", "rate"),
    [(900, "10.99"), (800, "10.99"), (799, "12.99"), (750, "12.99"), (749, "14.99"), (700, "14.99"),
     (650, "17.99"), (649, "21.99"), (None, "21.99")],
)
def test_score_band_to_rate(score, rate):
    assert rate_for_score(score, PRICING) == Decimal(rate)
