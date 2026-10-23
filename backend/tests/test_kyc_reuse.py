"""US-09 enhancement (D-47): "My applications" and reuse of e-KYC already on file.

A returning applicant whose earlier application completed e-KYC for the same PAN skips the
e-KYC step on a new application. Reuse never crosses applicants or PANs.
"""

from tests.conftest import VALID_DETAILS, applicant_headers_for
from tests.helpers import STRONG_PROFILE, assess, prepare, register_profile

PAN = "ZZZPZ1234Q"
OTHER_PAN = "ZZYPZ1234Q"


def disburse(client, app_id, headers):
    for step, body in (("offer/accept", {"kfs_acknowledged": True}),
                       ("offer/esign", {"signature_name": "Asha Verma"}), ("disburse", None)):
        r = client.post(f"/applications/{app_id}/{step}", json=body, headers=headers)
        assert r.status_code == 200, r.text


def completed_first_application(client, headers) -> str:
    """An earlier application that finished e-KYC and was disbursed (so F1 allows the PAN again)."""
    app_id = prepare(client, headers, PAN)
    assert assess(client, app_id, headers)["outcome"] == "APPROVED"
    disburse(client, app_id, headers)
    return app_id


def new_application_to_pan(client, headers, pan=PAN):
    register_profile(client, pan, STRONG_PROFILE)
    app_id = client.post("/applications", headers=headers).json()["id"]
    assert client.patch(f"/applications/{app_id}", json=VALID_DETAILS, headers=headers).status_code == 200
    assert client.post(f"/applications/{app_id}/submit", headers=headers).status_code == 200
    r = client.post(f"/applications/{app_id}/pan/verify", json={"pan": pan}, headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "VERIFIED", r.text
    return app_id, r.json()


def test_returning_applicant_reuses_kyc_and_skips_the_step(client, applicant_headers):
    first = completed_first_application(client, applicant_headers)
    assert client.get("/applications", headers=applicant_headers).json()["kyc_on_file"] is True

    second, pan = new_application_to_pan(client, applicant_headers)
    assert (pan["kyc_reused"], pan["next_step"]) == (True, "AA_CONSENT")

    view = client.get(f"/applications/{second}", headers=applicant_headers).json()
    assert view["kyc"] == {"status": "COMPLETE", "reused": True}
    assert view["next_step"] == "AA_CONSENT"
    assert [e["reason"] for e in view["timeline"] if e["event_type"] == "NOTE"] == ["KYC_REUSED"]

    # The e-KYC step is closed; the rest of the journey works as normal, including fraud check F3.
    assert client.post(f"/applications/{second}/kyc/start", headers=applicant_headers).status_code == 409
    assert client.post(f"/applications/{second}/aa/consent", json={"decision": "APPROVE"},
                       headers=applicant_headers).status_code == 200
    decision = assess(client, second, applicant_headers)
    assert decision["outcome"] == "APPROVED", decision

    items = {i["id"]: i for i in client.get("/applications", headers=applicant_headers).json()["items"]}
    assert (items[second]["kyc_reused"], items[first]["kyc_reused"]) == (True, False)


def test_reused_kyc_feeds_the_same_inputs_as_a_fresh_one(client, applicant_headers, db_session):
    from app.models import Application

    first = completed_first_application(client, applicant_headers)
    second, _ = new_application_to_pan(client, applicant_headers)
    a, b = db_session.get(Application, first), db_session.get(Application, second)
    db_session.refresh(b)
    assert (b.kyc_name, b.kyc_dob, b.kyc_address) == (a.kyc_name, a.kyc_dob, a.kyc_address)
    assert b.kyc_pan_name_similarity == a.kyc_pan_name_similarity
    assert b.kyc_reused_from_application_id == a.id and b.kyc_session_id is None


def test_no_reuse_for_a_different_pan(client, applicant_headers):
    completed_first_application(client, applicant_headers)
    app_id, pan = new_application_to_pan(client, applicant_headers, pan=OTHER_PAN)
    assert (pan["kyc_reused"], pan["next_step"]) == (False, "EKYC")
    assert client.get(f"/applications/{app_id}", headers=applicant_headers).json()["kyc"] == {
        "status": "NOT_STARTED", "reused": False}


def test_no_reuse_across_applicants_even_with_the_same_pan(client, applicant_headers):
    completed_first_application(client, applicant_headers)
    other = applicant_headers_for(client, phone="9000000002")
    assert client.get("/applications", headers=other).json() == {"items": [], "kyc_on_file": False}
    _, pan = new_application_to_pan(client, other)
    assert (pan["kyc_reused"], pan["next_step"]) == (False, "EKYC")


def test_no_reuse_when_earlier_kyc_was_not_completed(client, applicant_headers, clock):
    first, _ = new_application_to_pan(client, applicant_headers)  # PAN verified, e-KYC never done
    clock.advance(days=31)  # abandoned -> EXPIRED, which frees the PAN for F1
    headers = applicant_headers_for(client)
    assert client.get(f"/applications/{first}", headers=headers).json()["state"] == "EXPIRED"
    assert client.get("/applications", headers=headers).json()["kyc_on_file"] is False
    _, pan = new_application_to_pan(client, headers)
    assert (pan["kyc_reused"], pan["next_step"]) == (False, "EKYC")


def test_my_applications_shows_status_and_next_step(client, applicant_headers, clock):
    disbursed = completed_first_application(client, applicant_headers)
    clock.advance(minutes=5)
    draft = client.post("/applications", headers=applicant_headers).json()["id"]

    r = client.get("/applications", headers=applicant_headers)
    assert r.status_code == 200
    body = r.json()
    assert [i["id"] for i in body["items"]] == [draft, disbursed]  # most recently active first
    d, done = body["items"]
    assert (d["state"], d["next_step"], d["loan_amount"]) == ("DRAFT", "DETAILS", None)
    assert (done["state"], done["next_step"], done["loan_amount"], done["purpose"]) == (
        "DISBURSED", "DONE", VALID_DETAILS["loan_amount"], VALID_DETAILS["purpose"])


def test_my_applications_next_step_follows_the_offer(client, applicant_headers):
    app_id = prepare(client, applicant_headers, PAN)
    assess(client, app_id, applicant_headers)

    def step():
        [item] = client.get("/applications", headers=applicant_headers).json()["items"]
        return item["state"], item["next_step"]

    assert step() == ("APPROVED", "OFFER")
    client.post(f"/applications/{app_id}/offer/accept", json={"kfs_acknowledged": True}, headers=applicant_headers)
    assert step() == ("APPROVED", "ESIGN")
    client.post(f"/applications/{app_id}/offer/esign", json={"signature_name": "Asha Verma"}, headers=applicant_headers)
    assert step() == ("APPROVED", "DISBURSE")


def test_my_applications_applies_due_expiry(client, applicant_headers, clock):
    client.post("/applications", headers=applicant_headers)
    clock.advance(days=31)
    headers = applicant_headers_for(client)
    [item] = client.get("/applications", headers=headers).json()["items"]
    assert (item["state"], item["next_step"]) == ("EXPIRED", "START_NEW")
