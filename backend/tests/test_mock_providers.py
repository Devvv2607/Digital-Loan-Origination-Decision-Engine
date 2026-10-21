"""Mock providers: deterministic, fixture > magic letter > hash, latency, call logging, retries."""

import time
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.core.clock import FrozenClock
from app.integrations.base import ProviderError, ProviderTimeout
from app.integrations.calls import call_with_retries, logged_call, mask_payload
from app.integrations.mock.population import SCORE_MAX, SCORE_MIN, score_from_uniform
from app.integrations.mock.profiles import resolve_profile
from app.integrations.mock.providers import (
    MockAaProvider,
    MockBureauProvider,
    MockKycProvider,
    MockPanProvider,
    kyc_otp_for,
)
from app.models import IntegrationCall
from tests.conftest import START

NO_FIXTURES = lambda pan: None  # noqa: E731
CLOCK = FrozenClock(datetime(2026, 1, 15, 10, 0, tzinfo=UTC))


def pan_p(fixtures=NO_FIXTURES):
    return MockPanProvider(0, fixtures)


def kyc_p(fixtures=NO_FIXTURES):
    return MockKycProvider(0, fixtures)


def bureau_p(fixtures=NO_FIXTURES):
    return MockBureauProvider(0, fixtures)


def aa_p(fixtures=NO_FIXTURES):
    return MockAaProvider(0, fixtures, CLOCK)


# ---------- determinism ----------

@pytest.mark.parametrize("pan", ["ZZZPZ1234Q", "ABCPQ9876R", "QWEPR0001K"])
def test_same_pan_gives_same_profile(pan):
    assert resolve_profile(pan, None) == resolve_profile(pan, None)
    assert pan_p().verify(pan) == pan_p().verify(pan)
    assert bureau_p().report(pan) == bureau_p().report(pan)


def test_different_pans_give_different_profiles():
    profiles = {resolve_profile(f"ZZZPZ{n:04d}Q", None).pan_name for n in range(40)}
    assert len(profiles) > 10


def test_hash_profiles_are_consistent_between_pan_and_kyc():
    p = resolve_profile("ZZZPZ1234Q", None)
    assert (p.kyc_name, p.kyc_dob) == (p.pan_name, p.pan_dob)
    assert date(1972, 1, 1) <= p.pan_dob < date(2000, 1, 1)


def test_score_distribution_maps_into_bureau_range():
    assert score_from_uniform(0.0) >= SCORE_MIN and score_from_uniform(1.0) <= SCORE_MAX
    assert score_from_uniform(0.5) == 720
    assert score_from_uniform(0.1) < score_from_uniform(0.5) < score_from_uniform(0.9)


# ---------- magic letters ----------

def test_magic_x_makes_pan_invalid():
    r = pan_p().verify("ZZZPZ1234X")
    assert (r.status, r.name, r.date_of_birth) == ("INVALID", None, None)


def test_magic_t_times_out_kyc():
    start = kyc_p().start("ZZZPZ1234T")
    with pytest.raises(ProviderTimeout):
        kyc_p().complete(start.session_id, "ZZZPZ1234T", start.demo_otp)


def test_magic_i_returns_incomplete_kyc():
    start = kyc_p().start("ZZZPZ1234I")
    r = kyc_p().complete(start.session_id, "ZZZPZ1234I", start.demo_otp)
    assert (r.status, r.address, r.missing_fields, r.call_status) == ("INCOMPLETE", None, ["address"], "INCOMPLETE")


def test_magic_m_and_d_create_identity_mismatches():
    m = resolve_profile("ZZZPZ1234M", None)
    d = resolve_profile("ZZZPZ1234D", None)
    assert m.kyc_name != m.pan_name and m.kyc_dob == m.pan_dob
    assert d.kyc_dob != d.pan_dob and d.kyc_name == d.pan_name


def test_magic_b_times_out_bureau_and_n_is_new_to_credit():
    with pytest.raises(ProviderTimeout):
        bureau_p().report("ZZZPZ1234B")
    ntc = bureau_p().report("ZZZPZ1234N")
    assert (ntc.ntc, ntc.score, ntc.existing_monthly_emis, ntc.max_dpd_12m) == (True, None, 0, None)


# ---------- fixtures ----------

FIXTURE = {
    "pan_name": "Asha Verma",
    "pan_dob": "1994-03-12",
    "kyc": {"behaviour": "OK"},
    "bureau": {"behaviour": "OK", "score": 781, "existing_monthly_emis": 6000, "active_loans": 1},
    "aa": {"average_monthly_income": 84200},
}


def test_fixture_drives_every_provider():
    fixtures = {"ZZZPZ1234Q": FIXTURE}.get
    assert pan_p(fixtures).verify("ZZZPZ1234Q").name == "ASHA VERMA"
    report = bureau_p(fixtures).report("ZZZPZ1234Q")
    assert (report.score, report.existing_monthly_emis, report.active_loans) == (781, 6000, 1)
    consent = aa_p(fixtures).create_consent("ZZZPZ1234Q", "LOAN_UNDERWRITING", 6)
    assert aa_p(fixtures).decide(consent.consent_id, "ZZZPZ1234Q", "APPROVE").average_monthly_income == 84200


def test_fixture_wins_over_magic_letter():
    # PAN ends in B (bureau timeout) but the fixture says the bureau answers.
    fixtures = {"ZZZPZ1234B": FIXTURE}.get
    assert bureau_p(fixtures).report("ZZZPZ1234B").score == 781


def test_fixture_can_force_failures():
    fixtures = {"ZZZPZ1234Q": {**FIXTURE, "kyc": {"behaviour": "TIMEOUT"}, "bureau": {"behaviour": "NTC"}}}.get
    start = kyc_p(fixtures).start("ZZZPZ1234Q")
    with pytest.raises(ProviderTimeout):
        kyc_p(fixtures).complete(start.session_id, "ZZZPZ1234Q", start.demo_otp)
    assert bureau_p(fixtures).report("ZZZPZ1234Q").ntc is True


def test_fixture_with_explicit_credits():
    credits = [80000, 82000, 84000, 86000, 88000, 90000]
    fixtures = {"ZZZPZ1234Q": {**FIXTURE, "aa": {"income_credits": credits}}}.get
    r = aa_p(fixtures).decide("c1", "ZZZPZ1234Q", "APPROVE")
    assert [c["amount"] for c in r.income_credits] == credits
    assert r.average_monthly_income == 85000


# ---------- KYC OTP and AA data ----------

def test_kyc_wrong_otp_rejected():
    start = kyc_p().start("ZZZPZ1234Q")
    wrong = f"{(int(start.demo_otp) + 1) % 1_000_000:06d}"
    assert kyc_p().complete(start.session_id, "ZZZPZ1234Q", wrong).status == "OTP_INVALID"
    assert start.demo_otp == kyc_otp_for(start.session_id)


def test_aa_returns_six_months_that_average_exactly():
    r = aa_p().decide("c1", "ZZZPZ1234Q", "APPROVE")
    assert [c["month"] for c in r.income_credits] == [
        "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12"
    ]
    amounts = [c["amount"] for c in r.income_credits]
    assert sum(amounts) / 6 == r.average_monthly_income
    assert r.average_monthly_income == resolve_profile("ZZZPZ1234Q", None).aa_average_income


def test_aa_decline_returns_no_data():
    r = aa_p().decide("c1", "ZZZPZ1234Q", "DECLINE")
    assert (r.status, r.income_credits, r.average_monthly_income) == ("DECLINED", [], None)


def test_providers_reject_malformed_pan():
    with pytest.raises(ProviderError):
        pan_p().verify("BAD")


def test_latency_is_simulated():
    started = time.perf_counter()
    MockPanProvider(60, NO_FIXTURES).verify("ZZZPZ1234Q")
    assert time.perf_counter() - started >= 0.055


# ---------- call logging and retries ----------

def calls(db):
    return db.scalars(select(IntegrationCall).order_by(IntegrationCall.attempt)).all()


def test_logged_call_records_masked_request_and_response(db_session):
    result = logged_call(
        db_session, provider="pan", operation="verify", request={"pan": "ZZZPZ1234Q"},
        fn=lambda: pan_p().verify("ZZZPZ1234Q"), now=START,
    )
    db_session.flush()
    [row] = calls(db_session)
    assert result.status == "VALID"
    assert (row.provider, row.operation, row.status, row.attempt) == ("pan", "verify", "SUCCESS", 1)
    assert row.request == {"pan": "ZZZPZ****Q"}
    assert "ZZZPZ1234Q" not in str(row.request) + str(row.response)
    assert row.latency_ms >= 0 and row.created_at == START


def test_retries_twice_then_gives_up_logging_every_attempt(db_session):
    sleeps = []

    def always_timeout():
        raise ProviderTimeout()

    with pytest.raises(ProviderTimeout):
        call_with_retries(
            db_session, backoff_ms=500, sleep=sleeps.append, provider="bureau", operation="report",
            request={"pan": "ZZZPZ1234B"}, fn=always_timeout, now=START,
        )
    db_session.flush()
    assert [(c.attempt, c.status) for c in calls(db_session)] == [(1, "TIMEOUT"), (2, "TIMEOUT"), (3, "TIMEOUT")]
    assert sleeps == [0.5, 1.0]  # exponential backoff


def test_retry_succeeds_on_second_attempt(db_session):
    attempts = iter([ProviderTimeout(), "ok"])

    class Ok:
        call_status = "SUCCESS"

        def to_dict(self):
            return {"ok": True}

    def flaky():
        item = next(attempts)
        if isinstance(item, Exception):
            raise item
        return Ok()

    call_with_retries(db_session, backoff_ms=0, provider="kyc", operation="complete",
                      request={}, fn=flaky, now=START)
    db_session.flush()
    assert [(c.attempt, c.status) for c in calls(db_session)] == [(1, "TIMEOUT"), (2, "SUCCESS")]


def test_provider_errors_are_logged_and_not_retried(db_session):
    def broken():
        raise ProviderError("bad")

    with pytest.raises(ProviderError):
        call_with_retries(db_session, backoff_ms=0, provider="pan", operation="verify",
                          request={}, fn=broken, now=START)
    db_session.flush()
    assert [(c.attempt, c.status) for c in calls(db_session)] == [(1, "ERROR")]


def test_mask_payload_masks_nested_fields():
    payload = {"pan": "ZZZPZ1234Q", "phone": "9000000001", "nested": [{"note": "PAN ZZZPZ1234Q"}], "n": 3}
    assert mask_payload(payload) == {
        "pan": "ZZZPZ****Q", "phone": "******0001", "nested": [{"note": "PAN ZZZPZ****Q"}], "n": 3,
    }
