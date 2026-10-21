"""Product limits and journey timings.

Loan amount and tenure limits move into the versioned PRICING policy in Phase 3;
until then these constants are the single source of truth.
"""

from datetime import timedelta

LOAN_AMOUNT_MIN = 50_000
LOAN_AMOUNT_MAX = 2_500_000
TENURE_MONTHS_MIN = 12
TENURE_MONTHS_MAX = 60

OTP_LENGTH = 6
OTP_TTL = timedelta(minutes=5)                  # EC-02
OTP_MAX_WRONG_ATTEMPTS = 3                      # EC-01
OTP_LOCK_DURATION = timedelta(minutes=15)       # EC-01
OTP_MAX_SENDS_PER_WINDOW = 3                    # EC-02
OTP_SEND_WINDOW = timedelta(hours=1)

ABANDONMENT_PERIOD = timedelta(days=30)         # EC-14
OFFER_VALIDITY = timedelta(days=7)              # EC-15

IDEMPOTENCY_KEY_TTL = timedelta(hours=24)
