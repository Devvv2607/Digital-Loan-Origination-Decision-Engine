"""US-02 (details + submit) and US-09 (resume) through the API."""

from sqlalchemy import select

from app.models import Application, ApplicationEvent
from tests.conftest import (
    VALID_DETAILS,
    applicant_headers_for,
    create_application,
    create_submitted_application,
)


def test_create_starts_in_draft_with_creation_event(client, applicant_headers, db_session):
    r = client.post("/applications", headers={**applicant_headers, "X-Device-Id": "device-abc"})
    assert r.status_code == 201
    body = r.json()
    assert (body["state"], body["next_step"]) == ("DRAFT", "DETAILS")

    view = client.get(f"/applications/{body['id']}", headers=applicant_headers).json()
    assert [(e["from_state"], e["to_state"], e["actor"]) for e in view["timeline"]] == [
        (None, "DRAFT", "applicant")
    ]
    stored = db_session.get(Application, view["id"])
    assert stored.device_id == "device-abc"


def test_create_requires_login(client):
    r = client.post("/applications")
    assert r.status_code == 401


def test_other_applicant_cannot_read_application(client, applicant_headers):
    """404, not 403, so another applicant's application ID can't be probed (test_applicant_isolation.py)."""
    app_id = create_application(client, applicant_headers)
    other = applicant_headers_for(client, phone="9000000002")
    r = client.get(f"/applications/{app_id}", headers=other)
    assert r.status_code == 404 and r.json()["error_code"] == "NOT_FOUND"


def test_unknown_application_is_404(client, applicant_headers):
    r = client.get("/applications/00000000-0000-0000-0000-000000000000", headers=applicant_headers)
    assert r.status_code == 404 and r.json()["error_code"] == "NOT_FOUND"


def test_details_can_be_saved_in_steps(client, applicant_headers):
    app_id = create_application(client, applicant_headers)
    r = client.patch(f"/applications/{app_id}", json={"full_name": "  Asha Verma  "}, headers=applicant_headers)
    assert r.status_code == 200
    assert r.json()["details"]["full_name"] == "Asha Verma"
    assert r.json()["next_step"] == "DETAILS"

    r = client.patch(f"/applications/{app_id}", json=VALID_DETAILS, headers=applicant_headers)
    assert r.json()["next_step"] == "SUBMIT"
    assert r.json()["state"] == "DRAFT"


def test_invalid_details_rejected_field_by_field(client, applicant_headers):
    app_id = create_application(client, applicant_headers)
    r = client.patch(f"/applications/{app_id}", json={"employment_type": "STUDENT"}, headers=applicant_headers)
    assert r.status_code == 422
    assert {f["field"] for f in r.json()["details"]["fields"]} == {"employment_type"}

    # Amount and tenure limits come from the PRICING policy (50,000-25,00,000; 12-60 months).
    r = client.patch(f"/applications/{app_id}", json={"loan_amount": 10_000, "tenure_months": 72},
                     headers=applicant_headers)
    assert r.status_code == 422
    assert {f["field"] for f in r.json()["details"]["fields"]} == {"loan_amount", "tenure_months"}
    # Nothing was stored.
    view = client.get(f"/applications/{app_id}", headers=applicant_headers).json()
    assert view["details"]["loan_amount"] is None


def test_unknown_fields_rejected(client, applicant_headers):
    app_id = create_application(client, applicant_headers)
    r = client.patch(f"/applications/{app_id}", json={"state": "APPROVED"}, headers=applicant_headers)
    assert r.status_code == 422


def test_future_date_of_birth_rejected(client, applicant_headers):
    app_id = create_application(client, applicant_headers)
    r = client.patch(f"/applications/{app_id}", json={"date_of_birth": "2030-01-01"}, headers=applicant_headers)
    assert r.status_code == 422
    assert r.json()["details"]["fields"][0]["field"] == "date_of_birth"


def test_submit_requires_all_details(client, applicant_headers):
    app_id = create_application(client, applicant_headers)
    client.patch(f"/applications/{app_id}", json={"full_name": "Asha Verma"}, headers=applicant_headers)
    r = client.post(f"/applications/{app_id}/submit", headers=applicant_headers)
    assert r.status_code == 422
    assert "loan_amount" in r.json()["details"]["missing_fields"]
    assert "full_name" not in r.json()["details"]["missing_fields"]


def test_submit_moves_draft_to_kyc_pending(client, applicant_headers):
    app_id = create_application(client, applicant_headers)
    client.patch(f"/applications/{app_id}", json=VALID_DETAILS, headers=applicant_headers)
    r = client.post(f"/applications/{app_id}/submit", headers=applicant_headers)
    assert r.status_code == 200
    assert r.json() == {"id": app_id, "state": "KYC_PENDING", "next_step": "PAN"}

    timeline = client.get(f"/applications/{app_id}", headers=applicant_headers).json()["timeline"]
    assert [(e["from_state"], e["to_state"], e["reason"]) for e in timeline] == [
        (None, "DRAFT", "CREATED"),
        ("DRAFT", "KYC_PENDING", "SUBMITTED"),
    ]


def _transition_count(db_session, app_id):
    return len(
        db_session.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == app_id)).all()
    )


def test_submit_idempotency_key_replays_original_response(client, applicant_headers, db_session):
    app_id = create_application(client, applicant_headers)
    client.patch(f"/applications/{app_id}", json=VALID_DETAILS, headers=applicant_headers)
    headers = {**applicant_headers, "Idempotency-Key": "submit-1"}

    first = client.post(f"/applications/{app_id}/submit", headers=headers)
    second = client.post(f"/applications/{app_id}/submit", headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert "Idempotent-Replay" not in first.headers
    assert second.headers["Idempotent-Replay"] == "true"
    assert _transition_count(db_session, app_id) == 2  # creation + one submit


def test_submit_without_key_is_still_safe_to_repeat(client, applicant_headers, db_session):
    app_id = create_submitted_application(client, applicant_headers)
    r = client.post(f"/applications/{app_id}/submit", headers=applicant_headers)
    assert r.status_code == 200 and r.json()["state"] == "KYC_PENDING"
    assert _transition_count(db_session, app_id) == 2


def test_details_locked_after_submit(client, applicant_headers):
    app_id = create_submitted_application(client, applicant_headers)
    r = client.patch(f"/applications/{app_id}", json={"loan_amount": 600000}, headers=applicant_headers)
    assert r.status_code == 409 and r.json()["error_code"] == "INVALID_STATE_TRANSITION"


def test_resumable_applications_returned_at_login(client):
    headers = applicant_headers_for(client)
    draft_id = create_application(client, headers)
    submitted_id = create_submitted_application(client, headers)

    sent = client.post("/auth/otp/send", json={"phone": "9000000001"}).json()
    r = client.post("/auth/otp/verify", json={"phone": "9000000001", "otp": sent["demo_otp"]})
    resumable = {a["id"]: a["next_step"] for a in r.json()["resumable_applications"]}
    assert resumable == {draft_id: "DETAILS", submitted_id: "PAN"}
