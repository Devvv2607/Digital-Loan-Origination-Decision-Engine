"""`/mock/*` endpoints: visible in Swagger, clearly labelled, logged, rate-limited, fixtures admin-only."""

from sqlalchemy import select

from app.models import IntegrationCall, MockProfile

TAG = "Mock providers (simulated)"


def test_all_four_mocks_are_in_swagger_under_a_mock_tag(client):
    paths = client.get("/openapi.json").json()["paths"]
    mock_paths = {p for p in paths if p.startswith("/mock/")}
    assert mock_paths == {
        "/mock/pan/verify",
        "/mock/kyc/start",
        "/mock/kyc/complete",
        "/mock/bureau/report",
        "/mock/aa/consent",
        "/mock/aa/consent/{consent_id}/decision",
        "/mock/profiles/{pan}",
    }
    for path in mock_paths:
        for op in paths[path].values():
            assert op["tags"] == [TAG]


def test_mock_pan_masks_pan_and_logs(client, db_session):
    r = client.post("/mock/pan/verify", json={"pan": "ZZZPZ1234Q"})
    assert r.status_code == 200
    assert r.json()["pan"] == "ZZZPZ****Q" and r.json()["status"] == "VALID"
    [row] = db_session.scalars(select(IntegrationCall)).all()
    assert row.application_id is None
    assert row.request == {"pan": "ZZZPZ****Q", "channel": "mock_api"}


def test_mock_kyc_round_trip(client):
    start = client.post("/mock/kyc/start", json={"pan": "ZZZPZ1234Q"}).json()
    r = client.post("/mock/kyc/complete",
                    json={"kyc_session_id": start["kyc_session_id"], "pan": "ZZZPZ1234Q", "otp": start["demo_kyc_otp"]})
    assert r.json()["status"] == "COMPLETE"


def test_mock_timeouts_return_504(client):
    start = client.post("/mock/kyc/start", json={"pan": "ZZZPZ1234T"}).json()
    r = client.post("/mock/kyc/complete",
                    json={"kyc_session_id": start["kyc_session_id"], "pan": "ZZZPZ1234T", "otp": start["demo_kyc_otp"]})
    assert r.status_code == 504 and r.json()["error_code"] == "PROVIDER_TIMEOUT"
    r = client.post("/mock/bureau/report", json={"pan": "ZZZPZ1234B"})
    assert r.status_code == 504


def test_mock_bureau_and_aa(client):
    report = client.post("/mock/bureau/report", json={"pan": "ZZZPZ1234N"}).json()
    assert report["ntc"] is True and report["pan"] == "ZZZPZ****N"
    consent = client.post("/mock/aa/consent", json={"pan": "ZZZPZ1234Q"}).json()
    assert consent["status"] == "PENDING"
    decided = client.post(f"/mock/aa/consent/{consent['consent_id']}/decision",
                          json={"pan": "ZZZPZ1234Q", "decision": "APPROVE"}).json()
    assert decided["status"] == "APPROVED" and len(decided["income_credits"]) == 6


def test_mock_rejects_bad_pan(client):
    r = client.post("/mock/pan/verify", json={"pan": "ABCDE1234!"})
    assert r.status_code == 422


def test_profiles_require_admin(client, applicant_headers, ops_headers, admin_headers, db_session):
    body = {"pan_name": "Asha Verma", "pan_dob": "1994-03-12"}
    assert client.put("/mock/profiles/ZZZPZ1234Q", json=body).status_code == 401
    assert client.put("/mock/profiles/ZZZPZ1234Q", json=body, headers=applicant_headers).status_code == 403
    assert client.put("/mock/profiles/ZZZPZ1234Q", json=body, headers=ops_headers).status_code == 403
    r = client.put("/mock/profiles/ZZZPZ1234Q", json=body, headers=admin_headers)
    assert r.json() == {"pan": "ZZZPZ****Q", "registered": True}
    row = db_session.get(MockProfile, "ZZZPZ1234Q")
    assert row.created_by == "admin:admin"


def test_profile_validation(client, admin_headers):
    r = client.put("/mock/profiles/ZZZPZ1234Q",
                   json={"pan_name": "A V", "pan_dob": "1994-03-12", "bureau": {"score": 950}}, headers=admin_headers)
    assert r.status_code == 422


def test_mock_endpoints_are_rate_limited(client):
    codes = [client.post("/mock/pan/verify", json={"pan": "ZZZPZ1234Q"}).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429
