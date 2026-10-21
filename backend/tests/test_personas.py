"""One-click demo personas: each must reach the outcome the landing page promises."""

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import create_app
from app.models import Application
from tests.helpers import internal_decision


def start(client, persona_id):
    r = client.post(f"/demo/personas/{persona_id}")
    assert r.status_code == 200, r.text
    return r.json()


def run_flow(client, persona):
    """Click through the journey exactly as the frontend does, with the persona's prefilled data."""
    phone = persona["phone"]
    otp = client.post("/auth/otp/send", json={"phone": phone}).json()["demo_otp"]
    token = client.post("/auth/otp/verify", json={"phone": phone, "otp": otp}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    app_id = client.post("/applications", headers=h).json()["id"]
    assert client.patch(f"/applications/{app_id}", json=persona["details"], headers=h).status_code == 200
    assert client.post(f"/applications/{app_id}/submit", headers=h).status_code == 200
    pan = client.post(f"/applications/{app_id}/pan/verify", json={"pan": persona["pan"]}, headers=h)
    if pan.status_code != 200:
        return app_id, h, pan
    assert pan.json()["status"] == "VERIFIED", pan.json()  # persona names always match their PAN
    s = client.post(f"/applications/{app_id}/kyc/start", headers=h).json()
    client.post(f"/applications/{app_id}/kyc/complete",
                json={"kyc_session_id": s["kyc_session_id"], "otp": s["demo_kyc_otp"]}, headers=h)
    client.post(f"/applications/{app_id}/aa/consent", json={"decision": persona["aa_decision"]}, headers=h)
    return app_id, h, client.post(f"/applications/{app_id}/assess", headers=h)


def test_list_personas(client):
    items = client.get("/demo/personas").json()["items"]
    assert [p["label"] for p in items] == [
        "Strong borrower", "New to credit", "High FOIR", "Duplicate PAN", "Income mismatch"]


@pytest.mark.parametrize(
    ("persona_id", "outcome", "internal_codes"),
    [("strong", "APPROVED", []),
     ("new-to-credit", "REFERRED", ["ELIG_THIN_FILE"]),
     ("high-foir", "REFERRED", ["ELIG_FOIR_HIGH"]),
     ("income-mismatch", "REFERRED", ["FRAUD_INCOME_MISMATCH"])],
)
def test_persona_reaches_promised_outcome(client, persona_id, outcome, internal_codes):
    persona = start(client, persona_id)
    app_id, _, result = run_flow(client, persona)
    assert result.status_code == 200 and result.json()["outcome"] == outcome
    assert internal_decision(client, app_id)["reason_codes"] == internal_codes


def test_duplicate_pan_persona_is_blocked_at_pan_step(client, db_session):
    persona = start(client, "duplicate-pan")
    _, _, result = run_flow(client, persona)
    assert result.status_code == 409 and result.json()["error_code"] == "APPLICATION_ALREADY_IN_PROGRESS"
    holders = db_session.query(Application).filter(Application.pan == persona["pan"]).all()
    assert len(holders) == 1 and holders[0].state == "KYC_PENDING"


def test_duplicate_holder_never_expires_while_demo_is_used(client, clock, db_session):
    start(client, "duplicate-pan")
    clock.advance(days=29)
    start(client, "duplicate-pan")  # touches the holder
    clock.advance(days=29)          # 58 days after creation, 29 after last use
    persona = start(client, "duplicate-pan")
    _, _, result = run_flow(client, persona)
    assert result.status_code == 409


def test_two_visitors_can_use_the_same_persona(client):
    a, b = start(client, "strong"), start(client, "strong")
    assert a["pan"] != b["pan"]
    assert run_flow(client, a)[2].json()["outcome"] == "APPROVED"
    assert run_flow(client, b)[2].json()["outcome"] == "APPROVED"


def test_unknown_persona_is_404(client):
    assert client.post("/demo/personas/nobody").status_code == 404


def test_personas_disabled_outside_demo_mode(settings, clock, db_session):
    app = create_app(settings.model_copy(update={"demo_mode": False}), clock)
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        assert c.get("/demo/personas").status_code == 404
        assert c.post("/demo/personas/strong").status_code == 404
