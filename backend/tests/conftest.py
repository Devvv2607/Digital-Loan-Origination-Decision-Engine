"""Shared fixtures.

- The test database is rebuilt once per session by running the real Alembic migrations.
- Each test runs inside a transaction that is rolled back afterwards (service-level
  commits become savepoints), so tests are isolated and fast.
- Time comes from a FrozenClock that tests can advance.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.clock import FrozenClock
from app.core.config import load_settings
from app.core.db import get_db
from app.engine.policy import seed_policy
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://lendwise:lendwise_local_only@localhost:55432/lendwise_test",
)
START = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)

ADMIN = {"username": "admin", "password": "admin-pass-123"}
OPS = {"username": "ops", "password": "ops-pass-123"}

VALID_DETAILS = {
    "full_name": "Asha Verma",
    "date_of_birth": "1994-03-12",
    "employment_type": "SALARIED",
    "employer_name": "Example Systems Pvt Ltd",
    "months_in_current_job": 30,
    "declared_monthly_income": 85000,
    "loan_amount": 500000,
    "tenure_months": 36,
    "purpose": "HOME_RENOVATION",
}


@pytest.fixture(scope="session")
def settings():
    return load_settings(
        _env_file=None,
        env="test",
        database_url=TEST_DATABASE_URL,
        jwt_secret="test-jwt-secret-" + "x" * 32,
        pii_hash_key="test-pii-key-" + "y" * 16,
        admin_username=ADMIN["username"],
        admin_password=ADMIN["password"],
        ops_username=OPS["username"],
        ops_password=OPS["password"],
        demo_mode=True,
        demo_read_only=True,
        mock_latency_ms=0,
        provider_retry_backoff_ms=0,
        rate_limit_profile="default",
        log_level="WARNING",
    )


@pytest.fixture(scope="session")
def engine(settings):
    eng = create_engine(TEST_DATABASE_URL)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    with Session(eng) as s:
        seed_policy(s, START)  # policy v1 from backend/policy/seed_policy.json, committed once
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine):
    connection = engine.connect()
    outer = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    yield session
    session.close()
    outer.rollback()
    connection.close()


@pytest.fixture
def clock():
    return FrozenClock(START)


def build_app(settings, clock, db_session):
    application = create_app(settings, clock)
    application.dependency_overrides[get_db] = lambda: db_session
    return application


@pytest.fixture
def app(settings, clock, db_session):
    application = build_app(settings, clock, db_session)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


# ---------- helpers ----------

def applicant_headers_for(client: TestClient, phone: str = "9000000001") -> dict[str, str]:
    sent = client.post("/auth/otp/send", json={"phone": phone})
    assert sent.status_code == 200, sent.text
    verified = client.post("/auth/otp/verify", json={"phone": phone, "otp": sent.json()["demo_otp"]})
    assert verified.status_code == 200, verified.text
    return {"Authorization": f"Bearer {verified.json()['access_token']}"}


def internal_headers_for(client: TestClient, creds: dict[str, str]) -> dict[str, str]:
    r = client.post("/auth/login", json=creds)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def create_application(client: TestClient, headers: dict[str, str], **extra_headers) -> str:
    r = client.post("/applications", headers={**headers, **extra_headers})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def create_submitted_application(client: TestClient, headers: dict[str, str]) -> str:
    app_id = create_application(client, headers)
    assert client.patch(f"/applications/{app_id}", json=VALID_DETAILS, headers=headers).status_code == 200
    assert client.post(f"/applications/{app_id}/submit", headers=headers).status_code == 200
    return app_id


@pytest.fixture
def applicant_headers(client):
    return applicant_headers_for(client)


@pytest.fixture
def admin_headers(client):
    return internal_headers_for(client, ADMIN)


@pytest.fixture
def ops_headers(client):
    return internal_headers_for(client, OPS)
