"""US-03 PAN, US-04 e-KYC, US-05 AA consent through the API.

Edge cases covered here: EC-03, EC-04, EC-05, EC-06, EC-11. (EC-07 bureau timeout
is covered at the provider level here and end-to-end with assessment in Phase 3.)
"""

import uuid

import pytest
from sqlalchemy import select

from app.integrations.registry import build_mock_providers
from app.models import Application, ApplicationEvent, Decision, IntegrationCall
from app.services.verification import fetch_bureau_report
from tests.conftest import (
    ADMIN,
    VALID_DETAILS,
    applicant_headers_for,
    create_submitted_application,
    internal_headers_for,
)

PAN = "ZZZPZ1234Q"


def register(client, pan, **overrides):
    profile = {
        "pan_name": "Asha Verma",
        "pan_dob": "1994-03-12",
        "kyc": {"behaviour": "OK"},
        "bureau": {"behaviour": "OK", "score": 781},
        "aa": {"average_monthly_income": 84200},
    }
    profile.update(overrides)
    r = client.put(f"/mock/profiles/{pan}", json=profile, headers=internal_headers_for(client, ADMIN))
    assert r.status_code == 200, r.text


def verify_pan(client, app_id, headers, pan=PAN, **extra):
    return client.post(f"/applications/{app_id}/pan/verify", json={"pan": pan, **extra}, headers=headers)


def calls_for(db, app_id, provider=None):
    stmt = select(IntegrationCall).where(IntegrationCall.application_id == uuid.UUID(app_id))
    if provider:
        stmt = stmt.where(IntegrationCall.provider == provider)
    return db.scalars(stmt.order_by(IntegrationCall.attempt)).all()


@pytest.fixture
def submitted(client, applicant_headers):
    register(client, PAN)
    return create_submitted_application(client, applicant_headers), applicant_headers


def to_kyc_done(client, app_id, headers):
    assert verify_pan(client, app_id, headers).json()["status"] == "VERIFIED"
    start = client.post(f"/applications/{app_id}/kyc/start", headers=headers).json()
    r = client.post(
        f"/applications/{app_id}/kyc/complete",
        json={"kyc_session_id": start["kyc_session_id"], "otp": start["demo_kyc_otp"]},
        headers=headers,
    )
    assert r.json()["status"] == "COMPLETE", r.text


# ======================================================= PAN

def test_pan_verified_when_names_match(client, submitted, db_session):
    app_id, headers = submitted
    r = verify_pan(client, app_id, headers, pan=" zzzpz1234q ")  # normalised
    assert r.status_code == 200
    assert r.json() == {
        "status": "VERIFIED", "pan_masked": "ZZZPZ****Q", "name_on_pan": "ASHA VERMA",
        "name_entered": None, "options": None, "message": None, "next_step": "EKYC",
        "kyc_reused": False,
    }
    [call] = calls_for(db_session, app_id, "pan")
    assert call.request == {"pan": "ZZZPZ****Q"} and call.status == "SUCCESS"


def test_pan_step_requires_submitted_application(client, applicant_headers):
    r = client.post("/applications", headers=applicant_headers)
    resp = verify_pan(client, r.json()["id"], applicant_headers)
    assert resp.status_code == 409


def test_ec_03_invalid_pan_format_makes_no_provider_call(client, submitted, db_session):
    app_id, headers = submitted
    for bad in ["ABCDE12345", "1234567890", "ABCD1234E", "ABCDE1234"]:
        r = verify_pan(client, app_id, headers, pan=bad)
        assert r.status_code == 422
        assert r.json()["error_code"] == "PAN_FORMAT_INVALID"
    assert calls_for(db_session, app_id) == []


def test_pan_reported_invalid_by_provider(client, submitted, db_session):
    app_id, headers = submitted
    r = verify_pan(client, app_id, headers, pan="ZZZPZ1234X")  # magic X, no fixture
    assert r.json()["status"] == "INVALID"
    app = db_session.get(Application, uuid.UUID(app_id))
    assert (app.state, app.pan) == ("KYC_PENDING", None)
    # The applicant can correct it.
    assert verify_pan(client, app_id, headers).json()["status"] == "VERIFIED"


def test_ec_04_pan_name_mismatch_requires_confirmation_and_feeds_f3(client, applicant_headers, db_session):
    register(client, PAN, pan_name="Rohan Mehta")
    app_id = create_submitted_application(client, applicant_headers)  # entered name: Asha Verma

    r = verify_pan(client, app_id, applicant_headers)
    body = r.json()
    assert body["status"] == "NAME_CONFIRMATION_REQUIRED"
    assert (body["name_on_pan"], body["name_entered"]) == ("ROHAN MEHTA", "Asha Verma")
    assert body["options"] == ["USE_PAN_NAME", "KEEP_ENTERED_NAME"]
    assert body["next_step"] == "PAN"

    # Asking again without an answer does not call the provider again.
    verify_pan(client, app_id, applicant_headers)
    assert len(calls_for(db_session, app_id, "pan")) == 1

    r = verify_pan(client, app_id, applicant_headers, name_confirmation="KEEP_ENTERED_NAME")
    assert r.json()["status"] == "VERIFIED"
    app = db_session.get(Application, uuid.UUID(app_id))
    assert app.pan_name_confirmation == "KEEP_ENTERED_NAME"  # F3 reads this in Phase 3
    assert app.full_name == "Asha Verma"
    assert app.pan_name_similarity < 0.85


def test_ec_04_use_pan_name_updates_name_without_flag(client, applicant_headers, db_session):
    register(client, PAN, pan_name="Asha Rani Verma Iyer")
    app_id = create_submitted_application(client, applicant_headers)
    assert verify_pan(client, app_id, applicant_headers).json()["status"] == "NAME_CONFIRMATION_REQUIRED"
    r = verify_pan(client, app_id, applicant_headers, name_confirmation="USE_PAN_NAME")
    assert r.json()["status"] == "VERIFIED"
    app = db_session.get(Application, uuid.UUID(app_id))
    assert (app.full_name, app.pan_name_confirmation) == ("Asha Rani Verma Iyer", "USE_PAN_NAME")


def test_minor_name_variation_passes_without_confirmation(client, applicant_headers):
    register(client, PAN, pan_name="VERMA ASHA")  # word order differs only
    app_id = create_submitted_application(client, applicant_headers)
    assert verify_pan(client, app_id, applicant_headers).json()["status"] == "VERIFIED"


def test_ec_11_duplicate_pan_blocked_with_409(client, submitted, db_session):
    first_id, first_headers = submitted
    assert verify_pan(client, first_id, first_headers).json()["status"] == "VERIFIED"

    other = applicant_headers_for(client, phone="9000000002")
    second_id = create_submitted_application(client, other)
    r = verify_pan(client, second_id, other)

    assert r.status_code == 409
    assert r.json()["error_code"] == "APPLICATION_ALREADY_IN_PROGRESS"
    assert "fraud" not in r.json()["message"].lower() and "duplicate" not in r.json()["message"].lower()

    second = db_session.get(Application, uuid.UUID(second_id))
    assert (second.state, second.pan, second.pan_status) == ("KYC_PENDING", None, "NOT_STARTED")
    assert calls_for(db_session, second_id) == []  # blocked before any provider call
    assert db_session.scalars(select(Decision)).all() == []
    [event] = db_session.scalars(
        select(ApplicationEvent).where(
            ApplicationEvent.application_id == second.id, ApplicationEvent.event_type == "FRAUD_CHECK"
        )
    ).all()
    assert (event.reason, event.metadata_) == ("FRAUD_DUPLICATE_PAN", {"check": "F1", "pan": "ZZZPZ****Q"})


def test_ec_11_pan_held_by_terminal_application_is_not_a_duplicate(client, submitted, db_session):
    first_id, first_headers = submitted
    verify_pan(client, first_id, first_headers)
    db_session.get(Application, uuid.UUID(first_id)).state = "DECLINED"
    db_session.flush()

    other = applicant_headers_for(client, phone="9000000002")
    second_id = create_submitted_application(client, other)
    assert verify_pan(client, second_id, other).json()["status"] == "VERIFIED"


def test_ec_11_pan_awaiting_name_confirmation_is_already_claimed(client, applicant_headers):
    register(client, PAN, pan_name="Rohan Mehta")
    first = create_submitted_application(client, applicant_headers)
    assert verify_pan(client, first, applicant_headers).json()["status"] == "NAME_CONFIRMATION_REQUIRED"
    second = create_submitted_application(client, applicant_headers)
    assert verify_pan(client, second, applicant_headers).status_code == 409


def test_verified_pan_cannot_be_swapped(client, submitted):
    app_id, headers = submitted
    verify_pan(client, app_id, headers)
    assert verify_pan(client, app_id, headers).json()["status"] == "VERIFIED"  # same PAN: idempotent
    assert verify_pan(client, app_id, headers, pan="ZZZPZ9999Q").status_code == 409


# ======================================================= e-KYC

def test_kyc_requires_verified_pan(client, submitted):
    app_id, headers = submitted
    r = client.post(f"/applications/{app_id}/kyc/start", headers=headers)
    assert r.status_code == 409 and "PAN" in r.json()["message"]


def test_kyc_success_stores_identity_and_similarity(client, submitted, db_session):
    app_id, headers = submitted
    verify_pan(client, app_id, headers)
    start = client.post(f"/applications/{app_id}/kyc/start", headers=headers).json()
    assert start["status"] == "OTP_SENT" and len(start["demo_kyc_otp"]) == 6
    assert start["demo_notice"].startswith("Simulated e-KYC")

    r = client.post(f"/applications/{app_id}/kyc/complete",
                    json={"kyc_session_id": start["kyc_session_id"], "otp": start["demo_kyc_otp"]}, headers=headers)
    assert r.json() == {"status": "COMPLETE", "message": None, "state": "KYC_PENDING", "next_step": "AA_CONSENT"}
    app = db_session.get(Application, uuid.UUID(app_id))
    assert (app.kyc_status, app.kyc_name, str(app.kyc_dob)) == ("COMPLETE", "ASHA VERMA", "1994-03-12")
    assert app.kyc_pan_name_similarity == 1.0 and app.kyc_address["city"]


def test_kyc_identity_mismatch_recorded_for_f3(client, applicant_headers, db_session):
    register(client, PAN, kyc={"behaviour": "OK", "name": "Priya Nair", "dob": "1990-01-01"})
    app_id = create_submitted_application(client, applicant_headers)
    to_kyc_done(client, app_id, applicant_headers)
    app = db_session.get(Application, uuid.UUID(app_id))
    assert app.kyc_pan_name_similarity < 0.85
    assert app.kyc_dob != app.pan_dob


def test_kyc_wrong_otp(client, submitted, db_session):
    app_id, headers = submitted
    verify_pan(client, app_id, headers)
    start = client.post(f"/applications/{app_id}/kyc/start", headers=headers).json()
    wrong = f"{(int(start['demo_kyc_otp']) + 1) % 1_000_000:06d}"
    r = client.post(f"/applications/{app_id}/kyc/complete",
                    json={"kyc_session_id": start["kyc_session_id"], "otp": wrong}, headers=headers)
    assert r.status_code == 400 and r.json()["error_code"] == "KYC_OTP_INVALID"
    assert [c.status for c in calls_for(db_session, app_id, "kyc")] == ["SUCCESS", "SUCCESS"]  # start + complete logged


def test_kyc_session_must_match(client, submitted):
    app_id, headers = submitted
    verify_pan(client, app_id, headers)
    client.post(f"/applications/{app_id}/kyc/start", headers=headers)
    r = client.post(f"/applications/{app_id}/kyc/complete",
                    json={"kyc_session_id": "k-forged", "otp": "123456"}, headers=headers)
    assert r.status_code == 409


def test_ec_05_kyc_timeout_retries_then_stays_pending(client, applicant_headers, db_session):
    register(client, PAN, kyc={"behaviour": "TIMEOUT"})
    app_id = create_submitted_application(client, applicant_headers)
    verify_pan(client, app_id, applicant_headers)
    start = client.post(f"/applications/{app_id}/kyc/start", headers=applicant_headers).json()
    body = {"kyc_session_id": start["kyc_session_id"], "otp": start["demo_kyc_otp"]}

    r = client.post(f"/applications/{app_id}/kyc/complete", json=body, headers=applicant_headers)
    assert r.status_code == 202
    assert r.json()["status"] == "DELAYED" and "notify you" in r.json()["message"]
    assert r.json()["state"] == "KYC_PENDING"

    complete_calls = [c for c in calls_for(db_session, app_id, "kyc") if c.operation == "complete"]
    assert [(c.attempt, c.status) for c in complete_calls] == [(1, "TIMEOUT"), (2, "TIMEOUT"), (3, "TIMEOUT")]
    app = db_session.get(Application, uuid.UUID(app_id))
    assert (app.state, app.kyc_status) == ("KYC_PENDING", "DELAYED")

    # Provider recovers: the applicant retries the same session and completes.
    register(client, PAN, kyc={"behaviour": "OK"})
    r = client.post(f"/applications/{app_id}/kyc/complete", json=body, headers=applicant_headers)
    assert r.status_code == 200 and r.json()["status"] == "COMPLETE"


def test_ec_06_kyc_incomplete_asks_retry(client, applicant_headers, db_session):
    register(client, PAN, kyc={"behaviour": "INCOMPLETE"})
    app_id = create_submitted_application(client, applicant_headers)
    verify_pan(client, app_id, applicant_headers)
    start = client.post(f"/applications/{app_id}/kyc/start", headers=applicant_headers).json()
    r = client.post(f"/applications/{app_id}/kyc/complete",
                    json={"kyc_session_id": start["kyc_session_id"], "otp": start["demo_kyc_otp"]},
                    headers=applicant_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "INCOMPLETE" and "try again" in r.json()["message"]
    assert r.json()["next_step"] == "EKYC"
    app = db_session.get(Application, uuid.UUID(app_id))
    assert (app.state, app.kyc_status, app.kyc_session_id) == ("KYC_PENDING", "INCOMPLETE", None)
    assert calls_for(db_session, app_id, "kyc")[-1].status == "INCOMPLETE"

    # Retry with a fresh session once the provider returns full data.
    register(client, PAN, kyc={"behaviour": "OK"})
    to_retry = client.post(f"/applications/{app_id}/kyc/start", headers=applicant_headers).json()
    r = client.post(f"/applications/{app_id}/kyc/complete",
                    json={"kyc_session_id": to_retry["kyc_session_id"], "otp": to_retry["demo_kyc_otp"]},
                    headers=applicant_headers)
    assert r.json()["status"] == "COMPLETE"


def test_kyc_cannot_restart_after_completion(client, submitted):
    app_id, headers = submitted
    to_kyc_done(client, app_id, headers)
    assert client.post(f"/applications/{app_id}/kyc/start", headers=headers).status_code == 409


# ======================================================= Account Aggregator

def test_aa_requires_completed_kyc(client, submitted):
    app_id, headers = submitted
    verify_pan(client, app_id, headers)
    r = client.post(f"/applications/{app_id}/aa/consent", json={"decision": "APPROVE"}, headers=headers)
    assert r.status_code == 409


def test_aa_approve_stores_verified_income(client, submitted, db_session):
    app_id, headers = submitted
    to_kyc_done(client, app_id, headers)
    r = client.post(f"/applications/{app_id}/aa/consent", json={"decision": "APPROVE"}, headers=headers)
    body = r.json()
    assert (body["status"], body["months_of_data"], body["average_monthly_income"], body["next_step"]) == (
        "APPROVED", 6, 84200, "ASSESS"
    )
    app = db_session.get(Application, uuid.UUID(app_id))
    assert app.aa_average_monthly_income == 84200 and len(app.aa_income_credits) == 6
    assert app.declared_monthly_income == VALID_DETAILS["declared_monthly_income"]  # untouched
    assert [c.operation for c in calls_for(db_session, app_id, "aa")] == ["consent_create", "consent_decision"]


def test_aa_decline_records_choice_and_moves_on(client, submitted, db_session):
    app_id, headers = submitted
    to_kyc_done(client, app_id, headers)
    r = client.post(f"/applications/{app_id}/aa/consent", json={"decision": "DECLINE"}, headers=headers)
    assert r.json()["status"] == "DECLINED"
    assert "manual review" in r.json()["notice"]
    assert r.json()["next_step"] == "ASSESS"
    app = db_session.get(Application, uuid.UUID(app_id))
    assert (app.aa_status, app.aa_average_monthly_income, app.state) == ("DECLINED", None, "KYC_PENDING")


def test_aa_choice_is_idempotent_but_cannot_be_flipped(client, submitted, db_session):
    app_id, headers = submitted
    to_kyc_done(client, app_id, headers)
    url = f"/applications/{app_id}/aa/consent"
    first = client.post(url, json={"decision": "APPROVE"}, headers=headers).json()
    again = client.post(url, json={"decision": "APPROVE"}, headers=headers).json()
    assert first == again
    assert len(calls_for(db_session, app_id, "aa")) == 2  # no new provider calls
    assert client.post(url, json={"decision": "DECLINE"}, headers=headers).status_code == 409


def test_full_pre_assessment_flow_timeline(client, submitted):
    app_id, headers = submitted
    to_kyc_done(client, app_id, headers)
    client.post(f"/applications/{app_id}/aa/consent", json={"decision": "APPROVE"}, headers=headers)
    view = client.get(f"/applications/{app_id}", headers=headers).json()
    assert (view["state"], view["next_step"]) == ("KYC_PENDING", "ASSESS")
    assert (view["pan"]["status"], view["kyc"]["status"], view["aa"]["status"]) == ("VERIFIED", "COMPLETE", "APPROVED")


# ======================================================= Bureau (used by assessment in Phase 3)

def _app_with_pan(db_session, client, headers, pan):
    app_id = create_submitted_application(client, headers)
    app = db_session.get(Application, uuid.UUID(app_id))
    app.pan = pan
    return app


def test_bureau_report_fetched_and_logged(client, applicant_headers, db_session, settings, clock):
    register(client, PAN)
    app = _app_with_pan(db_session, client, applicant_headers, PAN)
    providers = build_mock_providers(settings, clock, db_session)
    outcome = fetch_bureau_report(db_session, app, providers, settings, clock.now())
    db_session.flush()
    assert outcome.report.score == 781
    [call] = calls_for(db_session, str(app.id), "bureau")
    assert (call.status, call.request) == ("SUCCESS", {"pan": "ZZZPZ****Q"})
    assert "ZZZPZ1234Q" not in str(call.response)


def test_bureau_timeout_retried_twice_then_unavailable(client, applicant_headers, db_session, settings, clock):
    app = _app_with_pan(db_session, client, applicant_headers, "ZZZPZ1234B")  # magic B, no fixture
    providers = build_mock_providers(settings, clock, db_session)
    outcome = fetch_bureau_report(db_session, app, providers, settings, clock.now())
    db_session.flush()
    assert outcome.report is None  # Phase 3 turns this into REFERRED / SYS_BUREAU_UNAVAILABLE (EC-07)
    assert [(c.attempt, c.status) for c in calls_for(db_session, str(app.id), "bureau")] == [
        (1, "TIMEOUT"), (2, "TIMEOUT"), (3, "TIMEOUT")
    ]
