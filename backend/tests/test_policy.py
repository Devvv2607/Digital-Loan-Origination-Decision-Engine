"""US-10: versioned, configurable policy; admin endpoints; R2 seeding script."""

import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.core.errors import AppError
from app.engine.policy import (
    DEFAULT_SEED_PATH,
    ELIGIBILITY_RULES,
    FRAUD_CHECKS,
    load_policy,
    seed_policy,
    update_rule,
)
from app.main import create_app
from tests.conftest import START

ROOT = Path(__file__).resolve().parents[2]


def load_seed_script():
    spec = importlib.util.spec_from_file_location("seed_script", ROOT / "scripts" / "seed_policy_from_cutoff.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------- seed + load ----------

def test_seed_policy_has_exactly_6_rules_4_fraud_checks_and_pricing(db_session):
    policy = load_policy(db_session)
    assert policy.version == 1
    kinds = {}
    for r in policy.rules.values():
        kinds.setdefault(r.kind, []).append(r.rule_id)
    assert sorted(kinds["ELIGIBILITY"]) == list(ELIGIBILITY_RULES)
    assert sorted(kinds["FRAUD"]) == list(FRAUD_CHECKS)
    assert kinds["PRICING"] == ["PRICING"]
    assert policy.rule("R1").change_comment.startswith("Illustrative calibration to the 88.2% approval-rate scenario")


def test_seeding_twice_is_a_no_op(db_session):
    assert seed_policy(db_session, START) is False
    assert load_policy(db_session).version == 1


def test_r2_thresholds_in_db_come_from_seed_file(db_session):
    seed = json.loads(DEFAULT_SEED_PATH.read_text(encoding="utf-8"))
    r2 = next(r for r in seed["rules"] if r["rule_id"] == "R2")["parameters"]
    params = load_policy(db_session).params("R2")
    assert (params.approve_threshold, params.refer_floor) == (r2["approve_threshold"], r2["refer_floor"])


# ---------- versioning ----------

def test_edit_creates_new_version_and_old_version_is_reconstructable(db_session):
    v1 = load_policy(db_session)
    rule, previous = update_rule(db_session, "R4", enabled=None, parameters={"pass_max": 0.45, "refer_max": 0.6},
                                 outcome_on_fail=None, change_comment="Tighten", actor="admin:admin", now=START)
    assert (rule.version, previous) == (2, 1)
    update_rule(db_session, "R3", enabled=False, parameters=None, outcome_on_fail=None,
                change_comment="Pause", actor="admin:admin", now=START)

    latest = load_policy(db_session)
    assert latest.version == 3
    assert latest.params("R4").pass_max == 0.45 and latest.enabled("R3") is False
    again_v1 = load_policy(db_session, 1)
    assert again_v1.params("R4").pass_max == v1.params("R4").pass_max == 0.5
    assert again_v1.enabled("R3") is True
    v2 = load_policy(db_session, 2)
    assert v2.params("R4").pass_max == 0.45 and v2.enabled("R3") is True


@pytest.mark.parametrize(
    ("rule_id", "params", "field_hint"),
    [("R2", {"approve_threshold": 600, "refer_floor": 650}, "refer_floor"),
     ("R4", {"pass_max": 0.7, "refer_max": 0.6}, "pass_max"),
     ("R1", {"min_age_now": 21, "max_age_at_maturity": 60, "surprise": 1}, "surprise"),
     ("R3", {"min_monthly_income": -5}, "min_monthly_income"),
     ("PRICING", {"rate_bands": []}, "rate_bands")],
)
def test_invalid_parameters_rejected_without_new_version(db_session, rule_id, params, field_hint):
    with pytest.raises(AppError) as exc:
        update_rule(db_session, rule_id, enabled=None, parameters=params, outcome_on_fail=None,
                    change_comment="bad", actor="admin:admin", now=START)
    assert exc.value.error_code == "POLICY_VALIDATION_ERROR"
    assert field_hint in json.dumps(exc.value.details)
    assert load_policy(db_session).version == 1


def test_fail_outcome_only_editable_on_single_outcome_rules(db_session):
    update_rule(db_session, "R5", enabled=None, parameters=None, outcome_on_fail="DECLINE",
                change_comment="Stricter", actor="admin:admin", now=START)
    assert load_policy(db_session).rule("R5").outcome_on_fail == "DECLINE"
    with pytest.raises(AppError):
        update_rule(db_session, "R2", enabled=None, parameters=None, outcome_on_fail="REFER",
                    change_comment="no", actor="admin:admin", now=START)


def test_no_op_edit_rejected(db_session):
    with pytest.raises(AppError, match="No changes"):
        update_rule(db_session, "R1", enabled=True, parameters=None, outcome_on_fail=None,
                    change_comment="same", actor="admin:admin", now=START)


# ---------- admin API ----------

def test_rules_are_publicly_readable_in_demo_mode(client):
    r = client.get("/admin/rules")
    assert r.status_code == 200
    body = r.json()
    assert body["policy_version"] == 1 and body["read_only"] is True
    assert [x["rule_id"] for x in body["rules"]] == ["R1", "R2", "R3", "R4", "R5", "R6", "F1", "F2", "F3", "F4", "PRICING"]


def test_rules_need_login_when_demo_read_only_is_off(settings, clock, db_session):
    app = create_app(settings.model_copy(update={"demo_read_only": False}), clock)
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        assert c.get("/admin/rules").status_code == 401
        assert c.get("/admin/rules/versions").status_code == 401


def test_applicants_cannot_read_admin_screens(client, applicant_headers):
    assert client.get("/admin/rules", headers=applicant_headers).status_code == 403


def test_edit_requires_admin(client, ops_headers):
    body = {"parameters": {"pass_max": 0.45, "refer_max": 0.6}, "change_comment": "Tighten FOIR"}
    assert client.put("/admin/rules/R4", json=body).status_code == 401
    assert client.put("/admin/rules/R4", json=body, headers=ops_headers).status_code == 403


def test_admin_edit_and_version_history(client, admin_headers):
    r = client.put("/admin/rules/R4", json={"parameters": {"pass_max": 0.45, "refer_max": 0.6},
                                            "change_comment": "Tighten FOIR pass band"}, headers=admin_headers)
    assert r.status_code == 200
    assert (r.json()["policy_version"], r.json()["previous_version"]) == (2, 1)
    assert client.get("/admin/rules", headers=admin_headers).json()["read_only"] is False

    history = client.get("/admin/rules/versions?rule_id=R4").json()
    assert history["total"] == 2
    assert [(i["policy_version"], i["parameters"]["pass_max"], i["changed_by"]) for i in history["items"]] == [
        (2, 0.45, "admin:admin"), (1, 0.5, "seed")
    ]

    page = client.get("/admin/rules/versions?page=2&page_size=5").json()
    assert (page["page"], page["page_size"], page["total"], len(page["items"])) == (2, 5, 12, 5)


def test_admin_edit_validation_error_shape(client, admin_headers):
    r = client.put("/admin/rules/R2", json={"parameters": {"approve_threshold": 600, "refer_floor": 650},
                                            "change_comment": "oops"}, headers=admin_headers)
    assert r.status_code == 422
    assert r.json()["error_code"] == "POLICY_VALIDATION_ERROR"
    assert r.json()["details"]["rule_id"] == "R2"


def test_unknown_rule_is_404(client, admin_headers):
    r = client.put("/admin/rules/R9", json={"enabled": False, "change_comment": "nope"}, headers=admin_headers)
    assert r.status_code == 404


def test_health_reports_policy_version(client):
    assert client.get("/health").json()["policy_version"] == 1


# ---------- R2 seeding script ----------

def test_seed_script_calibrates_to_reference_approval_rate():
    script = load_seed_script()
    cal = script.calibrate(0.882, 0.05, sample_size=50_000, seed=1)
    assert cal["refer_floor"] < cal["approve_threshold"]
    assert abs(cal["achieved_pass_share"] - 0.882) < 0.01
    assert abs(cal["achieved_refer_share"] - 0.05) < 0.01


def test_seed_script_rejects_impossible_rates():
    script = load_seed_script()
    with pytest.raises(ValueError):
        script.calibrate(1.2, 0.05, 1000, 1)
    with pytest.raises(ValueError):
        script.calibrate(0.97, 0.05, 1000, 1)


def test_committed_seed_file_is_reproducible_from_the_script():
    script = load_seed_script()
    rebuilt = script.build_seed(0.882, 0.05, 200_000, 882)
    committed = json.loads(DEFAULT_SEED_PATH.read_text(encoding="utf-8"))
    assert rebuilt == committed
    assert committed["source"] == (
        "Illustrative calibration to the 88.2% approval-rate scenario from the credit-risk "
        "cut-off project; does not establish equivalent risk."
    )
    ref = committed["reference_model"]
    assert (ref["cutoff_score"], ref["approval_rate_on_test_set"]) == (535, 0.882)
    assert "Metadata only" in ref["note"]
