"""Application state machine.

Every state change goes through `transition()`, which validates it against
ALLOWED_TRANSITIONS and writes an `application_events` row in the same database
transaction. Callers commit; nothing here commits on its own.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Application, ApplicationEvent
from app.state_machine.states import (
    ALLOWED_TRANSITIONS,
    OFFER_TRANSITIONS,
    AppState,
    EventType,
    OfferStatus,
)


class InvalidTransitionError(AppError):
    def __init__(self, from_state: str | None, to_state: str, kind: str = "application"):
        super().__init__(
            409,
            "INVALID_STATE_TRANSITION",
            "This action isn't available at the current step.",
            {"kind": kind, "from_state": from_state, "to_state": to_state},
        )
        self.from_state = from_state
        self.to_state = to_state


def can_transition(from_state: AppState | str, to_state: AppState | str) -> bool:
    try:
        return AppState(to_state) in ALLOWED_TRANSITIONS[AppState(from_state)]
    except ValueError:
        return False


def record_event(
    db: Session,
    application: Application,
    *,
    event_type: EventType,
    actor: str,
    now: datetime,
    from_state: str | None = None,
    to_state: str | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ApplicationEvent:
    event = ApplicationEvent(
        application_id=application.id,
        event_type=event_type.value,
        from_state=from_state,
        to_state=to_state,
        actor=actor,
        reason=reason,
        metadata_=metadata or {},
        created_at=now,
    )
    db.add(event)
    return event


def record_creation(db: Session, application: Application, *, actor: str, now: datetime) -> ApplicationEvent:
    """The only way into the machine: (none) -> DRAFT."""
    if application.state != AppState.DRAFT:
        raise InvalidTransitionError(None, application.state)
    return record_event(
        db,
        application,
        event_type=EventType.STATE_CHANGE,
        from_state=None,
        to_state=AppState.DRAFT.value,
        actor=actor,
        reason="CREATED",
        now=now,
    )


def transition(
    db: Session,
    application: Application,
    to_state: AppState,
    *,
    actor: str,
    now: datetime,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ApplicationEvent:
    from_state = application.state
    if not can_transition(from_state, to_state):
        raise InvalidTransitionError(from_state, to_state)
    application.state = to_state.value
    application.state_changed_at = now
    application.updated_at = now
    return record_event(
        db,
        application,
        event_type=EventType.STATE_CHANGE,
        from_state=from_state,
        to_state=to_state.value,
        actor=actor,
        reason=reason,
        metadata=metadata,
        now=now,
    )


def check_offer_transition(from_status: OfferStatus | str, to_status: OfferStatus) -> None:
    if to_status not in OFFER_TRANSITIONS[OfferStatus(from_status)]:
        raise InvalidTransitionError(str(from_status), to_status.value, kind="offer")


def illegal_transitions_in_log(events: Iterable[ApplicationEvent | dict]) -> list[str]:
    """Return a description of every illegal step in an event log (empty list = valid).

    Checks STATE_CHANGE rows only: the first must be (none) -> DRAFT, every later
    one must start where the previous ended and be an allowed transition.
    """

    def get(e, name):
        return e[name] if isinstance(e, dict) else getattr(e, name)

    problems: list[str] = []
    current: str | None = None
    first = True
    for e in events:
        if get(e, "event_type") != EventType.STATE_CHANGE:
            continue
        frm, to = get(e, "from_state"), get(e, "to_state")
        if first:
            if frm is not None or to != AppState.DRAFT:
                problems.append(f"first transition must be (none)->DRAFT, got {frm}->{to}")
            first = False
        elif frm != current:
            problems.append(f"gap: previous state {current}, next event starts at {frm}")
        elif not can_transition(frm, to):
            problems.append(f"illegal transition {frm}->{to}")
        current = to
    if first:
        problems.append("no state transitions recorded")
    return problems
