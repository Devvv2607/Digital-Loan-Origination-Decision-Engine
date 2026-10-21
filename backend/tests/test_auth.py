"""Roles and JWTs: applicant (OTP), ops and admin (env-configured login)."""

import pytest

from tests.conftest import ADMIN, OPS


def test_admin_login(client):
    r = client.post("/auth/login", json=ADMIN)
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
    assert r.json()["expires_in"] == 3600


def test_ops_login(client):
    assert client.post("/auth/login", json=OPS).json()["role"] == "ops"


@pytest.mark.parametrize(
    "creds",
    [
        {"username": "admin", "password": "wrong-password"},
        {"username": "nobody", "password": ADMIN["password"]},
        {"username": "ops", "password": ADMIN["password"]},
    ],
)
def test_bad_credentials_rejected(client, creds):
    r = client.post("/auth/login", json=creds)
    assert r.status_code == 401
    assert r.json() == {
        "error_code": "UNAUTHENTICATED",
        "message": "Incorrect username or password.",
        "details": {},
    }


def test_admin_route_requires_token(client):
    r = client.post("/admin/jobs/expire")
    assert r.status_code == 401 and r.json()["error_code"] == "UNAUTHENTICATED"


def test_admin_route_rejects_applicant_and_ops(client, applicant_headers, ops_headers):
    assert client.post("/admin/jobs/expire", headers=applicant_headers).status_code == 403
    r = client.post("/admin/jobs/expire", headers=ops_headers)
    assert r.status_code == 403 and r.json()["error_code"] == "FORBIDDEN"


def test_admin_route_allows_admin(client, admin_headers):
    assert client.post("/admin/jobs/expire", headers=admin_headers).status_code == 200


def test_applicant_route_rejects_internal_roles(client, admin_headers):
    assert client.post("/applications", headers=admin_headers).status_code == 403


@pytest.mark.parametrize(
    "header",
    ["Bearer not-a-jwt", "Basic abc", "Bearer", "token-without-scheme"],
)
def test_malformed_or_invalid_tokens_rejected(client, header):
    r = client.post("/applications", headers={"Authorization": header})
    assert r.status_code == 401


def test_token_signed_with_other_secret_rejected(client, settings, clock):
    from app.core.security import Role, create_token

    forged = create_token(
        settings.model_copy(update={"jwt_secret": "z" * 40}), clock, "admin", Role.ADMIN
    )
    r = client.post("/admin/jobs/expire", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_token_expires_after_ttl(client, clock, admin_headers):
    clock.advance(minutes=59)
    assert client.post("/admin/jobs/expire", headers=admin_headers).status_code == 200
    clock.advance(minutes=1)
    r = client.post("/admin/jobs/expire", headers=admin_headers)
    assert r.status_code == 401 and "expired" in r.json()["message"]
