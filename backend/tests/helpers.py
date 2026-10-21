"""Helpers that drive applications through the real API (used by engine end-to-end tests)."""

from typing import Any

from fastapi.testclient import TestClient

from app.engine.policy import Policy, RuleView, read_seed_file
from tests.conftest import ADMIN, START, VALID_DETAILS, internal_headers_for

STRONG_PROFILE: dict[str, Any] = {
    "pan_name": "Asha Verma",
    "pan_dob": "1994-03-12",
    "kyc": {"behaviour": "OK"},
    "bureau": {"behaviour": "OK", "score": 781, "existing_monthly_emis": 6000, "active_loans": 1},
    "aa": {"average_monthly_income": 84200},
}


def admin_headers_cached(client: TestClient) -> dict[str, str]:
    """Reuse one admin token per client (the login endpoint is rate-limited to 5/minute)."""
    headers = getattr(client, "_lendwise_admin_headers", None)
    if headers is None:
        headers = internal_headers_for(client, ADMIN)
        client._lendwise_admin_headers = headers
    return headers


def register_profile(client: TestClient, pan: str, profile: dict[str, Any]) -> None:
    r = client.put(f"/mock/profiles/{pan}", json=profile, headers=admin_headers_cached(client))
    if r.status_code == 401:  # token expired after the test moved the clock
        client._lendwise_admin_headers = None
        r = client.put(f"/mock/profiles/{pan}", json=profile, headers=admin_headers_cached(client))
    assert r.status_code == 200, r.text


def prepare(
    client: TestClient,
    headers: dict[str, str],
    pan: str,
    profile: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    aa: str = "APPROVE",
    device_id: str | None = None,
) -> str:
    """Create an application and take it through details, PAN, e-KYC and AA consent."""
    register_profile(client, pan, {**STRONG_PROFILE, **(profile or {})})
    extra = {"X-Device-Id": device_id} if device_id else {}
    app_id = client.post("/applications", headers={**headers, **extra}).json()["id"]
    r = client.patch(f"/applications/{app_id}", json={**VALID_DETAILS, **(details or {})}, headers=headers)
    assert r.status_code == 200, r.text
    assert client.post(f"/applications/{app_id}/submit", headers=headers).status_code == 200
    r = client.post(f"/applications/{app_id}/pan/verify", json={"pan": pan}, headers=headers).json()
    if r["status"] == "NAME_CONFIRMATION_REQUIRED":
        r = client.post(f"/applications/{app_id}/pan/verify",
                        json={"pan": pan, "name_confirmation": "USE_PAN_NAME"}, headers=headers).json()
    assert r["status"] == "VERIFIED", r
    start = client.post(f"/applications/{app_id}/kyc/start", headers=headers).json()
    r = client.post(f"/applications/{app_id}/kyc/complete",
                    json={"kyc_session_id": start["kyc_session_id"], "otp": start["demo_kyc_otp"]}, headers=headers)
    assert r.json()["status"] == "COMPLETE", r.text
    r = client.post(f"/applications/{app_id}/aa/consent", json={"decision": aa}, headers=headers)
    assert r.status_code == 200, r.text
    return app_id


def assess(client: TestClient, app_id: str, headers: dict[str, str]) -> dict:
    r = client.post(f"/applications/{app_id}/assess", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def internal_decision(client: TestClient, app_id: str) -> dict:
    r = client.get(f"/applications/{app_id}/decision", headers=admin_headers_cached(client))
    assert r.status_code == 200, r.text
    return r.json()


def make_policy(
    params: dict[str, dict] | None = None,
    disabled: set[str] | None = None,
    outcomes: dict[str, str] | None = None,
    version: int = 1,
) -> Policy:
    """A Policy built from the seed file without a database (for pure engine tests)."""
    params, disabled, outcomes = params or {}, disabled or set(), outcomes or {}
    rules = {}
    for r in read_seed_file()["rules"]:
        rid = r["rule_id"]
        rules[rid] = RuleView(
            rule_id=rid, kind=r["kind"], name=r["name"], enabled=rid not in disabled,
            parameters={**r["parameters"], **params.get(rid, {})},
            outcome_on_fail=outcomes.get(rid, r.get("outcome_on_fail")), reason_codes=r["reason_codes"],
            version=version, created_by="test", change_comment=None, created_at=START,
        )
    return Policy(version=version, rules=rules)
