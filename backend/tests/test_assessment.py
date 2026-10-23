"""US-06 instant decision through the real API, with EC-07, EC-08, EC-09, EC-10, EC-12, EC-13."""

import uuid

from sqlalchemy import select

from app.models import Application, ApplicationEvent, Decision, IntegrationCall, Offer
from app.state_machine.machine import illegal_transitions_in_log
from tests.conftest import applicant_headers_for
from tests.helpers import admin_headers_cached, assess, internal_decision, prepare

PAN = "ZZZPZ1234Q"


def events(db, app_id):
    return db.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == uuid.UUID(app_id))
                      .order_by(ApplicationEvent.seq)).all()


def test_strong_applicant_approved_instantly_with_offer(client, applicant_headers, db_session):
    app_id = prepare(client, applicant_headers, PAN)
    body = assess(client, app_id, applicant_headers)
    assert (body["outcome"], body["reasons"], body["offer_available"], body["next_step"]) == ("APPROVED", [], True, "OFFER")
    assert body["policy_version"] == 1 and body["decided_by"] == "engine"

    app = db_session.get(Application, uuid.UUID(app_id))
    assert (app.state, app.policy_version) == ("APPROVED", 1)
    offer = db_session.scalar(select(Offer).where(Offer.application_id == app.id))
    assert (offer.status, offer.loan_amount, offer.policy_version) == ("GENERATED", 500_000, 1)

    log = events(db_session, app_id)
    assert illegal_transitions_in_log(log) == []
    states = [(e.from_state, e.to_state) for e in log if e.event_type == "STATE_CHANGE"]
    assert states[-2:] == [("KYC_PENDING", "UNDER_ASSESSMENT"), ("UNDER_ASSESSMENT", "APPROVED")]
    assert log[-1].event_type == "OFFER_STATUS" and log[-1].to_state == "GENERATED"


def test_internal_view_has_full_detail(client, applicant_headers):
    app_id = prepare(client, applicant_headers, PAN)
    assess(client, app_id, applicant_headers)
    d = internal_decision(client, app_id)
    assert d["source"] == "ENGINE" and d["policy_version"] == 1
    assert [r["rule_id"] for r in d["rule_results"]] == ["F2", "F3", "F4", "R1", "R2", "R3", "R4", "R5", "R6"]
    snap = d["inputs_snapshot"]
    assert (snap["bureau"]["score"], snap["income_used"], snap["income_source"]) == (781, 84_200, "AA")
    assert snap["inputs"]["applications_24h_phone"] == 1


def test_assess_requires_all_verification_steps(client, applicant_headers):
    app_id = client.post("/applications", headers=applicant_headers).json()["id"]
    r = client.post(f"/applications/{app_id}/assess", headers=applicant_headers)
    assert r.status_code == 409 and r.json()["details"]["next_step"] == "DETAILS"


def test_assess_is_idempotent_with_and_without_key(client, applicant_headers, db_session):
    app_id = prepare(client, applicant_headers, PAN)
    keyed = {**applicant_headers, "Idempotency-Key": "assess-1"}
    first = client.post(f"/applications/{app_id}/assess", headers=keyed)
    replay = client.post(f"/applications/{app_id}/assess", headers=keyed)
    again = client.post(f"/applications/{app_id}/assess", headers=applicant_headers)
    assert first.json() == replay.json() == again.json()
    assert replay.headers["Idempotent-Replay"] == "true"
    app_uuid = uuid.UUID(app_id)
    assert len(db_session.scalars(select(Decision).where(Decision.application_id == app_uuid)).all()) == 1
    assert len(db_session.scalars(select(Offer).where(Offer.application_id == app_uuid)).all()) == 1
    bureau_calls = db_session.scalars(select(IntegrationCall).where(
        IntegrationCall.application_id == app_uuid, IntegrationCall.provider == "bureau")).all()
    assert len(bureau_calls) == 1


def test_ec_07_bureau_timeout_refers_with_sys_code(client, applicant_headers, db_session):
    app_id = prepare(client, applicant_headers, PAN, {"bureau": {"behaviour": "TIMEOUT"}})
    body = assess(client, app_id, applicant_headers)
    assert body["outcome"] == "REFERRED"
    assert body["reasons"] == [{"code": "SYS_BUREAU_UNAVAILABLE",
                                "message": "Your application needs a quick review. We'll update you soon."}]
    d = internal_decision(client, app_id)
    assert d["reason_codes"] == ["SYS_BUREAU_UNAVAILABLE"]
    assert {r["result"] for r in d["rule_results"]} == {"NOT_EVALUATED"}  # no credit rule marked failed
    calls = db_session.scalars(select(IntegrationCall).where(
        IntegrationCall.application_id == uuid.UUID(app_id), IntegrationCall.provider == "bureau")
        .order_by(IntegrationCall.attempt)).all()
    assert [(c.attempt, c.status) for c in calls] == [(1, "TIMEOUT"), (2, "TIMEOUT"), (3, "TIMEOUT")]


def test_ec_08_ntc_refers_not_declines(client, applicant_headers):
    app_id = prepare(client, applicant_headers, PAN, {"bureau": {"behaviour": "NTC"}})
    body = assess(client, app_id, applicant_headers)
    assert body["outcome"] == "REFERRED"
    assert body["primary_reason_code"] == "ELIG_THIN_FILE"
    assert internal_decision(client, app_id)["reason_codes"] == ["ELIG_THIN_FILE"]


def test_ec_09_aa_declined_caps_at_referred(client, applicant_headers):
    app_id = prepare(client, applicant_headers, PAN, aa="DECLINE")
    body = assess(client, app_id, applicant_headers)
    assert body["outcome"] == "REFERRED"
    assert body["reasons"] == [{"code": "DATA_INCOME_UNVERIFIED",
                                "message": "Without bank data we need to review your income manually."}]
    snap = internal_decision(client, app_id)["inputs_snapshot"]
    assert (snap["income_source"], snap["income_used"]) == ("DECLARED", 85_000)


def test_ec_09_declared_income_still_subject_to_r3(client, applicant_headers):
    app_id = prepare(client, applicant_headers, PAN, details={"declared_monthly_income": 20_000}, aa="DECLINE")
    body = assess(client, app_id, applicant_headers)
    assert body["outcome"] == "DECLINED"
    assert "ELIG_INCOME_LOW" in [r["code"] for r in body["reasons"]]
    assert "DATA_INCOME_UNVERIFIED" in internal_decision(client, app_id)["reason_codes"]


def test_ec_10_income_mismatch_uses_verified_and_flags_f4(client, applicant_headers):
    app_id = prepare(client, applicant_headers, PAN, {"aa": {"average_monthly_income": 50_000}},
                     details={"declared_monthly_income": 85_000})
    body = assess(client, app_id, applicant_headers)
    assert body["outcome"] == "REFERRED"
    assert body["reasons"] == [{"code": None, "message": "We need to review a few details."}]
    assert body["primary_reason_code"] is None  # fraud never named to the applicant
    d = internal_decision(client, app_id)
    assert d["primary_reason_code"] == "FRAUD_INCOME_MISMATCH"
    assert d["inputs_snapshot"]["income_used"] == 50_000
    assert "41.2% difference" in d["explanations"]["FRAUD_INCOME_MISMATCH"]


def test_ec_12_velocity_flags_fourth_application(client, clock):
    headers = applicant_headers_for(client, phone="9000000010")
    ids = []
    for n in range(4):
        ids.append(prepare(client, headers, f"ZZZPZ000{n}Q"))
        clock.advance(minutes=1)
    third = assess(client, ids[2], headers)
    assert third["outcome"] == "APPROVED"
    fourth = assess(client, ids[3], headers)
    assert fourth["outcome"] == "REFERRED"
    assert fourth["reasons"] == [{"code": None, "message": "We need to review a few details."}]
    d = internal_decision(client, ids[3])
    assert d["reason_codes"] == ["FRAUD_VELOCITY"]
    assert d["inputs_snapshot"]["inputs"]["applications_24h_phone"] == 4


def test_ec_12_velocity_by_device_across_phones(client, clock):
    ids = []
    for n in range(4):
        headers = applicant_headers_for(client, phone=f"900000002{n}")
        ids.append((prepare(client, headers, f"ZZZPZ001{n}Q", device_id="shared-device"), headers))
        clock.advance(minutes=1)
    app_id, headers = ids[3]
    assert assess(client, app_id, headers)["outcome"] == "REFERRED"
    assert internal_decision(client, app_id)["inputs_snapshot"]["inputs"]["applications_24h_device"] == 4


def test_ec_12_applications_outside_window_do_not_count(client, clock):
    ids = []
    for n in range(4):
        headers = applicant_headers_for(client, phone="9000000030")  # fresh session each visit
        ids.append(prepare(client, headers, f"ZZZPZ002{n}Q"))
        clock.advance(hours=9)  # created at 0h, 9h, 18h, 27h: only 3 fall in the 4th's 24h window
    headers = applicant_headers_for(client, phone="9000000030")
    assert assess(client, ids[3], headers)["outcome"] == "APPROVED"


def test_ec_13_age_out_of_range_declines(client, applicant_headers):
    too_young = prepare(client, applicant_headers, "ZZZPZ1111Q", {"pan_dob": "2005-06-01"})  # 20 today
    body = assess(client, too_young, applicant_headers)
    assert body["outcome"] == "DECLINED"
    assert body["reasons"] == [{"code": "ELIG_AGE", "message": "You don't meet our age criteria for this loan and tenure."}]

    too_old_at_maturity = prepare(client, applicant_headers, "ZZZPZ2222Q", {"pan_dob": "1968-06-01"})  # 57 + 3y loan
    assert assess(client, too_old_at_maturity, applicant_headers)["outcome"] == "DECLINED"
    assert internal_decision(client, too_old_at_maturity)["primary_reason_code"] == "ELIG_AGE"


def test_identity_mismatch_from_kyc_refers(client, applicant_headers):
    app_id = prepare(client, applicant_headers, PAN, {"kyc": {"behaviour": "OK", "name": "Priya Nair"}})
    assess(client, app_id, applicant_headers)
    assert internal_decision(client, app_id)["reason_codes"] == ["FRAUD_IDENTITY_MISMATCH"]


def test_confirmed_pan_name_mismatch_feeds_f3(client, applicant_headers):
    app_id = client.post("/applications", headers=applicant_headers).json()["id"]
    from tests.conftest import VALID_DETAILS
    from tests.helpers import STRONG_PROFILE, register_profile
    register_profile(client, PAN, {**STRONG_PROFILE, "pan_name": "Rohan Mehta", "kyc": {"behaviour": "OK"}})
    client.patch(f"/applications/{app_id}", json=VALID_DETAILS, headers=applicant_headers)
    client.post(f"/applications/{app_id}/submit", headers=applicant_headers)
    client.post(f"/applications/{app_id}/pan/verify", json={"pan": PAN}, headers=applicant_headers)
    client.post(f"/applications/{app_id}/pan/verify", json={"pan": PAN, "name_confirmation": "KEEP_ENTERED_NAME"},
                headers=applicant_headers)
    start = client.post(f"/applications/{app_id}/kyc/start", headers=applicant_headers).json()
    client.post(f"/applications/{app_id}/kyc/complete",
                json={"kyc_session_id": start["kyc_session_id"], "otp": start["demo_kyc_otp"]}, headers=applicant_headers)
    client.post(f"/applications/{app_id}/aa/consent", json={"decision": "APPROVE"}, headers=applicant_headers)
    assess(client, app_id, applicant_headers)
    d = internal_decision(client, app_id)
    assert d["reason_codes"] == ["FRAUD_IDENTITY_MISMATCH"]
    assert "kept an entered name" in d["explanations"]["FRAUD_IDENTITY_MISMATCH"]


def test_new_policy_version_used_without_restart(client, applicant_headers):
    r = client.put("/admin/rules/R2", headers=admin_headers_cached(client), json={
        "parameters": {"approve_threshold": 800, "refer_floor": 700, "ntc_outcome": "REFER"},
        "change_comment": "Raise approve threshold"})
    assert r.status_code == 200
    app_id = prepare(client, applicant_headers, PAN)  # score 781
    body = assess(client, app_id, applicant_headers)
    assert (body["outcome"], body["policy_version"], body["primary_reason_code"]) == ("REFERRED", 2, "ELIG_SCORE_BORDERLINE")


def test_disabled_f1_allows_duplicate_pan(client, applicant_headers):
    client.put("/admin/rules/F1", headers=admin_headers_cached(client), json={"enabled": False, "change_comment": "test"})
    prepare(client, applicant_headers, PAN)
    other = applicant_headers_for(client, phone="9000000002")
    prepare(client, other, PAN)  # would be a 409 with F1 enabled


def test_decision_access_control(client, applicant_headers):
    app_id = prepare(client, applicant_headers, PAN)
    assert client.get(f"/applications/{app_id}/decision", headers=applicant_headers).status_code == 404  # not assessed yet
    assess(client, app_id, applicant_headers)
    other = applicant_headers_for(client, phone="9000000002")
    assert client.get(f"/applications/{app_id}/decision", headers=other).status_code == 404
    assert client.get(f"/applications/{app_id}/decision").status_code == 401
