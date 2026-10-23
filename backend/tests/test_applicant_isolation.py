"""Applicants can only read or change their own applications, decisions and offers.

Another applicant's application answers exactly like one that doesn't exist (404 NOT_FOUND,
never 403), so an ID can't be probed. Ops and admin access is unchanged.
"""

import uuid

import pytest

from tests.conftest import OPS, VALID_DETAILS, applicant_headers_for, create_application, internal_headers_for
from tests.helpers import assess, prepare

PAN = "ZZZPZ1234Q"

# Every applicant-facing endpoint that takes an application ID, with a valid body,
# so the only possible reason for refusal is ownership.
APPLICATION_ENDPOINTS = [
    ("GET", "/applications/{id}", None),
    ("PATCH", "/applications/{id}", {"full_name": "Someone Else"}),
    ("POST", "/applications/{id}/submit", None),
    ("POST", "/applications/{id}/pan/verify", {"pan": PAN}),
    ("POST", "/applications/{id}/kyc/start", None),
    ("POST", "/applications/{id}/kyc/complete", {"kyc_session_id": "kyc-session", "otp": "123456"}),
    ("POST", "/applications/{id}/aa/consent", {"decision": "APPROVE"}),
    ("POST", "/applications/{id}/assess", None),
    ("GET", "/applications/{id}/decision", None),
    ("GET", "/applications/{id}/offer", None),
    ("POST", "/applications/{id}/offer/accept", {"kfs_acknowledged": True}),
    ("POST", "/applications/{id}/offer/esign", {"signature_name": "Someone Else"}),
    ("POST", "/applications/{id}/disburse", None),
]
IDS = [f"{m} {p.removeprefix('/applications/{id}') or '/'}" for m, p, _ in APPLICATION_ENDPOINTS]
NOT_FOUND = {"error_code": "NOT_FOUND", "message": "Application not found.", "details": {}}


def call(client, method, path, app_id, body, headers, key=None):
    extra = {"Idempotency-Key": key} if key else {}
    return client.request(method, path.format(id=app_id), json=body, headers={**headers, **extra})


@pytest.fixture
def approved(client, applicant_headers):
    """Applicant A's application, assessed and APPROVED with an open offer."""
    app_id = prepare(client, applicant_headers, PAN)
    assert assess(client, app_id, applicant_headers)["outcome"] == "APPROVED"
    return app_id


@pytest.mark.parametrize(("method", "path", "body"), APPLICATION_ENDPOINTS, ids=IDS)
def test_other_applicant_gets_404_like_a_missing_application(client, applicant_headers, approved, method, path, body):
    owner_view = client.get(f"/applications/{approved}", headers=applicant_headers).json()
    owner_offer = client.get(f"/applications/{approved}/offer", headers=applicant_headers).json()
    other = applicant_headers_for(client, phone="9000000002")

    theirs = call(client, method, path, approved, body, other, key=str(uuid.uuid4()))
    missing = call(client, method, path, uuid.uuid4(), body, other, key=str(uuid.uuid4()))

    assert (theirs.status_code, missing.status_code) == (404, 404), theirs.text
    assert theirs.json() == missing.json() == NOT_FOUND
    # Nothing about the owner's application changed.
    assert client.get(f"/applications/{approved}", headers=applicant_headers).json() == owner_view
    assert client.get(f"/applications/{approved}/offer", headers=applicant_headers).json() == owner_offer


@pytest.mark.parametrize(("method", "path", "body"), APPLICATION_ENDPOINTS, ids=IDS)
def test_other_applicant_gets_404_on_a_draft_too(client, applicant_headers, method, path, body):
    """Same answer at the earliest stage, before any decision or offer exists."""
    app_id = create_application(client, applicant_headers)
    other = applicant_headers_for(client, phone="9000000002")
    r = call(client, method, path, app_id, body, other)
    assert r.status_code == 404 and r.json() == NOT_FOUND, r.text
    view = client.get(f"/applications/{app_id}", headers=applicant_headers).json()
    assert view["state"] == "DRAFT" and view["details"]["full_name"] is None


IDEMPOTENT = ["submit", "assess", "offer/accept", "offer/esign", "disburse"]
BODIES = {"offer/accept": {"kfs_acknowledged": True}, "offer/esign": {"signature_name": "Asha Verma"}}


@pytest.mark.parametrize("step", IDEMPOTENT)
def test_reused_idempotency_key_does_not_replay_another_applicants_response(client, applicant_headers, step):
    """A stored response is only replayed after the ownership check passes."""
    if step == "submit":
        app_id = create_application(client, applicant_headers)
        client.patch(f"/applications/{app_id}", json=VALID_DETAILS, headers=applicant_headers)
    else:
        app_id = prepare(client, applicant_headers, PAN)
        # Run the earlier steps without keys so only the step under test stores a response.
        for earlier in IDEMPOTENT[1:IDEMPOTENT.index(step)]:
            r = call(client, "POST", "/applications/{id}/" + earlier, app_id, BODIES.get(earlier), applicant_headers)
            assert r.status_code == 200, r.text
    method, path, body = "POST", "/applications/{id}/" + step, BODIES.get(step)
    key = str(uuid.uuid4())
    owner = call(client, method, path, app_id, body, applicant_headers, key=key)
    assert owner.status_code == 200, owner.text

    other = applicant_headers_for(client, phone="9000000002")
    r = call(client, method, path, app_id, body, other, key=key)
    assert r.status_code == 404 and r.json() == NOT_FOUND
    assert "idempotent-replay" not in r.headers
    # The owner still gets their stored response back.
    again = call(client, method, path, app_id, body, applicant_headers, key=key)
    assert again.headers.get("idempotent-replay") == "true" and again.json() == owner.json()


def test_my_applications_lists_only_your_own(client, applicant_headers):
    mine = {create_application(client, applicant_headers) for _ in range(2)}
    other = applicant_headers_for(client, phone="9000000002")
    theirs = create_application(client, other)

    r = client.get("/applications", headers=applicant_headers)
    assert r.status_code == 200
    assert {i["id"] for i in r.json()["items"]} == mine
    assert [i["id"] for i in client.get("/applications", headers=other).json()["items"]] == [theirs]


def test_my_applications_needs_an_applicant_session(client):
    assert client.get("/applications").status_code == 401
    assert client.get("/applications", headers=internal_headers_for(client, OPS)).status_code == 403


def test_ops_and_admin_access_unchanged(client, applicant_headers, approved, admin_headers):
    ops = internal_headers_for(client, OPS)
    for headers in (ops, admin_headers):
        decision = client.get(f"/applications/{approved}/decision", headers=headers)
        assert decision.status_code == 200 and "rule_results" in decision.json()
        assert client.get(f"/applications/{approved}/offer", headers=headers).status_code == 200
    # Internal users still can't act as the applicant.
    r = client.post(f"/applications/{approved}/offer/accept", json={"kfs_acknowledged": True}, headers=ops)
    assert r.status_code == 403
