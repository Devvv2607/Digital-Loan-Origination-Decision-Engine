"""Injectable clock. Every business timestamp comes from here so tests can move time."""

from datetime import UTC, datetime, timedelta

from fastapi import Request


class Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock(Clock):
    """A clock that only moves when told to. Used by tests and the simulation."""

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
