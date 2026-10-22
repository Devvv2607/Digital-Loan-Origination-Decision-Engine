"""Run the 500 synthetic applications through the REAL API and write the report.

Every application goes through the same endpoints the frontend uses: OTP, create, details,
submit, PAN, e-KYC, AA consent, assess, and (for approvals) accept, e-sign and disburse.
Mock-provider fixtures are registered through PUT /mock/profiles (admin), like a provider
sandbox. Nothing here calls engine functions directly.

Pre-flight guards: the API must be on the seeded policy (version 1, no edits), hold no
applications, and run its business clock on the dataset's as-of date (CLOCK_START), unless
overridden. Expected outcomes are read from the generator output and are never modified;
mismatches are listed in the report and the script exits non-zero.

Usage (repo root, backend started with RATE_LIMIT_PROFILE=simulation and
CLOCK_START=2026-10-22T09:00:00+05:30, the as-of date in the input file):
  backend/.venv/Scripts/python scripts/run_simulation.py
Outputs: reports/simulation_results.csv, reports/simulation_report.md

--report-only DIR writes the CSV and report to DIR instead (for experiments such as a policy
mutation check); nothing under reports/ is touched.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "reports" / "synthetic_applications.json"
CSV_OUT = ROOT / "reports" / "simulation_results.csv"
MD_OUT = ROOT / "reports" / "simulation_report.md"
SIMULATOR_VERSION = "1.0.0"

DECISIONS = ["APPROVED", "REFERRED", "DECLINED"]
NO_DECISION = ["BLOCKED_AT_PAN", "KYC_PENDING"]
RULES = ["R1", "R2", "R3", "R4", "R5", "R6"]
FRAUD = ["F1", "F2", "F3", "F4"]

# The 8-state machine, written out independently of the backend (docs/STATE_MACHINE.md §3).
ALLOWED = {
    None: {"DRAFT"},
    "DRAFT": {"KYC_PENDING", "EXPIRED"},
    "KYC_PENDING": {"UNDER_ASSESSMENT", "EXPIRED"},
    "UNDER_ASSESSMENT": {"APPROVED", "REFERRED", "DECLINED"},
    "REFERRED": {"APPROVED", "DECLINED"},
    "APPROVED": {"DISBURSED", "EXPIRED"},
}


class Api:
    def __init__(self, base: str):
        self.c = httpx.Client(base_url=base.rstrip("/"), timeout=120)

    def call(self, method: str, path: str, token: str | None = None, **kw) -> httpx.Response:
        headers = kw.pop("headers", {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return self.c.request(method, path, headers=headers, **kw)

    def ok(self, method: str, path: str, token: str | None = None, **kw) -> dict:
        r = self.call(method, path, token, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json()


def git_commit() -> str:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "backend", "scripts"], cwd=ROOT, text=True).strip()
        return sha + (" (with uncommitted changes in backend/ or scripts/)" if dirty else "")
    except Exception:  # noqa: BLE001
        return "unknown"


def login(api: Api, phone: str) -> str:
    otp = api.ok("POST", "/auth/otp/send", json={"phone": phone})["demo_otp"]
    if not otp:
        raise RuntimeError("DEMO_MODE must be on so the simulated OTP is returned")
    return api.ok("POST", "/auth/otp/verify", json={"phone": phone, "otp": otp})["access_token"]


def run_one(api: Api, rec: dict, token: str, admin: str) -> dict:
    """Drive one application through the journey. Returns what actually happened."""
    out: dict = {"application_id": None, "actual_outcome": None, "error": None}
    if rec["fixture"]:
        api.ok("PUT", f"/mock/profiles/{rec['pan']}", admin, json=rec["fixture"])
    app_id = api.ok("POST", "/applications", token, headers={"X-Device-Id": rec["device_id"]})["id"]
    out["application_id"] = app_id
    base = f"/applications/{app_id}"
    api.ok("PATCH", base, token, json=rec["details"])
    api.ok("POST", f"{base}/submit", token, headers={"Idempotency-Key": str(uuid.uuid4())})

    r = api.call("POST", f"{base}/pan/verify", token, json={"pan": rec["pan"]})
    if r.status_code == 409 and r.json().get("error_code") == "APPLICATION_ALREADY_IN_PROGRESS":
        out["actual_outcome"] = "BLOCKED_AT_PAN"
        return out
    if r.status_code != 200 or r.json()["status"] != "VERIFIED":
        out["actual_outcome"] = f"ERROR:PAN_{r.json().get('status') or r.json().get('error_code')}"
        return out

    s = api.ok("POST", f"{base}/kyc/start", token)
    r = api.call("POST", f"{base}/kyc/complete", token, json={"kyc_session_id": s["kyc_session_id"], "otp": s["demo_kyc_otp"]})
    if r.status_code == 202:
        out["actual_outcome"] = "KYC_PENDING" if r.json()["state"] == "KYC_PENDING" else f"ERROR:KYC_{r.json()['state']}"
        return out
    if r.status_code != 200 or r.json()["status"] != "COMPLETE":
        out["actual_outcome"] = f"ERROR:KYC_{r.json().get('status') or r.json().get('error_code')}"
        return out

    api.ok("POST", f"{base}/aa/consent", token, json={"decision": rec["aa_decision"]})
    decision = api.ok("POST", f"{base}/assess", token, headers={"Idempotency-Key": str(uuid.uuid4())})
    out["actual_outcome"] = decision["outcome"]

    if decision["outcome"] == "APPROVED" and not rec["hold_offer"]:
        api.ok("POST", f"{base}/offer/accept", token, json={"kfs_acknowledged": True}, headers={"Idempotency-Key": str(uuid.uuid4())})
        api.ok("POST", f"{base}/offer/esign", token, json={"signature_name": rec["details"]["full_name"]}, headers={"Idempotency-Key": str(uuid.uuid4())})
        api.ok("POST", f"{base}/disburse", token, headers={"Idempotency-Key": str(uuid.uuid4())})
    return out


def collect(api: Api, app_id: str, token: str, admin: str) -> dict:
    """Read back the decision (internal view) and the event log for one application."""
    view = api.ok("GET", f"/applications/{app_id}", token)
    timeline = view["timeline"]
    info: dict = {"final_state": view["state"], "timeline": timeline}
    r = api.call("GET", f"/applications/{app_id}/decision", admin)
    if r.status_code == 200:
        d = r.json()
        info.update(decision=d, reason_codes=d["reason_codes"], primary=d["primary_reason_code"],
                    policy_version=d["policy_version"], rule_results=d["rule_results"],
                    bureau_score=(d["inputs_snapshot"].get("bureau") or {}).get("score"))
    else:
        f1 = [e["reason"] for e in timeline if e["event_type"] == "FRAUD_CHECK"]
        info.update(decision=None, reason_codes=f1, primary=f1[0] if f1 else None, policy_version=None,
                    rule_results=[], bureau_score=None)
    return info


def legal(timeline: list[dict]) -> tuple[bool, str]:
    current = None
    for e in timeline:
        if e["event_type"] != "STATE_CHANGE":
            continue
        if e["from_state"] != current:
            return False, f"gap: expected from {current}, got {e['from_state']}"
        if e["to_state"] not in ALLOWED.get(current, set()):
            return False, f"illegal {current} -> {e['to_state']}"
        current = e["to_state"]
    return (current is not None), ("" if current else "no transitions")


def complete_for_outcome(outcome: str, codes: list[str], rule_results: list[dict]) -> bool:
    has_decline = any(r["result"] == "DECLINE" for r in rule_results)
    has_refer = any(r["result"] == "REFER" for r in rule_results) or any(c.startswith(("SYS_", "DATA_")) for c in codes)
    if outcome == "DECLINED":
        return has_decline and bool(codes)
    if outcome == "REFERRED":
        return has_refer and not has_decline and bool(codes)
    if outcome == "APPROVED":
        return not has_decline and not has_refer
    return True


def pct(n: int, d: int) -> str:
    return f"{n / d:.1%}" if d else "n/a"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default=os.environ.get("SIM_API_URL", "http://localhost:8000"))
    ap.add_argument("--input", type=Path, default=INPUT)
    ap.add_argument("--env-file", type=Path, default=ROOT / "backend" / ".env", help="for ADMIN_USERNAME/ADMIN_PASSWORD")
    ap.add_argument("--allow-non-seed-policy", action="store_true")
    ap.add_argument("--allow-existing-data", action="store_true")
    ap.add_argument("--report-only", type=Path, metavar="DIR",
                    help="write the CSV and report to DIR, not reports/ (experiments; never committed)")
    ap.add_argument("--server-settings", default="RATE_LIMIT_PROFILE=simulation, MOCK_LATENCY_MS=20, PROVIDER_RETRY_BACKOFF_MS=500 (default)",
                    help="recorded in the report: how the backend was launched for this run")
    args = ap.parse_args()
    global CSV_OUT, MD_OUT
    if args.report_only:
        out_dir = args.report_only.resolve()
        if out_dir == (ROOT / "reports").resolve():
            sys.exit("--report-only must point somewhere other than reports/")
        out_dir.mkdir(parents=True, exist_ok=True)
        CSV_OUT, MD_OUT = out_dir / "simulation_results.csv", out_dir / "simulation_report.md"

    env = {**dotenv_values(args.env_file), **{k: v for k, v in os.environ.items() if k.startswith("ADMIN_")}}
    data = json.loads(args.input.read_text(encoding="utf-8"))
    recs, gen_meta = data["applications"], data["metadata"]
    assert len(recs) == 500, f"expected exactly 500 applications, got {len(recs)}"
    api = Api(args.api)

    # ---- pre-flight guards
    health = api.ok("GET", "/health")
    versions = api.ok("GET", "/admin/rules/versions?page_size=100")
    rules_now = api.ok("GET", "/admin/rules")
    seeded = health["policy_version"] == 1 and versions["total"] == 11
    if not seeded and not args.allow_non_seed_policy:
        sys.exit(f"Refusing to run: policy version {health['policy_version']} with {versions['total']} rule rows; expected seed version 1 (11 rows).")
    clock = health.get("clock") or {}
    if clock.get("now", "")[:10] != gen_meta["as_of_date"]:
        sys.exit(f"Refusing to run: the API's business clock reads {clock.get('now')} ({clock.get('kind')}), but the data is "
                 f"designed around {gen_meta['as_of_date']}. Start the backend with "
                 f"CLOCK_START={gen_meta['as_of_date']}T09:00:00+05:30.")
    existing = api.ok("GET", "/metrics/funnel")["stages"][0]["count"]
    if existing and not args.allow_existing_data:
        sys.exit(f"Refusing to run: the API already holds {existing} applications. Reset the database first.")
    r2 = next(r for r in rules_now["rules"] if r["rule_id"] == "R2")["parameters"]
    admin = api.ok("POST", "/auth/login", json={"username": env["ADMIN_USERNAME"], "password": env["ADMIN_PASSWORD"]})["access_token"]

    started = datetime.now(UTC)
    t0 = time.perf_counter()
    tokens: dict[str, str] = {}
    results = []
    for i, rec in enumerate(recs, 1):
        key = rec.get("session_group") or rec["phone"]
        if key not in tokens:
            tokens[key] = login(api, rec["phone"])
        token = tokens[key]
        try:
            out = run_one(api, rec, token, admin)
        except Exception as exc:  # noqa: BLE001 - recorded as an error row, never hidden
            out = {"application_id": None, "actual_outcome": "ERROR:EXCEPTION", "error": str(exc)}
        results.append((rec, out, token))
        if i % 50 == 0:
            print(f"  {i}/500 run ({time.perf_counter() - t0:.0f}s)")
    run_seconds = time.perf_counter() - t0

    rows = []
    for rec, out, token in results:
        info = collect(api, out["application_id"], token, admin) if out["application_id"] else {
            "final_state": None, "timeline": [], "decision": None, "reason_codes": [], "primary": None,
            "policy_version": None, "rule_results": [], "bureau_score": None}
        ok_legal, why = legal(info["timeline"])
        actual = out["actual_outcome"]
        codes = sorted(info["reason_codes"])
        match = actual == rec["expected_outcome"] and codes == rec["expected_reason_codes"]
        rows.append({
            "id": rec["id"], "persona": rec["persona"],
            "expected_outcome": rec["expected_outcome"], "actual_outcome": actual,
            "expected_reason_codes": " ".join(rec["expected_reason_codes"]), "actual_reason_codes": " ".join(codes),
            "match": match, "primary_reason_code": info["primary"] or "",
            "policy_version": info["policy_version"] if info["policy_version"] is not None else "",
            "final_state": info["final_state"] or "", "bureau_score": info["bureau_score"] if info["bureau_score"] is not None else "",
            "legal_transitions": ok_legal, "transition_problem": why,
            "reason_codes_complete": complete_for_outcome(actual, codes, info["rule_results"]) if actual in DECISIONS else True,
            "application_id": out["application_id"] or "", "error": out.get("error") or "",
            "expectation_note": rec["expectation_note"],
            "_rules": info["rule_results"],
        })

    funnel = api.ok("GET", "/metrics/funnel")
    tat = api.ok("GET", "/metrics/tat")
    write_csv(rows)
    write_report(rows, gen_meta, health, versions, r2, funnel, tat, started, run_seconds, args.api, args.server_settings,
                 seeded, bool(args.report_only))
    mismatches = [r for r in rows if not r["match"]]
    print(f"Done in {run_seconds:.0f}s. Match rate {500 - len(mismatches)}/500. Report: {MD_OUT}")
    if mismatches:
        for r in mismatches:
            print(f"  MISMATCH {r['id']} {r['persona']}: expected {r['expected_outcome']} [{r['expected_reason_codes']}], "
                  f"got {r['actual_outcome']} [{r['actual_reason_codes']}] {r['error']}")
        sys.exit(1)


def write_csv(rows: list[dict]) -> None:
    cols = [k for k in rows[0] if not k.startswith("_")]
    with CSV_OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_report(rows, gen_meta, health, versions, r2, funnel, tat, started, run_seconds, api_url, server_settings,
                 seeded=True, report_only=False) -> None:
    n = len(rows)
    actual = Counter(r["actual_outcome"] for r in rows)
    decided = [r for r in rows if r["actual_outcome"] in DECISIONS]
    matches = sum(r["match"] for r in rows)
    L: list[str] = []
    a = L.append

    a("# Simulation report: 500 synthetic applications")
    a("")
    a("> Demo prototype. Simulated integrations and synthetic data. Not affiliated with any bank or lender.")
    a("> Generated by `scripts/run_simulation.py` from a real run against the API. Do not edit by hand.")
    if report_only:
        a("> **Report-only experiment run** (`--report-only`): written outside reports/ and not a committed result.")
    a("")
    a("**What this shows, and what it doesn't.** A 100% match on these defined synthetic scenarios shows that the engine, "
      "state machine and API behave as specified. It does **not** show production readiness or real-world credit-risk "
      "performance: there are no repayment outcomes in this simulation, and the personas were designed to sit clearly "
      "inside or outside each rule.")
    a("")
    a("## Reproducibility")
    a("")
    a("| Item | Value |")
    a("|---|---|")
    for k, v in [
        ("Random seed", gen_meta["random_seed"]), ("Generator version", gen_meta["generator_version"]),
        ("Simulator version", SIMULATOR_VERSION), ("Ages designed around (as-of date)", gen_meta["as_of_date"]),
        ("Policy version used", f"{health['policy_version']} (seed policy; {versions['total']} rule rows, no edits)" if seeded
         else f"{health['policy_version']} (NOT the seed policy; {versions['total']} rule rows)"),
        ("R2 thresholds in force", f"approve ≥ {r2['approve_threshold']}, refer {r2['refer_floor']}–{r2['approve_threshold'] - 1}"),
        ("Business clock", f"{health['clock']['kind']}, started {health['clock']['now'][:19]} (CLOCK_START)"),
        ("Git commit", git_commit()), ("API", api_url), ("Server settings", server_settings),
        ("Run started (UTC)", started.isoformat(timespec="seconds")),
        ("Run time", f"{run_seconds:.0f} s"), ("Applications", n),
    ]:
        a(f"| {k} | {v} |")
    a("")
    a(f"Re-run: reset the database, start the backend with `RATE_LIMIT_PROFILE=simulation` and "
      f"`CLOCK_START={gen_meta['as_of_date']}T09:00:00+05:30`, then run `scripts/run_simulation.py`. The as-of date is fixed, "
      "so the input file and its age cases never expire; `scripts/generate_applications.py` regenerates it byte for byte.")
    a("")

    a("## Outcome distribution")
    a("")
    a("| Outcome | Applications | Share of 500 |")
    a("|---|---|---|")
    for o in DECISIONS + NO_DECISION:
        a(f"| {o} | {actual.get(o, 0)} | {pct(actual.get(o, 0), n)} |")
    other = {k: v for k, v in actual.items() if k not in DECISIONS + NO_DECISION}
    for k, v in other.items():
        a(f"| {k} | {v} | {pct(v, n)} |")
    a("")
    a(f"Engine decisions: {len(decided)}. Approval rate among decided applications: "
      f"{pct(actual.get('APPROVED', 0), len(decided))}. The mix is skewed toward edge cases by design (DECISIONS.md D-29), "
      "so these rates describe the test set, not an applicant population.")
    a("")

    a("## Expected vs actual")
    a("")
    a(f"**Match rate: {matches}/{n} ({pct(matches, n)}).** A row matches when both the outcome and the full set of reason codes equal the expectation.")
    a("")
    a("### Confusion matrix (applications that got a decision or were stopped)")
    a("")
    cats = DECISIONS + NO_DECISION
    a("| Expected \\ Actual | " + " | ".join(cats) + " | Other |")
    a("|---|" + "---|" * (len(cats) + 1))
    for e in cats:
        row = [r for r in rows if r["expected_outcome"] == e]
        cells = [str(sum(r["actual_outcome"] == c for r in row)) for c in cats]
        cells.append(str(sum(r["actual_outcome"] not in cats for r in row)))
        a(f"| **{e}** | " + " | ".join(cells) + " |")
    a("")
    mism = [r for r in rows if not r["match"]]
    a("### Mismatches")
    a("")
    if not mism:
        a("None. Every application produced exactly the expected outcome and reason codes.")
    else:
        a("Listed for review; neither the engine nor the expectations have been changed.")
        a("")
        a("| ID | Persona | Expected | Actual | Expectation note | Diagnosis |")
        a("|---|---|---|---|---|---|")
        for r in mism:
            a(f"| {r['id']} | {r['persona']} | {r['expected_outcome']} [{r['expected_reason_codes']}] | "
              f"{r['actual_outcome']} [{r['actual_reason_codes']}] {r['error'][:80]} | {r['expectation_note']} | Pending review |")
    a("")

    a("### By persona")
    a("")
    a("| Persona | Applications | Matched | Actual outcomes |")
    a("|---|---|---|---|")
    by = defaultdict(list)
    for r in rows:
        by[r["persona"]].append(r)
    for p, rs in by.items():
        outs = ", ".join(f"{k} {v}" for k, v in Counter(r["actual_outcome"] for r in rs).most_common())
        a(f"| {p} | {len(rs)} | {sum(r['match'] for r in rs)} | {outs} |")
    a("")

    a("## How often each rule and check fired")
    a("")
    a("A rule *fires* when it returns DECLINE, REFER or INFO (R6 counter-offer) on an engine decision. F1 fires at the PAN "
      "step, where it blocks the application before any decision.")
    a("")
    a("| Rule | Name | Fired | DECLINE | REFER | INFO | Not evaluated |")
    a("|---|---|---|---|---|---|---|")
    names = {"R1": "Age", "R2": "Credit score", "R3": "Minimum income", "R4": "FOIR", "R5": "Employment stability",
             "R6": "Loan-to-income cap", "F1": "Duplicate PAN", "F2": "Application velocity", "F3": "Identity mismatch",
             "F4": "Income inconsistency"}
    for rid in RULES + FRAUD:
        if rid == "F1":
            f1 = sum(r["actual_outcome"] == "BLOCKED_AT_PAN" for r in rows)
            a(f"| F1 | {names['F1']} | {f1} | – | – | – | – |")
            continue
        res = Counter(rr["result"] for r in rows for rr in r["_rules"] if rr["rule_id"] == rid)
        fired = res["DECLINE"] + res["REFER"] + res["INFO"]
        a(f"| {rid} | {names[rid]} | {fired} | {res['DECLINE']} | {res['REFER']} | {res['INFO']} | {res['NOT_EVALUATED']} |")
    a("")
    a("*Not evaluated:* the engine stops before credit rules when the bureau is unavailable after retries (D-08), so every "
      "rule is skipped for those applications. F4 is also not evaluated when the applicant declined AA consent, because "
      "there is no verified income to compare.")
    a("")

    scored = [r for r in rows if r["bureau_score"] != ""]
    r2_pass = sum(int(r["bureau_score"]) >= r2["approve_threshold"] for r in scored)
    a("## R2 seeding check (credit-risk cut-off scenario)")
    a("")
    a(f"R2 was calibrated so that 88.2% of the mock bureau's population would pass. On this test set, "
      f"{r2_pass} of {len(scored)} scored applicants ({pct(r2_pass, len(scored))}) scored ≥ {r2['approve_threshold']}, and the overall "
      f"engine approval rate was {pct(actual.get('APPROVED', 0), len(decided))}. Both differ from 88.2% because the test set "
      "deliberately over-represents borderline, thin-file and failing applicants, and approval also depends on R1, R3–R6 and "
      "the fraud checks. This calibration is illustrative and does not establish equivalent risk; the reference project's "
      "5.9% payment-difficulty rate is not reproduced or claimed.")
    a("")

    a("## Funnel and time in each state")
    a("")
    a("| Stage | Applications | Drop-off from previous |")
    a("|---|---|---|")
    for s in funnel["stages"]:
        d = s.get("drop_off_from_previous")
        a(f"| {s['stage']} | {s['count']} | {'–' if d is None else f'{d:.1%}'} |")
    a("")
    a(f"Application-to-disbursal conversion: {pct(funnel['stages'][-1]['count'], funnel['stages'][0]['count'])}. "
      f"Instant-decision rate: {funnel['instant_decision_rate']:.1%}. Referral rate: {funnel['referral_rate']:.1%}. "
      f"Fraud-flag rate: {funnel['fraud_flag_rate']:.1%} ({funnel['fraud_flags']} of {funnel['pan_attempts']}).")
    a("")
    a("| State | Left the state | Median | P90 | Still in state |")
    a("|---|---|---|---|---|")
    fmt = lambda v: "–" if v is None else f"{v:.2f} s"  # noqa: E731
    for s in tat["states"]:
        a(f"| {s['state']} | {s['n_completed']} | {fmt(s['median'])} | {fmt(s['p90'])} | {s['currently_in_state']} |")
    a("")
    a("Times are from a scripted run with simulated provider latency, so they measure the system's own processing, not "
      "applicant behaviour. 20 approvals are held at the offer stage (their PANs are reused by the duplicate-PAN cases), "
      "and referrals are left in the queue for analysts.")
    a("")

    a("## Assertions (all 500 applications)")
    a("")
    checks = [
        ("Exactly 500 applications run through the API", n == 500 and all(r["application_id"] for r in rows)),
        ("Reason codes complete for the outcome (every decline has a DECLINE reason; every referral a REFER reason and no DECLINE; approvals neither)",
         all(r["reason_codes_complete"] for r in rows)),
        ("Policy version recorded on every decision (and equal to the version in force)",
         all(r["policy_version"] == health["policy_version"] for r in decided)),
        ("Only legal state transitions in every application's event log", all(r["legal_transitions"] for r in rows)),
        ("No request errors", not any(r["actual_outcome"].startswith("ERROR") for r in rows)),
    ]
    a("| Assertion | Result |")
    a("|---|---|")
    for text, ok in checks:
        a(f"| {text} | {'PASS' if ok else 'FAIL'} |")
    a("")

    a("## Metric definitions")
    a("")
    for k, v in [
        ("Match", "Actual outcome equals the expected outcome AND the set of reason codes equals the expected set."),
        ("Match rate", "Matching applications ÷ 500."),
        ("Outcome", "Engine decision (APPROVED / REFERRED / DECLINED), or BLOCKED_AT_PAN (F1 409 at PAN verification), or KYC_PENDING (e-KYC timed out after retries)."),
        ("Rule fired", "The rule returned DECLINE, REFER or INFO in the decision's rule results; F1 counted from PAN-step blocks."),
        ("Confusion matrix", "Rows: expected outcome from the persona definition. Columns: actual outcome from the API."),
        ("Reason codes complete", "As defined in docs/RULES.md §5."),
        ("Legal transitions", "Every STATE_CHANGE event starts where the previous one ended and is in the allowed-transition table (docs/STATE_MACHINE.md §3)."),
        ("Funnel, conversion, drop-off, instant-decision, referral and fraud-flag rates, TAT", "As defined in docs/PRD.md §7, read from /metrics/funnel and /metrics/tat."),
        ("R2 pass share", "Scored applicants (bureau returned a score) with score ≥ the R2 approve threshold ÷ scored applicants."),
    ]:
        a(f"- **{k}:** {v}")
    a("")
    MD_OUT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
