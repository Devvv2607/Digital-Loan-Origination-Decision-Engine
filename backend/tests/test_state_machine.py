"""State machine: exactly 8 states, the 11 allowed transitions, and rejection of the other 53."""

import itertools
import uuid

import pytest
from sqlalchemy import select

from app.models import Applicant, Application, ApplicationEvent
from app.state_machine.machine import (
    InvalidTransitionError,
    can_transition,
    check_offer_transition,
    illegal_transitions_in_log,
    record_creation,
    transition,
)
from app.state_machine.states import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    AppState,
    EventType,
    OfferStatus,
)
from tests.conftest import START

EXPECTED_ALLOWED = {
    (AppState.DRAFT, AppState.KYC_PENDING),
    (AppState.DRAFT, AppState.EXPIRED),
    (AppState.KYC_PENDING, AppState.UNDER_ASSESSMENT),
    (AppState.KYC_PENDING, AppState.EXPIRED),
    (AppState.UNDER_ASSESSMENT, AppState.APPROVED),
    (AppState.UNDER_ASSESSMENT, AppState.REFERRED),
    (AppState.UNDER_ASSESSMENT, AppState.DECLINED),
    (AppState.REFERRED, AppState.APPROVED),
    (AppState.REFERRED, AppState.DECLINED),
    (AppState.APPROVED, AppState.DISBURSED),
    (AppState.APPROVED, AppState.EXPIRED),
}
ALL_PAIRS = list(itertools.product(AppState, AppState))


def make_application(db, state: AppState) -> Application:
    applicant = Applicant(phone_hash=uuid.uuid4().hex, phone_last4="0001", created_at=START)
    db.add(applicant)
    db.flush()
    app = Application(
        applicant_id=applicant.id,
        state=state.value,
        pan_status="NOT_STARTED",
        kyc_status="NOT_STARTED",
        aa_status="NOT_STARTED",
        created_at=START,
        updated_at=START,
        last_activity_at=START,
        state_changed_at=START,
    )
    db.add(app)
    db.flush()
    return app


def events_for(db, app):
    return db.scalars(
        select(ApplicationEvent).where(ApplicationEvent.application_id == app.id).order_by(ApplicationEvent.seq)
    ).all()


def test_exactly_eight_states_and_three_terminal():
    assert len(AppState) == 8
    assert TERMINAL_STATES == {AppState.DECLINED, AppState.DISBURSED, AppState.EXPIRED}


def test_allowed_transition_table_matches_spec():
    actual = {(f, t) for f, targets in ALLOWED_TRANSITIONS.items() for t in targets}
    assert actual == EXPECTED_ALLOWED
    assert len(ALL_PAIRS) - len(actual) == 53


@pytest.mark.parametrize(("from_state", "to_state"), sorted(EXPECTED_ALLOWED))
def test_allowed_transition_changes_state_and_logs_event(db_session, from_state, to_state):
    app = make_application(db_session, from_state)
    later = START.replace(hour=11)

    transition(db_session, app, to_state, actor="system", reason="TEST", now=later, metadata={"k": "v"})
    db_session.flush()

    assert app.state == to_state
    assert app.state_changed_at == later
    [event] = events_for(db_session, app)
    assert (event.event_type, event.from_state, event.to_state) == (
        EventType.STATE_CHANGE,
        from_state,
        to_state,
    )
    assert (event.actor, event.reason, event.metadata_, event.created_at) == ("system", "TEST", {"k": "v"}, later)


@pytest.mark.parametrize(
    ("from_state", "to_state"), [p for p in ALL_PAIRS if p not in EXPECTED_ALLOWED]
)
def test_illegal_transition_rejected_without_side_effects(db_session, from_state, to_state):
    app = make_application(db_session, from_state)

    with pytest.raises(InvalidTransitionError) as exc:
        transition(db_session, app, to_state, actor="system", now=START)

    assert exc.value.status_code == 409
    assert exc.value.error_code == "INVALID_STATE_TRANSITION"
    assert app.state == from_state
    db_session.flush()
    assert events_for(db_session, app) == []


def test_terminal_states_have_no_exit():
    for state in TERMINAL_STATES:
        assert not any(can_transition(state, t) for t in AppState)


def test_can_transition_rejects_unknown_states():
    assert not can_transition("NOT_A_STATE", AppState.DRAFT)
    assert not can_transition(AppState.DRAFT, "NOT_A_STATE")


def test_creation_event_is_none_to_draft(db_session):
    app = make_application(db_session, AppState.DRAFT)
    record_creation(db_session, app, actor="applicant", now=START)
    db_session.flush()
    [event] = events_for(db_session, app)
    assert (event.from_state, event.to_state, event.reason) == (None, "DRAFT", "CREATED")


def test_creation_requires_draft(db_session):
    app = make_application(db_session, AppState.KYC_PENDING)
    with pytest.raises(InvalidTransitionError):
        record_creation(db_session, app, actor="applicant", now=START)


def test_database_rejects_unknown_state(db_session):
    from sqlalchemy.exc import IntegrityError

    app = make_application(db_session, AppState.DRAFT)
    app.state = "LIMBO"
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


@pytest.mark.parametrize(
    ("from_status", "to_status", "ok"),
    [
        (OfferStatus.GENERATED, OfferStatus.ACCEPTED, True),
        (OfferStatus.ACCEPTED, OfferStatus.ESIGNED, True),
        (OfferStatus.GENERATED, OfferStatus.EXPIRED, True),
        (OfferStatus.ACCEPTED, OfferStatus.EXPIRED, True),
        (OfferStatus.GENERATED, OfferStatus.ESIGNED, False),  # cannot skip acceptance
        (OfferStatus.ESIGNED, OfferStatus.EXPIRED, False),  # signed offers don't expire
        (OfferStatus.EXPIRED, OfferStatus.ACCEPTED, False),  # expired offers can't reopen
        (OfferStatus.ACCEPTED, OfferStatus.GENERATED, False),
    ],
)
def test_offer_status_transitions(from_status, to_status, ok):
    if ok:
        check_offer_transition(from_status, to_status)
    else:
        with pytest.raises(InvalidTransitionError) as exc:
            check_offer_transition(from_status, to_status)
        assert exc.value.details["kind"] == "offer"


def _e(frm, to, event_type="STATE_CHANGE"):
    return {"event_type": event_type, "from_state": frm, "to_state": to}


def test_event_log_checker_accepts_legal_history():
    log = [
        _e(None, "DRAFT"),
        _e("DRAFT", "KYC_PENDING"),
        _e("KYC_PENDING", "UNDER_ASSESSMENT"),
        _e("UNDER_ASSESSMENT", "APPROVED"),
        _e("GENERATED", "ACCEPTED", "OFFER_STATUS"),  # non state-change rows are ignored
        _e("APPROVED", "DISBURSED"),
    ]
    assert illegal_transitions_in_log(log) == []


@pytest.mark.parametrize(
    ("log", "fragment"),
    [
        ([], "no state transitions"),
        ([_e("DRAFT", "KYC_PENDING")], "first transition"),
        ([_e(None, "DRAFT"), _e("DRAFT", "APPROVED")], "illegal transition DRAFT->APPROVED"),
        ([_e(None, "DRAFT"), _e("KYC_PENDING", "UNDER_ASSESSMENT")], "gap"),
    ],
)
def test_event_log_checker_flags_problems(log, fragment):
    problems = illegal_transitions_in_log(log)
    assert problems and fragment in problems[0]


def test_event_log_checker_reads_orm_rows(db_session):
    app = make_application(db_session, AppState.DRAFT)
    record_creation(db_session, app, actor="applicant", now=START)
    transition(db_session, app, AppState.KYC_PENDING, actor="applicant", now=START)
    db_session.flush()
    assert illegal_transitions_in_log(events_for(db_session, app)) == []
