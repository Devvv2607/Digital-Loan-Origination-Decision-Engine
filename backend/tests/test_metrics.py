"""US-12 metrics (definitions in docs/PRD.md §7) and the admin demo reset."""

from datetime import timedelta

import pytest

from app.services.metrics import percentile
from tests.conftest import VALID_DETAILS, applicant_headers_for
from tests.helpers import admin_headers_cached, assess, prepare


def disburse(client, app_id, h):
    base = f"/applications/{app_id}"
    client.post(f"{base}/offer/accept", json={"kfs_acknowledged": True}, headers=h)
    client.post(f"{base}/offer/esign", json={"signature_name": "Asha Verma"}, headers=h)
    client.post(f"{base}/disburse", headers=h)


@pytest.fixture
def portfolio(client):
    """Six applications with known outcomes:
    A approved + disbursed, B referred (AA declined), C declined (age),
    D blocked at PAN by F1 (B's PAN), E abandoned in DRAFT, F referred (income mismatch, F4)."""
    h = {}
    for i, n in enumerate("ABCDEF"):
        client.app.state.rate_limiter.reset()  # six logins from one test IP would trip the 5/minute OTP limit
        h[n] = applicant_headers_for(client, phone=f"90000001{i:02d}")
    a = prepare(client, h["A"], "ZZZPA0001Q")
    assess(client, a, h["A"])
    disburse(client, a, h["A"])
    b = prepare(client, h["B"], "ZZZPB0002Q", aa="DECLINE")
    assess(client, b, h["B"])
    c = prepare(client, h["C"], "ZZZPC0003Q", {"pan_dob": "2008-01-01"})
    assess(client, c, h["C"])
    d = client.post("/applications", headers=h["D"]).json()["id"]
    client.patch(f"/applications/{d}", json=VALID_DETAILS, headers=h["D"])
    client.post(f"/applications/{d}/submit", headers=h["D"])
    assert client.post(f"/applications/{d}/pan/verify", json={"pan": "ZZZPB0002Q"}, headers=h["D"]).status_code == 409
    client.post("/applications", headers=h["E"])
    f = prepare(client, h["F"], "ZZZPF0006Q", {"aa": {"average_monthly_income": 50_000}})
    assess(client, f, h["F"])


def test_funnel_counts_and_drop_off(client, portfolio):
    m = client.get("/metrics/funnel").json()  # public read-only in demo mode
    assert [(s["stage"], s["count"]) for s in m["stages"]] == [
        ("CREATED", 6), ("SUBMITTED", 5), ("ASSESSED", 4), ("APPROVED", 1), ("DISBURSED", 1)]
    assert [s.get("drop_off_from_previous") for s in m["stages"]] == [None, 0.1667, 0.2, 0.75, 0.0]
    assert m["conversion_application_to_disbursal"] == round(1 / 6, 4)


def test_decision_rates_fraud_rate_and_reasons(client, portfolio):
    m = client.get("/metrics/funnel").json()
    assert m["decision_mix"] == {"APPROVED": 1, "REFERRED": 2, "DECLINED": 1}
    assert (m["engine_decisions"], m["instant_decision_rate"], m["referral_rate"]) == (4, 0.5, 0.5)
    # D (F1 block) and F (F4) are flagged; A, B, C, D, F attempted PAN verification.
    assert (m["fraud_flags"], m["pan_attempts"], m["fraud_flag_rate"]) == (2, 5, 0.4)
    assert {r["code"]: r["count"] for r in m["top_reason_codes"]} == {
        "DATA_INCOME_UNVERIFIED": 1, "ELIG_AGE": 1, "FRAUD_INCOME_MISMATCH": 1}
    assert set(m["definitions"]) >= {"instant_decision_rate", "fraud_flag_rate", "tat"}


def test_date_filter(client, clock, portfolio):
    tomorrow = (clock.now() + timedelta(days=1)).date().isoformat()
    m = client.get(f"/metrics/funnel?from={tomorrow}").json()
    assert m["stages"][0]["count"] == 0 and m["instant_decision_rate"] is None


def test_tat_from_event_log(client, clock):
    h = applicant_headers_for(client)
    app_id = client.post("/applications", headers=h).json()["id"]
    clock.advance(minutes=5)                                  # 300 s in DRAFT
    h = applicant_headers_for(client)
    client.patch(f"/applications/{app_id}", json=VALID_DETAILS, headers=h)
    client.post(f"/applications/{app_id}/submit", headers=h)
    clock.advance(minutes=2)                                  # 120 s in KYC_PENDING (assess happens 2 min later)
    from tests.helpers import STRONG_PROFILE, register_profile
    register_profile(client, "ZZZPZ1234Q", STRONG_PROFILE)
    client.post(f"/applications/{app_id}/pan/verify", json={"pan": "ZZZPZ1234Q"}, headers=h)
    s = client.post(f"/applications/{app_id}/kyc/start", headers=h).json()
    client.post(f"/applications/{app_id}/kyc/complete",
                json={"kyc_session_id": s["kyc_session_id"], "otp": s["demo_kyc_otp"]}, headers=h)
    client.post(f"/applications/{app_id}/aa/consent", json={"decision": "APPROVE"}, headers=h)
    assess(client, app_id, h)

    tat = client.get("/metrics/tat").json()
    rows = {r["state"]: r for r in tat["states"]}
    assert (rows["DRAFT"]["median"], rows["DRAFT"]["n_completed"]) == (300.0, 1)
    assert rows["KYC_PENDING"]["median"] == 120.0
    assert rows["UNDER_ASSESSMENT"]["median"] == 0.0   # decided inside one request
    assert tat["simulated_timings"] is False and tat["seeded_applications"] == 0  # real event times
    assert (rows["APPROVED"]["n_completed"], rows["APPROVED"]["currently_in_state"]) == (0, 1)


def test_percentile_definition():
    assert percentile([], 0.5) is None
    assert percentile([10], 0.9) == 10
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    assert percentile([1, 2, 3, 4], 0.9) == pytest.approx(3.7)


def test_metrics_need_login_when_demo_read_only_is_off(settings, clock, db_session):
    from fastapi.testclient import TestClient

    from app.core.db import get_db
    from app.main import create_app

    app = create_app(settings.model_copy(update={"demo_read_only": False}), clock)
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        assert c.get("/metrics/funnel").status_code == 401
        assert c.get("/metrics/tat").status_code == 401
        assert c.get("/ops/referrals").status_code == 401


# ---------- demo reset ----------

def test_demo_reset_wipes_data_and_restores_policy_v1(client, portfolio):
    admin = admin_headers_cached(client)
    client.put("/admin/rules/R4", headers=admin,
               json={"parameters": {"pass_max": 0.45, "refer_max": 0.6}, "change_comment": "Tighten"})
    assert client.get("/health").json()["policy_version"] == 2

    r = client.post("/admin/demo/reset", headers=admin)
    assert r.status_code == 200
    assert r.json()["status"] == "reset" and r.json()["deleted"]["applications"] == 6
    assert client.get("/health").json()["policy_version"] == 1
    assert client.get("/metrics/funnel").json()["stages"][0]["count"] == 0
    assert client.get("/admin/rules/versions").json()["total"] == 11


def test_demo_reset_requires_admin(client, ops_headers):
    assert client.post("/admin/demo/reset").status_code == 401
    assert client.post("/admin/demo/reset", headers=ops_headers).status_code == 403
