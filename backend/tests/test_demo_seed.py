"""Deployed demo seed (D-42, D-44): reset restores the 500 seeded applications, moved to today."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.db import get_db
from app.core.masking import hash_pii
from app.engine.types import age_on
from app.main import create_app
from app.models import Applicant, Application, ApplicationEvent, Decision, Offer, RuleConfig
from app.services.demo_seed import read_seed, shift_date, shift_days, shift_value
from tests.conftest import ADMIN, START, internal_headers_for

SEED = read_seed()
IST = timezone(timedelta(hours=5, minutes=30))


def test_shift_value_moves_dates_datetimes_and_months_only():
    value = {"dob": "1998-02-14", "at": "2026-10-22T09:00:00+05:30", "credits": [{"month": "2026-09", "amount": 1}],
             "name": "Asha Verma", "pan": "ABCPE1234F", "n": 3}
    shifted = shift_value(value, 10, 10, 1)
    assert shifted == {"dob": "1998-02-24", "at": "2026-11-01T09:00:00+05:30", "credits": [{"month": "2026-10", "amount": 1}],
                       "name": "Asha Verma", "pan": "ABCPE1234F", "n": 3}
    assert shift_value({"month": "2026-12"}, 0, 0, 1) == {"month": "2027-01"}


def test_calendar_shift_keeps_ages_across_leap_years():
    # Birthday on decision day; moving back 280 positions crosses 29 Feb 1996 but no 29 Feb in 2026.
    dob, decided = date(1996, 10, 10), date(2026, 10, 10)
    for k in (-280, -1, 1, 140, 365 * 3 + 50):
        assert age_on(shift_date(dob, k), shift_date(decided, k)) == age_on(dob, decided) == 30
    assert shift_date(date(2026, 10, 22), -280) == date(2026, 1, 15)
    assert shift_date(date(2028, 2, 29), 0) == date(2028, 2, 28)


def test_shift_never_moves_the_seed_into_the_future():
    as_of = datetime(2026, 10, 22, 3, 30, tzinfo=UTC)
    for now in (as_of, as_of + timedelta(hours=1), as_of - timedelta(hours=1), as_of + timedelta(days=40, hours=23)):
        assert as_of + timedelta(days=shift_days(as_of, now)) <= now < as_of + timedelta(days=shift_days(as_of, now) + 1)


def test_seed_file_shape_and_documented_distributions():
    meta = SEED["meta"]
    assert meta["counts"]["applications"] == len(SEED["applications"]) == 500
    assert all(a["is_seeded"] for a in SEED["applications"])
    assert set(meta["assumed_distributions"]) >= {"details", "kyc_otp", "offer_accept"}
    assert "SIMULATED" in meta["note"]
    assert not any("phone_hash" in a for a in SEED["applicants"])  # hashed at load time with the deployment's key


@pytest.fixture
def seeded_client(settings, clock, db_session):
    app = create_app(settings.model_copy(update={"demo_seed": True}), clock)
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        admin = internal_headers_for(c, ADMIN)
        r = c.post("/admin/demo/reset", headers=admin)
        assert r.status_code == 200, r.text
        c.reset_result = r.json()
        yield c
    app.state.engine.dispose()


def test_reset_restores_the_seeded_state(seeded_client, db_session):
    result = seeded_client.reset_result
    assert result["seeded_applications"] == 500 and result["policy_version"] == 1
    count = lambda m: db_session.scalar(select(func.count()).select_from(m))  # noqa: E731
    assert count(Application) == 500 and count(Decision) == 470 and count(Offer) == 182
    assert count(RuleConfig) == 11 and db_session.scalar(select(func.max(RuleConfig.version))) == 1
    assert db_session.scalar(select(func.count()).where(Application.is_seeded.is_(False))) == 0
    # Moved to "now": nothing in the future, the newest activity within a day, the window is ~14 days.
    newest = db_session.scalar(select(func.max(ApplicationEvent.created_at)))
    oldest = db_session.scalar(select(func.min(Application.created_at)))
    assert START - timedelta(days=1) < newest <= START
    assert timedelta(days=13) < START - oldest <= timedelta(days=15)
    # The 20 held offers are still open.
    open_offers = db_session.scalars(select(Offer).where(Offer.status == "GENERATED")).all()
    assert len(open_offers) == 20 and all(o.expires_at > START for o in open_offers)
    # Reset again restores the same seeded state, not an empty system.
    again = seeded_client.post("/admin/demo/reset", headers=internal_headers_for(seeded_client, ADMIN)).json()
    assert again["seeded_applications"] == 500 and again["deleted"]["applications"] == 500


def test_shifted_dates_keep_every_recorded_age(seeded_client, db_session):
    for d in db_session.scalars(select(Decision)):
        inputs = d.inputs_snapshot["inputs"]
        r1 = next(r for r in d.rule_results if r["rule_id"] == "R1")
        if r1["result"] == "NOT_EVALUATED":
            continue
        decided_on = date.fromisoformat(inputs["decision_date"])
        assert r1["value"]["age_now"] == age_on(date.fromisoformat(inputs["date_of_birth"]), decided_on)
        assert d.created_at.astimezone(IST).date() == decided_on  # the engine's clock ran in IST


def test_seeded_phones_are_hashed_with_this_deployments_key(seeded_client, db_session, settings):
    phone = SEED["applicants"][0]["phone"]
    stored = db_session.scalar(select(Applicant.phone_hash).where(Applicant.phone_last4 == phone[-4:]))
    assert stored == hash_pii(phone, settings.pii_hash_key)


def test_tat_is_flagged_as_simulated_timings(seeded_client):
    tat = seeded_client.get("/metrics/tat").json()
    assert tat["simulated_timings"] is True and tat["seeded_applications"] == 500
    draft = next(s for s in tat["states"] if s["state"] == "DRAFT")
    assert 3 * 60 < draft["median"] < 15 * 60  # assumed median 6 min
    approved = next(s for s in tat["states"] if s["state"] == "APPROVED")
    assert approved["median"] > 3600  # offer acceptance takes hours
    queue = seeded_client.get("/ops/referrals?page_size=100").json()
    assert queue["total"] == 218
