"""Core utilities: config validation, masking, idempotency, rate limits, error shapes, health."""

import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import AnchoredClock
from app.core.config import ConfigurationError, load_settings
from app.core.db import get_db, make_engine, normalise_database_url
from app.core.masking import hash_pii, mask_pan, mask_phone, mask_text, mask_value
from app.main import create_app
from app.services.idempotency import run_idempotent
from tests.conftest import START

REQUIRED_ENV = [
    "DATABASE_URL", "JWT_SECRET", "PII_HASH_KEY", "ADMIN_USERNAME", "ADMIN_PASSWORD",
    "OPS_USERNAME", "OPS_PASSWORD", "ENV", "CLOCK_START",
]
GOOD = {
    "database_url": "postgresql+psycopg://u:p@localhost/db",
    "jwt_secret": "s" * 40,
    "pii_hash_key": "k" * 20,
    "admin_username": "admin",
    "admin_password": "long-enough",
}


@pytest.fixture
def clean_env(monkeypatch):
    for name in REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)


# ---------- config ----------

def test_missing_required_settings_fail_fast_with_names(clean_env):
    with pytest.raises(ConfigurationError) as exc:
        load_settings(_env_file=None)
    message = str(exc.value)
    for name in ("DATABASE_URL", "JWT_SECRET", "PII_HASH_KEY", "ADMIN_USERNAME", "ADMIN_PASSWORD"):
        assert name in message


def test_short_jwt_secret_rejected(clean_env):
    with pytest.raises(ConfigurationError, match="JWT_SECRET"):
        load_settings(_env_file=None, **{**GOOD, "jwt_secret": "short"})


def test_production_rejects_example_values(clean_env):
    with pytest.raises(ConfigurationError, match="example value"):
        load_settings(_env_file=None, env="production", **{**GOOD, "admin_password": "change-me-admin"})


def test_ops_credentials_must_come_in_pairs(clean_env):
    with pytest.raises(ConfigurationError, match="together"):
        load_settings(_env_file=None, ops_username="ops", **GOOD)


def test_valid_settings_load(clean_env):
    s = load_settings(_env_file=None, cors_origins="http://a.test, http://b.test", **GOOD)
    assert s.cors_origin_list == ["http://a.test", "http://b.test"]
    assert s.rate_limit_profile == "default"


# ---------- masking ----------

def test_mask_pan_and_phone():
    assert mask_pan("ZZZPZ1234Q") == "ZZZPZ****Q"
    assert mask_pan("BAD") == "**********"
    assert mask_pan(None) is None
    assert mask_phone("9000000001") == "******0001"
    assert mask_phone("+91 90000 00001") == "******0001"


def test_mask_text_finds_identifiers_in_free_text():
    text = "PAN ZZZPZ1234Q phone 9876543210 amount 500000 id 12345"
    assert mask_text(text) == "PAN ZZZPZ****Q phone ******3210 amount 500000 id 12345"


def test_mask_value_is_recursive():
    data = {"pan": "ZZZPZ1234Q", "nested": [{"phone": "9000000001"}], "n": 5}
    assert mask_value(data) == {"pan": "ZZZPZ****Q", "nested": [{"phone": "******0001"}], "n": 5}


def test_hash_pii_is_keyed_and_stable():
    assert hash_pii("9000000001", "k1") == hash_pii("9000000001", "k1")
    assert hash_pii("9000000001", "k1") != hash_pii("9000000001", "k2")


def test_logging_masks_pan_even_if_code_forgets(app, caplog):
    caplog.set_level(logging.INFO)
    logging.getLogger("app.test").info("verifying %s for %s", "ZZZPZ1234Q", "9000000001")
    assert "ZZZPZ1234Q" not in caplog.text and "9000000001" not in caplog.text
    assert "ZZZPZ****Q" in caplog.text


# ---------- idempotency ----------

def test_idempotency_runs_handler_once_per_key(db_session):
    calls = []

    def handler():
        calls.append(1)
        return 201, {"n": len(calls)}

    kwargs = dict(key="k1", endpoint="test", scope="s", payload={"a": 1}, now=START, handler=handler)
    first = run_idempotent(db_session, **kwargs)
    second = run_idempotent(db_session, **kwargs)
    assert (first.status_code, first.body, first.replayed) == (201, {"n": 1}, False)
    assert (second.status_code, second.body, second.replayed) == (201, {"n": 1}, True)
    assert len(calls) == 1


def test_idempotency_key_reuse_with_different_body_rejected(db_session):
    from app.core.errors import AppError

    run_idempotent(db_session, key="k2", endpoint="t", scope="s", payload={"a": 1}, now=START, handler=lambda: (200, {}))
    with pytest.raises(AppError) as exc:
        run_idempotent(db_session, key="k2", endpoint="t", scope="s", payload={"a": 2}, now=START, handler=lambda: (200, {}))
    assert exc.value.error_code == "IDEMPOTENCY_KEY_REUSED"


def test_idempotency_keys_are_scoped(db_session):
    a = run_idempotent(db_session, key="k3", endpoint="t", scope="app-1", payload={}, now=START, handler=lambda: (200, {"s": 1}))
    b = run_idempotent(db_session, key="k3", endpoint="t", scope="app-2", payload={}, now=START, handler=lambda: (200, {"s": 2}))
    assert (a.body, b.body, b.replayed) == ({"s": 1}, {"s": 2}, False)


def test_idempotency_key_expires_after_24_hours(db_session):
    from datetime import timedelta

    run_idempotent(db_session, key="k4", endpoint="t", scope="s", payload={}, now=START, handler=lambda: (200, {"v": 1}))
    later = run_idempotent(
        db_session, key="k4", endpoint="t", scope="s", payload={}, now=START + timedelta(hours=25),
        handler=lambda: (200, {"v": 2}),
    )
    assert later.body == {"v": 2} and not later.replayed


@pytest.mark.parametrize("bad_key", ["", "x" * 129])
def test_idempotency_key_length_validated(db_session, bad_key):
    from app.core.errors import AppError

    with pytest.raises(AppError):
        run_idempotent(db_session, key=bad_key, endpoint="t", scope="s", payload={}, now=START, handler=lambda: (200, {}))


def test_errors_are_not_stored_so_retry_can_succeed(db_session):
    from app.core.errors import AppError

    def failing():
        raise AppError(422, "VALIDATION_ERROR", "nope")

    with pytest.raises(AppError):
        run_idempotent(db_session, key="k5", endpoint="t", scope="s", payload={}, now=START, handler=failing)
    ok = run_idempotent(db_session, key="k5", endpoint="t", scope="s", payload={}, now=START, handler=lambda: (200, {"ok": True}))
    assert ok.body == {"ok": True} and not ok.replayed


# ---------- rate limits ----------

def test_otp_send_rate_limited_per_ip(client):
    codes = [client.post("/auth/otp/send", json={"phone": f"900000000{i}"}).status_code for i in range(6)]
    assert codes == [200] * 5 + [429]
    r = client.post("/auth/otp/send", json={"phone": "9000000009"})
    assert r.json()["error_code"] == "RATE_LIMITED"
    assert int(r.headers["Retry-After"]) >= 1


def test_login_rate_limited(client):
    codes = [client.post("/auth/login", json={"username": "x", "password": "y"}).status_code for _ in range(6)]
    assert codes == [401] * 5 + [429]


@pytest.mark.parametrize("profile", ["simulation", "off"])
def test_simulation_and_off_profiles_relax_technical_limits(settings, clock, db_session, profile):
    app = create_app(settings.model_copy(update={"rate_limit_profile": profile}), clock)
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        codes = {c.post("/auth/login", json={"username": "x", "password": "y"}).status_code for _ in range(8)}
    assert codes == {401}


@pytest.mark.parametrize("url", ["postgres://u:p@h/db?sslmode=require", "postgresql://u:p@h/db?sslmode=require",
                                 "postgresql+psycopg://u:p@h/db?sslmode=require"])
def test_hosted_database_urls_use_psycopg3(url):
    assert normalise_database_url(url) == "postgresql+psycopg://u:p@h/db?sslmode=require"


# ---------- clock ----------


def test_clock_start_must_have_offset_and_is_refused_in_production(clean_env):
    with pytest.raises(ConfigurationError, match="timezone offset"):
        load_settings(_env_file=None, clock_start="2026-10-22T09:00:00", **GOOD)
    with pytest.raises(ConfigurationError, match="CLOCK_START must not be set in production"):
        load_settings(_env_file=None, env="production", clock_start="2026-10-22T09:00:00+05:30", **GOOD)


def test_anchored_clock_starts_at_fixed_instant_and_advances_in_real_time():
    start = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
    c = AnchoredClock(start)
    first, second = c.now(), c.now()
    assert start <= first <= second < start + timedelta(seconds=5)
    with pytest.raises(ValueError):
        AnchoredClock(datetime(2026, 10, 22))


def test_app_uses_anchored_clock_when_clock_start_set(settings, db_session):
    app = create_app(settings.model_copy(update={"clock_start": datetime(2026, 10, 22, 9, 0, tzinfo=UTC)}))
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        clock = c.get("/health").json()["clock"]
    assert clock["kind"] == "anchored" and clock["now"].startswith("2026-10-22T09:00")


# ---------- error shapes ----------

def test_unknown_route_uses_error_shape(client):
    r = client.get("/nope")
    assert r.status_code == 404
    assert set(r.json()) == {"error_code", "message", "details"}


def test_wrong_method_uses_error_shape(client):
    r = client.delete("/health")
    assert r.status_code == 405 and r.json()["error_code"] == "METHOD_NOT_ALLOWED"


def test_unhandled_exception_returns_500_without_internals(app):
    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom")
    assert r.status_code == 500
    assert r.json()["error_code"] == "INTERNAL_ERROR"
    assert "secret" not in r.text


# ---------- health ----------

def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok" and r.json()["database"] == "ok"
    assert r.json()["clock"] == {"kind": "frozen", "now": START.isoformat()}


def test_health_reports_database_down(app):
    dead = make_engine("postgresql+psycopg://nobody:nothing@127.0.0.1:1/none?connect_timeout=1")

    def broken_db():
        with Session(bind=dead) as s:
            yield s

    app.dependency_overrides[get_db] = broken_db
    with TestClient(app) as c:
        r = c.get("/health")
    dead.dispose()
    assert r.status_code == 503
    assert r.json()["error_code"] == "DEPENDENCY_UNAVAILABLE"
    assert r.json()["details"]["database"] == "unreachable"


def test_ping_answers_without_the_database_and_is_not_rate_limited(app):
    def no_db():
        raise AssertionError("/ping must not open a database session")
        yield  # pragma: no cover

    app.dependency_overrides[get_db] = no_db
    with TestClient(app) as c:
        codes = {c.get("/ping").status_code for _ in range(200)}
        head = c.head("/ping")
        body = c.get("/ping").json()
    assert codes == {200} and head.status_code == 200 and body == {"status": "ok"}


def test_openapi_carries_demo_disclaimer(client):
    spec = client.get("/openapi.json").json()
    assert "Not affiliated with any bank or lender" in spec["info"]["description"]
    assert spec["info"]["title"].startswith("Lendwise (Demo)")
