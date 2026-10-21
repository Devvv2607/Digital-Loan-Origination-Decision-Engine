"""Journey timings. Loan amount/tenure limits, offer validity and cooling-off live in the
versioned PRICING policy (backend/policy/seed_policy.json) so they can change without a deploy.
"""

from datetime import timedelta

OTP_LENGTH = 6
OTP_TTL = timedelta(minutes=5)                  # EC-02
OTP_MAX_WRONG_ATTEMPTS = 3                      # EC-01
OTP_LOCK_DURATION = timedelta(minutes=15)       # EC-01
OTP_MAX_SENDS_PER_WINDOW = 3                    # EC-02
OTP_SEND_WINDOW = timedelta(hours=1)

ABANDONMENT_PERIOD = timedelta(days=30)         # EC-14

IDEMPOTENCY_KEY_TTL = timedelta(hours=24)
