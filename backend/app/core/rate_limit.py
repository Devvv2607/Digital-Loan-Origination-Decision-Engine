"""Simple in-memory sliding-window rate limiter (per client IP, per bucket).

Good enough for a single-instance demo. Technical limits only; business limits
such as the OTP resend cap live in the services and are never relaxed.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.errors import AppError

# bucket -> (max requests, window seconds)
LIMITS: dict[str, tuple[int, int]] = {
    "otp_send": (5, 60),
    "otp_verify": (10, 60),
    "login": (5, 60),
    "app_create": (10, 60),
    "mock": (30, 60),
}

PROFILE_MULTIPLIER = {"default": 1, "simulation": 1000}


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, bucket: str, key: str, limit: int, window_s: int) -> float | None:
        """Record a hit. Returns seconds to wait if the limit is exceeded, else None."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[(bucket, key)]
            while q and now - q[0] >= window_s:
                q.popleft()
            if len(q) >= limit:
                return window_s - (now - q[0])
            q.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def rate_limit(bucket: str):
    """FastAPI dependency factory: `Depends(rate_limit("otp_send"))`."""

    def dependency(request: Request) -> None:
        profile = request.app.state.settings.rate_limit_profile
        if profile == "off":
            return
        limit, window = LIMITS[bucket]
        limit *= PROFILE_MULTIPLIER[profile]
        client = request.client.host if request.client else "unknown"
        wait = request.app.state.rate_limiter.hit(bucket, client, limit, window)
        if wait is not None:
            retry_after = max(1, int(wait) + 1)
            raise AppError(
                429,
                "RATE_LIMITED",
                "Too many requests. Please slow down and try again shortly.",
                {"retry_after_seconds": retry_after},
                headers={"Retry-After": str(retry_after)},
            )

    return dependency
