"""Injectable clock. Every business timestamp comes from here so tests can move time."""

import time
from datetime import UTC, datetime, timedelta

from fastapi import Request


class Clock:
    kind = "system"

    def now(self) -> datetime:
        return datetime.now(UTC)


class AnchoredClock(Clock):
    """Starts at a fixed instant and then advances in real time.

    Used to run the simulation (and the e2e test) "as of" a fixed date, so age-dependent
    cases never expire, while durations between events stay real.
    """

    kind = "anchored"

    def __init__(self, start: datetime):
        if start.tzinfo is None:
            raise ValueError("AnchoredClock needs a timezone-aware datetime")
        self._start = start
        self._t0 = time.monotonic()

    def now(self) -> datetime:
        return self._start + timedelta(seconds=time.monotonic() - self._t0)


class FrozenClock(Clock):
    """A clock that only moves when told to. Used by tests."""

    kind = "frozen"

    def __init__(self, start: datetime):
        if start.tzinfo is None:
            raise ValueError("FrozenClock needs a timezone-aware datetime")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs) -> datetime:
        self._now += timedelta(**kwargs)
        return self._now

    def set(self, value: datetime) -> None:
        self._now = value


def get_clock(request: Request) -> Clock:
    return request.app.state.clock
