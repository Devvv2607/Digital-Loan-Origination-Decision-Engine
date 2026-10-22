"""Review about half of the referrals for the deployed demo seed (DECISIONS.md D-44, D-46).

Runs on a COPY of a clean simulation database, never on the database behind the committed
report. Every change goes through the real API: ops reviews via POST /ops/referrals/{id}/review,
and for analyst approvals the applicant accepts, e-signs and draws down the offer, as every
other approval in the simulation does. The database is read only to map applications back to
their synthetic records (for the applicant's phone).

Selection: within each primary reason code, half the referrals (rounded down), chosen with a
fixed random seed. Decisions follow one documented rule per primary reason (REVIEW_RULE). These
are simulated analyst outcomes for the demo, not a credit policy.

Usage (repo root; backend running on the copy with RATE_LIMIT_PROFILE=simulation and a clock
AFTER the simulation run, e.g. CLOCK_START=2026-10-22T12:00:00+05:30, so reviews follow decisions):
  backend/.venv/Scripts/python scripts/review_seed_referrals.py --database-url <copy URL>
"""

import argparse
import json
import random
import sys
import uuid
from datetime import datetime
from collections import defaultdict
from pathlib import Path

import httpx
from dotenv import dotenv_values
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "reports" / "synthetic_applications.json"
RNG_SEED = 20261022

# Primary reason -> (action, analyst note). Simulated outcomes for the demo seed only.
REVIEW_RULE = {
    "ELIG_SCORE_BORDERLINE": ("APPROVE", "Simulated review: score just below the approve line, clean repayment record; approve."),
    "ELIG_THIN_FILE": ("APPROVE", "Simulated review: no bureau history, but verified salary credits are steady; approve."),
    "ELIG_EMPLOYMENT_TENURE": ("APPROVE", "Simulated review: short time in current job, same line of work before; approve."),
    "DATA_INCOME_UNVERIFIED": ("APPROVE", "Simulated review: bank data declined, declared income plausible for the role; approve."),
    "SYS_BUREAU_UNAVAILABLE": ("APPROVE", "Simulated review: bureau was down; other checks clean, priced at the fallback rate; approve."),
    "ELIG_FOIR_HIGH": ("DECLINE", "Simulated review: existing repayments leave too little room for this EMI; decline."),
    "FRAUD_IDENTITY_MISMATCH": ("DECLINE", "Simulated review: identity details could not be reconciled; decline."),
    "FRAUD_INCOME_MISMATCH": ("DECLINE", "Simulated review: declared and verified income differ too much; decline."),
    "FRAUD_VELOCITY": ("DECLINE", "Simulated review: several applications from one phone or device in a day; decline."),
}


class Api:
    def __init__(self, base: str):
        self.c = httpx.Client(base_url=base.rstrip("/"), timeout=120)

    def ok(self, method: str, path: str, token: str | None = None, **kw) -> dict:
        headers = kw.pop("headers", {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = self.c.request(method, path, headers=headers, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--database-url", required=True, help="the COPY the backend is running on (read-only use)")
    ap.add_argument("--env-file", type=Path, default=ROOT / "backend" / ".env", help="for OPS_USERNAME/OPS_PASSWORD")
    args = ap.parse_args()
    env = dotenv_values(args.env_file)
    api = Api(args.api)
    rng = random.Random(RNG_SEED)

    recs = json.loads(INPUT.read_text(encoding="utf-8"))["applications"]
    engine = create_engine(args.database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, device_id FROM applications ORDER BY created_at")).all()
        reviews = conn.scalar(text("SELECT count(*) FROM referral_reviews"))
        last_event = conn.scalar(text("SELECT max(created_at) FROM application_events"))
    if len(rows) != 500 or reviews:
        sys.exit(f"Refusing: expected a clean simulation copy (500 applications, no reviews); found {len(rows)}, {reviews} reviews.")
    server_now = datetime.fromisoformat(api.ok("GET", "/health")["clock"]["now"])
    if server_now <= last_event:
        sys.exit(f"Refusing: the server clock ({server_now}) must be after the last simulation event ({last_event}); "
                 "start it with a later CLOCK_START, e.g. 2026-10-22T12:00:00+05:30.")
    rec_of = {}
    for rec, (app_id, device_id) in zip(recs, rows, strict=True):
        if rec["device_id"] != device_id:
            sys.exit(f"Run order does not match the input file at {rec['id']}")
        rec_of[str(app_id)] = rec

    ops = api.ok("POST", "/auth/login", json={"username": env["OPS_USERNAME"], "password": env["OPS_PASSWORD"]})["access_token"]
    queue, page = [], 1
    while True:
        p = api.ok("GET", f"/ops/referrals?page={page}&page_size=100", ops)
        queue += p["items"]
        if len(queue) >= p["total"]:
            break
        page += 1

    by_reason = defaultdict(list)
    for item in queue:
        by_reason[item["primary_reason_code"]].append(item)
    chosen = []
    for reason in sorted(by_reason):
        items = sorted(by_reason[reason], key=lambda i: rec_of[i["application_id"]]["id"])
        chosen += rng.sample(items, len(items) // 2)
    unknown = {i["primary_reason_code"] for i in chosen} - set(REVIEW_RULE)
    if unknown:
        sys.exit(f"No review rule for {unknown}")

    tokens: dict[str, str] = {}
    counts = defaultdict(int)
    for item in sorted(chosen, key=lambda i: rec_of[i["application_id"]]["id"]):
        app_id, rec = item["application_id"], rec_of[item["application_id"]]
        action, note = REVIEW_RULE[item["primary_reason_code"]]
        api.ok("POST", f"/ops/referrals/{app_id}/review", ops, json={"action": action, "notes": note},
               headers={"Idempotency-Key": str(uuid.uuid4())})
        counts[(item["primary_reason_code"], action)] += 1
        if action == "APPROVE":
            key = rec.get("session_group") or rec["phone"]
            if key not in tokens:
                otp = api.ok("POST", "/auth/otp/send", json={"phone": rec["phone"]})["demo_otp"]
                tokens[key] = api.ok("POST", "/auth/otp/verify", json={"phone": rec["phone"], "otp": otp})["access_token"]
            t, base = tokens[key], f"/applications/{app_id}"
            api.ok("POST", f"{base}/offer/accept", t, json={"kfs_acknowledged": True}, headers={"Idempotency-Key": str(uuid.uuid4())})
            api.ok("POST", f"{base}/offer/esign", t, json={"signature_name": rec["details"]["full_name"]}, headers={"Idempotency-Key": str(uuid.uuid4())})
            api.ok("POST", f"{base}/disburse", t, headers={"Idempotency-Key": str(uuid.uuid4())})

    print(f"Reviewed {len(chosen)} of {len(queue)} referrals; {len(queue) - len(chosen)} left in the queue.")
    for (reason, action), n in sorted(counts.items()):
        print(f"  {reason:<26} {action:<8} {n}")


if __name__ == "__main__":
    main()
