"""The mock bureau's score distribution for applicants without a registered fixture.

This is the "synthetic bureau-score population" that scripts/seed_policy_from_cutoff.py
calibrates R2 against (docs/RULES.md §6). It is a fixed, illustrative distribution,
not an estimate of any real bureau's scores.
"""

from statistics import NormalDist

SCORE_MIN = 300
SCORE_MAX = 900
SCORE_DISTRIBUTION = NormalDist(mu=720, sigma=75)
NTC_SHARE = 0.08  # share of hash-derived profiles with no credit history


def score_from_uniform(u: float) -> int:
    """Map a uniform draw in (0, 1) to a bureau score via the inverse CDF, clipped to 300-900."""
    u = min(max(u, 1e-9), 1 - 1e-9)
    return int(min(SCORE_MAX, max(SCORE_MIN, round(SCORE_DISTRIBUTION.inv_cdf(u)))))
