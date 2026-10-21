"""EC-14 (30-day abandonment) and offer expiry (7 days, used by EC-15 in Phase 3)."""

import uuid
from datetime import timedelta
from decimal import Decimal

from app.models import Application, Decision, Offer
from app.state_machine.states import AppState
from tests.conftest import (
    ADMIN,
    VALID_DETAILS,
    internal_headers_for,
    applicant_headers_for,
    create_application,
    create_submitted_application,
)


def get(client, app_id, headers=None):
    """Read as the applicant. Logs in again first, since moving the clock days ahead
    expires the 60-minute session token (as it would for a returning user)."""
    headers = applicant_headers_for(client)
    return client.get(f"/applications/{app_id}", headers=headers).json()


def test_ec_14_abandoned_application_expires_after_30_days(client, clock, applicant_headers):
    app_id = create_application(client, applicant_headers)

    clock.advance(days=29, hours=23, minutes=59)
    assert get(client, app_id, applicant_headers)["state"] == "DRAFT"

    clock.advance(minutes=1)  # exactly 30 days since last activity
    view = get(client, app_id, applicant_headers)
    assert view["state"] == "EXPIRED"
    assert view["next_step"] == "START_NEW"
    last = view["timeline"][-1]
    assert (last["from_state"], last["to_state"], last["actor"], last["reason"]) == (
        "DRAFT",
        "EXPIRED",
        "system",
        "ABANDONED_30D",
    )


def test_ec_14_activity_resets_the_clock(client, clock, applicant_headers):
    app_id = create_application(client, applicant_headers)
    clock.advance(days=20)
    client.patch(f"/applications/{app_id}", json={"full_name": "Asha Verma"}, headers=applicant_headers_for(client))
    clock.advance(days=29)  # 49 days after creation, 29 after last activity
    assert get(client, app_id, applicant_headers)["state"] == "DRAFT"


def test_ec_14_kyc_pending_expires_too_and_cannot_be_acted_on(client, clock, applicant_headers):
    app_id = create_submitted_application(client, applicant_headers)
    clock.advance(days=30)
    r = client.post(f"/applications/{app_id}/submit", headers=applicant_headers_for(client))
    assert r.status_code == 409
    assert get(client, app_id, applicant_headers)["state"] == "EXPIRED"


def test_ec_14_expired_applications_are_not_offered_for_resume(client, clock):
    headers = applicant_headers_for(client)
    create_application(client, headers)
    clock.advance(days=31)

    code = client.post("/auth/otp/send", json={"phone": "9000000001"}).json()["demo_otp"]
    verified = client.post("/auth/otp/verify", json={"phone": "9000000001", "otp": code})
    assert verified.status_code == 200
    assert verified.json()["resumable_applications"] == []


def test_ec_14_bulk_job_expires_abandoned_only(client, clock, applicant_headers, db_session):
    old_draft = create_application(client, applicant_headers)
    old_pending = create_submitted_application(client, applicant_headers)
    clock.advance(days=25)
    recent = create_application(client, applicant_headers_for(client))
    clock.advance(days=5)
    admin_headers = internal_headers_for(client, ADMIN)

    r = client.post("/admin/jobs/expire", headers=admin_headers)
    assert r.json() == {"expired_abandoned": 2, "expired_offers": 0}
    states = {i: db_session.get(Application, uuid.UUID(i)).state for i in (old_draft, old_pending, recent)}
    assert states == {old_draft: "EXPIRED", old_pending: "EXPIRED", recent: "DRAFT"}

    # Running again does nothing more.
    assert client.post("/admin/jobs/expire", headers=admin_headers).json()["expired_abandoned"] == 0


def _approved_with_offer(db_session, client, headers, clock, status="GENERATED") -> Application:
    """Build an APPROVED application with an offer directly (engine arrives in Phase 3)."""
    app_id = create_submitted_application(client, headers)
    app = db_session.get(Application, uuid.UUID(app_id))
    now = clock.now()
    app.state = AppState.APPROVED.value
    decision = Decision(
        application_id=app.id, source="ENGINE", outcome="APPROVED", decided_by="engine",
        reason_codes=[], explanations={}, rule_results=[], inputs_snapshot={},
        policy_version=1, created_at=now,
    )
    db_session.add(decision)
    db_session.flush()
    db_session.add(
        Offer(
            application_id=app.id, decision_id=decision.id, status=status, policy_version=1,
            requested_amount=VALID_DETAILS["loan_amount"], loan_amount=500000, tenure_months=36,
            interest_rate=Decimal("12.99"), apr=Decimal("14.41"), emi=16845, processing_fee=10000,
            net_disbursal=490000, total_interest=106405, total_repayment=606405, schedule=[],
            cooling_off_days=3, created_at=now, expires_at=now + timedelta(days=7),
        )
    )
    db_session.flush()
    return app


def test_unsigned_offer_expires_after_7_days_lazily(client, clock, applicant_headers, db_session):
    app = _approved_with_offer(db_session, client, applicant_headers, clock)
    clock.advance(days=6, hours=23)
    assert get(client, app.id, applicant_headers)["state"] == "APPROVED"
    clock.advance(hours=1)
    view = get(client, app.id, applicant_headers)
    assert view["state"] == "EXPIRED"
    offer_event, state_event = view["timeline"][-2:]
    assert (offer_event["event_type"], offer_event["from_state"], offer_event["to_state"]) == (
        "OFFER_STATUS", "GENERATED", "EXPIRED"
    )
    assert (state_event["from_state"], state_event["to_state"], state_event["reason"]) == (
        "APPROVED", "EXPIRED", "OFFER_EXPIRED_7D"
    )


def test_accepted_offer_expires_but_signed_offer_does_not(client, clock, applicant_headers, db_session):
    accepted = _approved_with_offer(db_session, client, applicant_headers, clock, status="ACCEPTED")
    signed = _approved_with_offer(db_session, client, applicant_headers, clock, status="ESIGNED")
    clock.advance(days=8)

    r = client.post("/admin/jobs/expire", headers=internal_headers_for(client, ADMIN))
    assert r.json()["expired_offers"] == 1
    assert db_session.get(Application, accepted.id).state == "EXPIRED"
    assert db_session.get(Application, signed.id).state == "APPROVED"
