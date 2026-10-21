"""US-01: phone + OTP, including EC-01 (lockout) and EC-02 (expiry and resend cap)."""

import logging

from app.main import create_app
from app.core.db import get_db
from fastapi.testclient import TestClient

PHONE = "9000000001"


def send(client, phone=PHONE):
    return client.post("/auth/otp/send", json={"phone": phone})


def verify(client, otp, phone=PHONE):
    return client.post("/auth/otp/verify", json={"phone": phone, "otp": otp})


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


def test_send_returns_simulated_code_valid_for_five_minutes(client, clock):
    r = send(client)
    assert r.status_code == 200
    body = r.json()
    assert len(body["demo_otp"]) == 6 and body["demo_otp"].isdigit()
    assert body["demo_notice"] == "Simulated OTP — no SMS sent."
    assert body["resends_remaining_this_hour"] == 2
    assert body["expires_at"].startswith("2026-01-15T10:05:00")


def test_demo_code_hidden_when_demo_mode_off(settings, clock, db_session):
    app = create_app(settings.model_copy(update={"demo_mode": False}), clock)
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        body = send(c).json()
    assert body["demo_otp"] is None and body["demo_notice"] is None


def test_verify_issues_applicant_token_and_reuses_applicant(client):
    first = verify(client, send(client).json()["demo_otp"])
    assert first.status_code == 200
    assert first.json()["role"] == "applicant"
    assert first.json()["resumable_applications"] == []

    second = verify(client, send(client).json()["demo_otp"])
    assert second.json()["applicant_id"] == first.json()["applicant_id"]


def test_code_cannot_be_reused(client):
    code = send(client).json()["demo_otp"]
    assert verify(client, code).status_code == 200
    r = verify(client, code)
    assert r.status_code == 400 and r.json()["error_code"] == "OTP_INVALID"


def test_verify_without_send_is_invalid(client):
    r = verify(client, "123456")
    assert r.status_code == 400 and r.json()["error_code"] == "OTP_INVALID"


def test_invalid_phone_rejected_with_standard_error_shape(client):
    r = client.post("/auth/otp/send", json={"phone": "12345"})
    assert r.status_code == 422
    body = r.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["details"]["fields"][0]["field"] == "phone"


def test_ec_01_otp_locked_after_three_wrong_attempts(client, clock):
    code = send(client).json()["demo_otp"]

    r1 = verify(client, wrong(code))
    r2 = verify(client, wrong(code))
    assert (r1.status_code, r1.json()["details"]["attempts_remaining"]) == (400, 2)
    assert (r2.status_code, r2.json()["details"]["attempts_remaining"]) == (400, 1)

    r3 = verify(client, wrong(code))
    assert r3.status_code == 423
    assert r3.json()["error_code"] == "OTP_LOCKED"
    assert r3.json()["details"]["locked_until"].startswith("2026-01-15T10:15:00")

    # Locked: even the correct code and a new send are refused.
    assert verify(client, code).status_code == 423
    assert send(client).status_code == 423

    clock.advance(minutes=14, seconds=59)
    assert send(client).status_code == 423

    clock.advance(seconds=1)  # lock lasts exactly 15 minutes
    new_code = send(client).json()["demo_otp"]
    assert verify(client, new_code).status_code == 200


def test_ec_01_lock_is_per_phone(client):
    code = send(client).json()["demo_otp"]
    for _ in range(3):
        verify(client, wrong(code))
    other = send(client, phone="9000000002").json()["demo_otp"]
    assert verify(client, other, phone="9000000002").status_code == 200


def test_ec_02_expired_otp_rejected_and_resend_capped(client, clock):
    code = send(client).json()["demo_otp"]
    clock.advance(minutes=5)  # valid for 5 minutes: at 5:00 it has expired
    r = verify(client, code)
    assert r.status_code == 400 and r.json()["error_code"] == "OTP_EXPIRED"

    # Resend allowed: 2nd and 3rd sends within the hour succeed, the 4th is refused.
    second = send(client)
    assert second.status_code == 200 and second.json()["resends_remaining_this_hour"] == 1
    assert send(client).json()["resends_remaining_this_hour"] == 0
    capped = send(client)
    assert capped.status_code == 429
    assert capped.json()["error_code"] == "OTP_RESEND_LIMIT"
    assert capped.json()["details"]["retry_after"].startswith("2026-01-15T11:00:00")

    # Rolling window: once the first send is an hour old, one more send is allowed.
    clock.advance(minutes=55)
    latest = send(client)
    assert latest.status_code == 200
    assert verify(client, latest.json()["demo_otp"]).status_code == 200


def test_ec_02_code_just_before_expiry_still_works(client, clock):
    code = send(client).json()["demo_otp"]
    clock.advance(minutes=4, seconds=59)
    assert verify(client, code).status_code == 200


def test_phone_never_logged_in_clear(client, caplog):
    caplog.set_level(logging.DEBUG)
    code = send(client).json()["demo_otp"]
    verify(client, wrong(code))
    verify(client, code)
    text = caplog.text
    assert PHONE not in text
    assert "******0001" in text
