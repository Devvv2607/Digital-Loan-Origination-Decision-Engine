"""US-11 referral queue and analyst review."""

from sqlalchemy import select

from app.models import Decision
from tests.conftest import OPS, applicant_headers_for, internal_headers_for
from tests.helpers import admin_headers_cached, assess, prepare

PAN = "ZZZPZ1234Q"
NOTES = "Salary credits look stable; borderline case acceptable."


def referred(client, headers, pan=PAN, **kwargs) -> str:
    app_id = prepare(client, headers, pan, **kwargs)
    assert assess(client, app_id, headers)["outcome"] == "REFERRED"
    return app_id


def review(client, app_id, headers, action="APPROVE", notes=NOTES, key=None):
    h = {**headers, **({"Idempotency-Key": key} if key else {})}
    return client.post(f"/ops/referrals/{app_id}/review", json={"action": action, "notes": notes}, headers=h)


def test_queue_lists_referrals_oldest_first_with_flags(client, clock, applicant_headers):
    first = referred(client, applicant_headers, aa="DECLINE")
    clock.advance(hours=2)
    second = referred(client, applicant_headers_for(client), "ZZZPZ2222Q", profile={"bureau": {"behaviour": "NTC"}})
    clock.advance(hours=1)
    approved = prepare(client, applicant_headers_for(client), "ZZZPZ3333Q")
    assess(client, approved, applicant_headers_for(client))  # approved: not in the queue

    q = client.get("/ops/referrals", headers=admin_headers_cached(client)).json()
    assert q["total"] == 2
    assert [i["application_id"] for i in q["items"]] == [first, second]
    top = q["items"][0]
    assert top["income_unverified"] is True and top["fraud_signal"] is False
    assert top["hours_in_queue"] == 3.0
    assert top["applicant_name"] == "Asha Verma"
    assert top["phone_masked"] == "******0001" and top["pan_masked"] == "ZZZPZ****Q"

    filtered = client.get("/ops/referrals?reason_code=ELIG_THIN_FILE", headers=admin_headers_cached(client)).json()
    assert [i["application_id"] for i in filtered["items"]] == [second]


def test_public_read_only_view_shows_initials_only(client, applicant_headers):
    app_id = referred(client, applicant_headers, aa="DECLINE")
    item = client.get("/ops/referrals").json()["items"][0]
    assert item["applicant_name"] == "A. V."
    d = client.get(f"/ops/referrals/{app_id}").json()
    assert d["application"]["applicant_name"] == "A. V."
    assert d["application"]["details"]["employer_name"] is None


def test_detail_has_reasons_inputs_integrations_and_timeline(client, applicant_headers):
    app_id = referred(client, applicant_headers, profile={"aa": {"average_monthly_income": 50_000}})
    d = client.get(f"/ops/referrals/{app_id}", headers=admin_headers_cached(client)).json()
    assert d["decision"]["reason_codes"] == ["FRAUD_INCOME_MISMATCH"]
    assert "41.2% difference" in d["decision"]["explanations"]["FRAUD_INCOME_MISMATCH"]
    providers = {c["provider"] for c in d["integration_results"]}
    assert providers == {"pan", "kyc", "aa", "bureau"}
    assert "ZZZPZ1234Q" not in str(d)  # PAN masked everywhere
    assert d["timeline"][-1]["to_state"] == "REFERRED" and d["review"] is None


def test_approve_generates_offer_under_decision_policy_version(client, applicant_headers):
    app_id = referred(client, applicant_headers, aa="DECLINE")
    # Policy changes after the referral: the analyst's offer still uses version 1 pricing.
    admin = admin_headers_cached(client)
    pricing = client.get("/admin/rules", headers=admin).json()["rules"][-1]["parameters"]
    client.put("/admin/rules/PRICING", headers=admin, json={
        "parameters": {**pricing, "rate_bands": [{"min_score": 300, "annual_rate": 24.0}]},
        "change_comment": "Reprice"})

    r = review(client, app_id, internal_headers_for(client, OPS))
    assert r.status_code == 200
    body = r.json()
    assert (body["state"], body["policy_version"]) == ("APPROVED", 1)
    offer = client.get(f"/applications/{app_id}/offer", headers=applicant_headers).json()
    assert (offer["policy_version"], offer["interest_rate"], offer["loan_amount"]) == (1, 12.99, 500_000)

    decision = client.get(f"/applications/{app_id}/decision", headers=applicant_headers).json()
    assert (decision["outcome"], decision["decided_by"]) == ("APPROVED", "analyst")
    detail = client.get(f"/ops/referrals/{app_id}", headers=admin).json()
    assert detail["review"]["action"] == "APPROVE" and detail["review"]["reviewer"] == "ops:ops"
    assert detail["timeline"][-1]["event_type"] == "OFFER_STATUS"


def test_applicant_can_take_an_analyst_approved_offer_to_disbursal(client, applicant_headers):
    app_id = referred(client, applicant_headers, aa="DECLINE")
    review(client, app_id, internal_headers_for(client, OPS))
    base = f"/applications/{app_id}"
    client.post(f"{base}/offer/accept", json={"kfs_acknowledged": True}, headers=applicant_headers)
    client.post(f"{base}/offer/esign", json={"signature_name": "Asha Verma"}, headers=applicant_headers)
    assert client.post(f"{base}/disburse", headers=applicant_headers).json()["application_state"] == "DISBURSED"


def test_decline_with_notes(client, applicant_headers, db_session):
    app_id = referred(client, applicant_headers, aa="DECLINE")
    r = review(client, app_id, internal_headers_for(client, OPS), action="DECLINE",
               notes="Declared income could not be supported by documents.")
    assert r.json()["state"] == "DECLINED" and r.json()["offer_id"] is None
    decision = client.get(f"/applications/{app_id}/decision", headers=applicant_headers).json()
    assert (decision["outcome"], decision["decided_by"], decision["reasons"]) == ("DECLINED", "analyst", [])


def test_bureau_outage_referral_approved_at_fallback_rate(client, applicant_headers):
    app_id = referred(client, applicant_headers, profile={"bureau": {"behaviour": "TIMEOUT"}})
    review(client, app_id, internal_headers_for(client, OPS))
    offer = client.get(f"/applications/{app_id}/offer", headers=applicant_headers).json()
    assert (offer["interest_rate"], offer["loan_amount"]) == (21.99, 500_000)


def test_notes_are_mandatory(client, applicant_headers):
    app_id = referred(client, applicant_headers, aa="DECLINE")
    r = review(client, app_id, internal_headers_for(client, OPS), notes="ok")
    assert r.status_code == 422 and r.json()["details"]["fields"][0]["field"] == "notes"


def test_review_is_idempotent_and_single(client, applicant_headers, db_session):
    app_id = referred(client, applicant_headers, aa="DECLINE")
    ops = internal_headers_for(client, OPS)
    first = review(client, app_id, ops, key="rv-1")
    replay = review(client, app_id, ops, key="rv-1")
    assert first.json() == replay.json() and replay.headers["Idempotent-Replay"] == "true"
    second = review(client, app_id, ops, action="DECLINE", notes="Changing my mind about this one.")
    assert second.status_code == 409 and second.json()["error_code"] == "ALREADY_REVIEWED"
    manual = db_session.scalars(select(Decision).where(Decision.source == "MANUAL")).all()
    assert len(manual) == 1


def test_only_referred_applications_can_be_reviewed(client, applicant_headers):
    app_id = prepare(client, applicant_headers, PAN)
    assess(client, app_id, applicant_headers)  # approved
    r = review(client, app_id, internal_headers_for(client, OPS))
    assert r.status_code == 409 and r.json()["error_code"] == "INVALID_STATE_TRANSITION"


def test_review_requires_ops_or_admin(client, applicant_headers):
    app_id = referred(client, applicant_headers, aa="DECLINE")
    assert review(client, app_id, {}).status_code == 401
    assert review(client, app_id, applicant_headers).status_code == 403
    assert review(client, app_id, admin_headers_cached(client)).status_code == 200
