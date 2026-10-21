"""US-07 KFS-style offer and US-08 accept -> e-sign -> disburse, including EC-15."""

import uuid

from sqlalchemy import select

from app.models import ApplicationEvent
from app.state_machine.machine import illegal_transitions_in_log
from tests.conftest import applicant_headers_for
from tests.helpers import admin_headers_cached, assess, prepare

PAN = "ZZZPZ1234Q"


def approved(client, headers, pan=PAN, **kwargs) -> str:
    app_id = prepare(client, headers, pan, **kwargs)
    assert assess(client, app_id, headers)["outcome"] == "APPROVED"
    return app_id


def offer(client, app_id, headers):
    r = client.get(f"/applications/{app_id}/offer", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def accept(client, app_id, headers, ack=True, key=None):
    h = {**headers, **({"Idempotency-Key": key} if key else {})}
    return client.post(f"/applications/{app_id}/offer/accept", json={"kfs_acknowledged": ack}, headers=h)


def esign(client, app_id, headers):
    return client.post(f"/applications/{app_id}/offer/esign", json={"signature_name": "Asha Verma"}, headers=headers)


def disburse(client, app_id, headers):
    return client.post(f"/applications/{app_id}/disburse", headers=headers)


def test_kfs_offer_shows_every_required_field(client, applicant_headers):
    o = offer(client, approved(client, applicant_headers), applicant_headers)
    for key in ("loan_amount", "net_disbursal", "tenure_months", "interest_rate", "apr", "emi", "total_interest",
                "total_fees", "total_repayment", "schedule", "cooling_off_days", "grievance_contact", "assumptions",
                "disclaimer", "expires_at", "policy_version"):
        assert o[key] is not None, key
    # ₹5,00,000 for 36 months at 12.99% (score 781 band), 2% fee — same figures as docs/API.md.
    assert (o["loan_amount"], o["interest_rate"], o["emi"], o["total_fees"], o["net_disbursal"]) == (
        500_000, 12.99, 16_845, 10_000, 490_000)
    assert (o["total_repayment"], o["total_interest"], o["apr"]) == (606_405, 106_405, 14.41)
    assert sum(row["principal"] for row in o["schedule"]) == o["loan_amount"]
    assert o["disclaimer"] == ("Simulated KFS-style disclosure for demonstration; not a legally compliant "
                               "disclosure or a real offer.")
    assert o["cooling_off_days"] == 3 and o["grievance_contact"] == "grievance@lendwise.example"
    assert o["expires_at"].startswith("2026-01-22T10:00:00")  # 7 days
    assert o["status"] == "GENERATED" and o["amount_capped"] is False


def test_counter_offer_is_shown_against_requested_amount(client, applicant_headers):
    # No existing EMIs, so FOIR on the capped ₹16,84,000 (~46%) passes and the counter-offer is made.
    app_id = approved(client, applicant_headers, details={"loan_amount": 2_000_000, "tenure_months": 60},
                      profile={"bureau": {"behaviour": "OK", "score": 781, "existing_monthly_emis": 0}})
    o = offer(client, app_id, applicant_headers)
    assert (o["requested_amount"], o["loan_amount"], o["amount_capped"]) == (2_000_000, 1_684_000, True)


def test_accept_requires_kfs_acknowledgement(client, applicant_headers):
    app_id = approved(client, applicant_headers)
    r = accept(client, app_id, applicant_headers, ack=False)
    assert r.status_code == 400 and r.json()["error_code"] == "KFS_NOT_ACKNOWLEDGED"
    assert offer(client, app_id, applicant_headers)["status"] == "GENERATED"


def test_accept_esign_disburse_are_separate_ordered_steps(client, applicant_headers, db_session):
    app_id = approved(client, applicant_headers)

    r = esign(client, app_id, applicant_headers)
    assert r.status_code == 409 and "accept" in r.json()["message"]          # can't sign before accepting
    assert disburse(client, app_id, applicant_headers).status_code == 409    # can't disburse before signing

    r = accept(client, app_id, applicant_headers)
    assert (r.json()["status"], r.json()["application_state"], r.json()["next_step"]) == ("ACCEPTED", "APPROVED", "ESIGN")
    assert disburse(client, app_id, applicant_headers).status_code == 409    # still not signed

    r = esign(client, app_id, applicant_headers)
    assert r.json()["status"] == "ESIGNED" and r.json()["esign_reference"].startswith("MOCK-ESIGN-")
    assert r.json()["next_step"] == "DISBURSE"

    r = disburse(client, app_id, applicant_headers)
    body = r.json()
    assert (body["application_state"], body["net_disbursed"], body["cooling_off_days"]) == ("DISBURSED", 490_000, 3)
    assert body["disbursal_reference"].startswith("MOCK-DISB-") and body["next_step"] == "DONE"

    log = db_session.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == uuid.UUID(app_id))
                             .order_by(ApplicationEvent.seq)).all()
    assert illegal_transitions_in_log(log) == []
    offer_steps = [(e.from_state, e.to_state) for e in log if e.event_type == "OFFER_STATUS"]
    assert offer_steps == [(None, "GENERATED"), ("GENERATED", "ACCEPTED"), ("ACCEPTED", "ESIGNED")]
    assert log[-1].event_type == "STATE_CHANGE" and (log[-1].from_state, log[-1].to_state) == ("APPROVED", "DISBURSED")


def test_offer_steps_are_idempotent(client, applicant_headers, db_session):
    app_id = approved(client, applicant_headers)
    first = accept(client, app_id, applicant_headers, key="acc-1")
    replay = accept(client, app_id, applicant_headers, key="acc-1")
    assert first.json() == replay.json() and replay.headers["Idempotent-Replay"] == "true"
    assert accept(client, app_id, applicant_headers).status_code == 200      # no key: still no second event
    esign(client, app_id, applicant_headers)
    esign(client, app_id, applicant_headers)
    disburse(client, app_id, applicant_headers)
    assert disburse(client, app_id, applicant_headers).json()["application_state"] == "DISBURSED"
    log = db_session.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == uuid.UUID(app_id))).all()
    assert len([e for e in log if e.event_type == "OFFER_STATUS"]) == 3
    assert len([e for e in log if e.to_state == "DISBURSED"]) == 1


def test_expired_offer_cannot_be_accepted(client, clock, applicant_headers):
    app_id = approved(client, applicant_headers)
    clock.advance(days=7)
    headers = applicant_headers_for(client)
    r = accept(client, app_id, headers)
    assert r.status_code == 409 and r.json()["error_code"] == "OFFER_EXPIRED"
    view = client.get(f"/applications/{app_id}", headers=headers).json()
    assert (view["state"], view["next_step"]) == ("EXPIRED", "START_NEW")


def test_signed_offer_still_disburses_after_7_days(client, clock, applicant_headers):
    app_id = approved(client, applicant_headers)
    accept(client, app_id, applicant_headers)
    esign(client, app_id, applicant_headers)
    clock.advance(days=8)
    assert disburse(client, app_id, applicant_headers_for(client)).json()["application_state"] == "DISBURSED"


def test_ec_15_acceptance_honours_decision_time_policy(client, applicant_headers):
    app_id = approved(client, applicant_headers)
    before = offer(client, app_id, applicant_headers)
    assert before["policy_version"] == 1

    # Policy changes between decision and acceptance: higher rates and a higher fee.
    admin = admin_headers_cached(client)
    pricing = client.get("/admin/rules", headers=admin).json()["rules"][-1]["parameters"]
    r = client.put("/admin/rules/PRICING", headers=admin, json={
        "parameters": {**pricing, "processing_fee_rate": 0.04,
                       "rate_bands": [{"min_score": 650, "annual_rate": 19.99}], "offer_validity_days": 3},
        "change_comment": "Reprice"})
    assert r.json()["policy_version"] == 2

    accepted = accept(client, app_id, applicant_headers).json()
    assert accepted["policy_version"] == 1
    after = offer(client, app_id, applicant_headers)
    frozen = ("loan_amount", "interest_rate", "apr", "emi", "total_fees", "net_disbursal", "total_repayment",
              "expires_at", "policy_version", "grievance_contact")
    assert {k: after[k] for k in frozen} == {k: before[k] for k in frozen}
    esign(client, app_id, applicant_headers)
    assert disburse(client, app_id, applicant_headers).json()["net_disbursed"] == before["net_disbursal"]

    # A new application is priced under the new policy.
    other = applicant_headers_for(client, phone="9000000002")
    new_id = approved(client, other, pan="ZZZPZ5678Q")
    new_offer = offer(client, new_id, other)
    assert (new_offer["policy_version"], new_offer["interest_rate"], new_offer["total_fees"]) == (2, 19.99, 20_000)


def test_no_offer_for_referred_application(client, applicant_headers):
    app_id = prepare(client, applicant_headers, PAN, aa="DECLINE")
    assess(client, app_id, applicant_headers)
    r = client.get(f"/applications/{app_id}/offer", headers=applicant_headers)
    assert r.status_code == 404
    assert accept(client, app_id, applicant_headers).status_code == 404
