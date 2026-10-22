"""Build the deployed demo seed from a clean 500-application simulation run (DECISIONS.md D-42, D-44).

The simulation (scripts/run_simulation.py) produces the applications, decisions, offers, events
and provider calls through the real API, but in about four minutes, so every stage takes
fractions of a second. For the deployed demo only, this script keeps every record exactly as
the engine produced it and re-times each journey with SIMULATED durations drawn from the
assumed distributions below, spread over the 14 days before the as-of date. The Phase 6
report (reports/simulation_report.md) keeps the real run's timings and is not affected.

Re-timing rules
- Gaps the applicant or operations would cause (filling in details, PAN, e-KYC, bank consent,
  asking for the decision, accepting the offer, e-signing, disbursal) are drawn from the
  log-normal distributions in DURATIONS (median and 90th percentile, in seconds).
- Gaps inside one request (provider retries, the bureau call, the engine decision, offer
  generation) keep the real run's values.
- Arrivals: a random day in the window and a daytime hour (centred 14:30 IST, sd 3.5 h,
  07:30-23:30). Every journey ends before the as-of instant.
- Constraints kept: the 20 held offers are generated in the last 6 days (still open at the
  as-of date, validity 7 days); each duplicate-PAN attempt comes after its original's offer;
  each velocity group's 5 applications arrive minutes apart, in the original order.
- About half the referrals were reviewed through the API by scripts/review_seed_referrals.py (D-46);
  their review gap is drawn from DURATIONS["review"]. Referrals still pending arrive in the last
  4 days, so the queue looks like a recent backlog.
- Each application's own calendar dates (date of birth, PAN/KYC dates, decision date, R1 maturity
  date, provider payloads) move by the same number of days as its re-timed decision, so the
  recorded decision date matches its timestamp and every age is unchanged.

Phones are written in clear (they are the synthetic numbers already in
reports/synthetic_applications.json); the loader stores only their keyed hash with the
deployment's PII_HASH_KEY. OTP attempts and idempotency keys are not part of the seed.

Usage (repo root; PII_HASH_KEY from backend/.env; --database-url points at the copy of a clean
simulation run on policy version 1 that scripts/review_seed_referrals.py has reviewed):
  backend/.venv/Scripts/python scripts/build_demo_seed.py --database-url <copy URL>
Writes backend/seed/demo_seed.json.gz and prints the resulting stage timings.
"""

import argparse
import gzip
import json
import math
import random
import sys
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from dotenv import dotenv_values
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.masking import hash_pii  # noqa: E402
from app.services.demo_seed import shift_value  # noqa: E402
from app.services.metrics import percentile  # noqa: E402  (same definition as the dashboard)
from app.models import (  # noqa: E402
    Applicant,
    Application,
    ApplicationEvent,
    Decision,
    IntegrationCall,
    MockProfile,
    Offer,
    ReferralReview,
    RuleConfig,
)

SEED_VERSION = "1.0.0"
RNG_SEED = 20261022
IST = timezone(timedelta(hours=5, minutes=30))
AS_OF = datetime(2026, 10, 22, 9, 0, tzinfo=IST)  # same fixed instant as the simulation's CLOCK_START
WINDOW_DAYS = 14
OUTPUT = ROOT / "backend" / "seed" / "demo_seed.json.gz"
INPUT = ROOT / "reports" / "synthetic_applications.json"

# Assumed distributions (log-normal): gap kind -> (median seconds, 90th percentile seconds, label).
DURATIONS = {
    "details": (360, 900, "Filling in personal and loan details"),
    "pan_step": (45, 120, "Entering the PAN after submitting details"),
    "kyc_start": (30, 90, "Starting e-KYC"),
    "kyc_otp": (150, 420, "Receiving and entering the e-KYC code"),
    "aa_consent": (90, 240, "Opening the bank-data consent"),
    "aa_approve": (60, 180, "Approving the consent with the Account Aggregator"),
    "get_decision": (20, 60, "Asking for the decision"),
    "offer_accept": (6 * 3600, 36 * 3600, "Reading and accepting the offer"),
    "esign": (480, 1800, "E-signing the agreement"),
    "review": (3 * 3600, 10 * 3600, "Analyst review of a referral (simulated outcome, D-46)"),
    "disburse": (2 * 3600, 8 * 3600, "Disbursal (simulated payout processing)"),
}
OFFER_ACCEPT_CAP = 6 * 86400  # always inside the 7-day offer validity
Z90 = 1.2815515655446004


def lognormal(rng: random.Random, kind: str) -> float:
    med, p90, _ = DURATIONS[kind]
    value = rng.lognormvariate(math.log(med), math.log(p90 / med) / Z90)
    return min(value, OFFER_ACCEPT_CAP) if kind == "offer_accept" else value


def classify_event(e: ApplicationEvent) -> str:
    if e.event_type == "STATE_CHANGE":
        if e.from_state == "REFERRED":
            return "review"
        return {"DRAFT": "start", "KYC_PENDING": "details", "UNDER_ASSESSMENT": "get_decision",
                "DISBURSED": "disburse"}.get(e.to_state, "system")
    if e.event_type == "OFFER_STATUS":
        return {"ACCEPTED": "offer_accept", "ESIGNED": "esign"}.get(e.to_state, "system")
    if e.event_type == "FRAUD_CHECK":
        return "pan_step"
    return "system"


def classify_call(c: IntegrationCall) -> str:
    if c.attempt != 1:
        return "system"
    return {("pan", "verify"): "pan_step", ("kyc", "start"): "kyc_start", ("kyc", "complete"): "kyc_otp",
            ("aa", "consent_create"): "aa_consent", ("aa", "consent_decision"): "aa_approve"}.get(
        (c.provider, c.operation), "system")


class Timeline:
    """Milestones of one application, re-timed as offsets from its arrival."""

    def __init__(self, milestones: list[tuple[datetime, str]], rng: random.Random):
        milestones.sort(key=lambda m: m[0])
        self.orig: list[datetime] = []
        self.offset: list[float] = []
        self.kinds: list[str] = []
        used: set[str] = set()
        for t, kind in milestones:
            if self.orig and t == self.orig[-1]:
                continue
            if kind in used or kind in ("start", "system"):
                kind = "start" if not self.orig else "system"
            used.add(kind)
            if not self.orig:
                gap = 0.0
            elif kind == "system":
                gap = (t - self.orig[-1]).total_seconds()
            else:
                gap = lognormal(rng, kind)
            self.offset.append((self.offset[-1] if self.offset else 0.0) + gap)
            self.orig.append(t)
            self.kinds.append(kind)
        self.arrival: datetime | None = None

    def length(self) -> float:
        return self.offset[-1]

    def length_to(self, kind: str) -> float:
        return next(o for o, k in zip(self.offset, self.kinds, strict=True) if k == kind)

    def at(self, kind: str) -> datetime:
        return self.arrival + timedelta(seconds=next(o for o, k in zip(self.offset, self.kinds, strict=True) if k == kind))

    def new(self, t: datetime) -> datetime:
        i = bisect_right(self.orig, t) - 1
        if i < 0:
            return self.arrival - (self.orig[0] - t)
        value = self.offset[i] + (t - self.orig[i]).total_seconds()
        if i + 1 < len(self.offset):
            value = min(value, self.offset[i + 1])
        return self.arrival + timedelta(seconds=value)


def daytime_arrival(rng: random.Random, lo: datetime, hi: datetime) -> datetime:
    """A random day in [lo, hi] at a daytime hour (IST)."""
    if hi <= lo:
        raise ValueError("empty arrival window")
    for _ in range(2000):
        day = (lo.astimezone(IST).date() + timedelta(days=rng.randrange((hi - lo).days + 2)))
        hour = min(max(rng.gauss(14.5, 3.5), 7.5), 23.5)
        t = datetime.combine(day, time(0), tzinfo=IST) + timedelta(hours=hour)
        if lo <= t <= hi:
            return t
    return lo + (hi - lo) * rng.random()


def serialise(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    return value


def row(obj, skip=()) -> dict:
    return {c.key: serialise(getattr(obj, c.key)) for c in obj.__mapper__.column_attrs if c.key not in skip}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", type=Path, default=ROOT / "backend" / ".env")
    ap.add_argument("--output", type=Path, default=OUTPUT)
    ap.add_argument("--database-url", help="database to read (default: DATABASE_URL from the env file)")
    args = ap.parse_args()
    env = dotenv_values(args.env_file)
    engine = create_engine((args.database_url or env["DATABASE_URL"]).replace("postgresql://", "postgresql+psycopg://", 1))
    rng = random.Random(RNG_SEED)
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    recs = data["applications"]
    phone_by_hash = {hash_pii(r["phone"], env["PII_HASH_KEY"]): r["phone"] for r in recs}

    with Session(engine) as db:
        # ---- guards: a clean simulation run on the seed policy
        n_apps = db.scalar(select(func.count()).select_from(Application))
        rules = db.scalar(select(func.count()).select_from(RuleConfig))
        version = db.scalar(select(func.max(RuleConfig.version)))
        reviews = db.scalar(select(func.count()).select_from(ReferralReview))
        if (n_apps, rules, version) != (500, 11, 1):
            sys.exit(f"Refusing: expected a simulation run on policy v1 (500 applications, 11 rule rows); "
                     f"found {n_apps} applications, {rules} rule rows, version {version}.")
        review_list = list(db.scalars(select(ReferralReview)))
        apps = list(db.scalars(select(Application).order_by(Application.created_at)))
        events = list(db.scalars(select(ApplicationEvent).order_by(ApplicationEvent.seq)))
        calls = list(db.scalars(select(IntegrationCall)))
        decisions = list(db.scalars(select(Decision)))
        offers = list(db.scalars(select(Offer)))
        applicants = list(db.scalars(select(Applicant)))
        profiles = list(db.scalars(select(MockProfile)))
        policy_created = db.scalar(select(func.min(RuleConfig.created_at)))

    # The simulation runs the records in file order, so creation order identifies each record.
    for rec, a in zip(recs, apps, strict=True):
        if rec["device_id"] != a.device_id:
            sys.exit(f"Run order does not match the input file at {rec['id']}")
    rec_of = {a.id: rec for rec, a in zip(recs, apps, strict=True)}
    app_by_rec = {rec["id"]: a for rec, a in zip(recs, apps, strict=True)}

    milestones = defaultdict(list)
    for e in events:
        milestones[e.application_id].append((e.created_at, classify_event(e)))
    for c in calls:
        milestones[c.application_id].append((c.created_at, classify_call(c)))
    tl = {a.id: Timeline(milestones[a.id], rng) for a in apps}

    # ---- arrivals
    start, end = AS_OF - timedelta(days=WINDOW_DAYS), AS_OF - timedelta(minutes=5)
    groups = defaultdict(list)
    for a in apps:
        rec = rec_of[a.id]
        if rec["persona"] == "velocity":
            groups[rec.get("session_group") or rec["device_id"]].append(a)
    for a in apps:
        rec, t = rec_of[a.id], tl[a.id]
        if rec["persona"] in ("velocity", "duplicate_pan"):
            continue
        if rec["hold_offer"]:
            lo = AS_OF - timedelta(days=6)
        elif a.state == "REFERRED":
            lo = AS_OF - timedelta(days=4)  # still pending: a recent backlog
        else:
            lo = start
        t.arrival = daytime_arrival(rng, lo, end - timedelta(seconds=t.length()))
    for members in groups.values():
        # One velocity group: each application starts a few minutes after the previous one got its decision.
        span = sum(tl[m.id].length_to("get_decision") + 20 * 60 for m in members) + max(tl[m.id].length() for m in members)
        t0 = daytime_arrival(rng, start, end - timedelta(seconds=span))
        for m in members:
            t = tl[m.id]
            t.arrival = t0
            t0 = t.at("get_decision") + timedelta(minutes=rng.uniform(3, 20))
    for a in apps:
        rec, t = rec_of[a.id], tl[a.id]
        if rec["persona"] == "duplicate_pan":
            original = tl[app_by_rec[rec["duplicate_of"]].id]
            lo = original.new(max(o.created_at for o in offers if o.application_id == app_by_rec[rec["duplicate_of"]].id)) + timedelta(hours=1)
            t.arrival = daytime_arrival(rng, lo, end - timedelta(seconds=t.length()))
    assert all(t.arrival is not None for t in tl.values())
    late = [(rec_of[a.id]["persona"], rec_of[a.id]["id"], round(tl[a.id].length() / 3600, 1)) for a in apps
            if tl[a.id].arrival + timedelta(seconds=tl[a.id].length()) > AS_OF]
    assert not late, late

    # ---- per-application calendar shift: the day the re-timed journey was decided (or last active), in IST
    decided_at = {d.application_id: d.created_at for d in decisions if d.source == "ENGINE"}
    day_shift = {}
    for a in apps:
        t = tl[a.id]
        when = t.new(decided_at[a.id]) if a.id in decided_at else t.arrival
        day_shift[a.id] = (when.astimezone(IST).date() - AS_OF.date()).days

    def dates(r: dict, app_id, keys) -> dict:
        for k in keys:
            if r.get(k) is not None:
                r[k] = shift_value(r[k], day_shift[app_id], day_shift[app_id], 0)  # within October: no 29 Feb
        return r

    # ---- rows with new timestamps
    app_rows = []
    for a in apps:
        r, t = row(a), tl[a.id]
        for k in ("created_at", "updated_at", "last_activity_at", "state_changed_at"):
            r[k] = t.new(getattr(a, k)).isoformat()
        dates(r, a.id, ("date_of_birth", "pan_dob", "kyc_dob", "kyc_address", "aa_income_credits"))
        r["is_seeded"] = True
        app_rows.append(r)
    ev_rows = []
    for e in events:
        r = dates(row(e, skip=("seq",)), e.application_id, ("metadata_",))
        r["created_at"] = tl[e.application_id].new(e.created_at).isoformat()
        ev_rows.append((r["created_at"], e.seq, r))
    ev_rows = [r for *_, r in sorted(ev_rows, key=lambda x: (x[0], x[1]))]
    call_rows = []
    for c in calls:
        r = dates(row(c), c.application_id, ("request", "response"))
        r["created_at"] = tl[c.application_id].new(c.created_at).isoformat()
        call_rows.append(r)
    dec_rows = []
    for d in decisions:
        r = dates(row(d), d.application_id, [k for k, v in row(d).items() if isinstance(v, dict | list)])
        r["created_at"] = tl[d.application_id].new(d.created_at).isoformat()
        dec_rows.append(r)
    offer_rows = []
    for o in offers:
        t, r = tl[o.application_id], row(o)
        r["created_at"] = t.new(o.created_at).isoformat()
        r["expires_at"] = (t.new(o.created_at) + (o.expires_at - o.created_at)).isoformat()
        for k in ("accepted_at", "esigned_at", "disbursed_at"):
            if getattr(o, k):
                r[k] = t.new(getattr(o, k)).isoformat()
        offer_rows.append(r)
    review_rows = []
    for rv in review_list:
        r = row(rv)
        r["created_at"] = tl[rv.application_id].new(rv.created_at).isoformat()
        review_rows.append(r)
    first_app = defaultdict(list)
    for a in apps:
        first_app[a.applicant_id].append(tl[a.id].arrival)
    applicant_rows = []
    for p in applicants:
        r = row(p, skip=("phone_hash",))
        r["phone"] = phone_by_hash[p.phone_hash]
        r["created_at"] = (min(first_app[p.id]) - timedelta(minutes=1)).isoformat()
        applicant_rows.append(r)
    by_pan = defaultdict(list)
    for a in apps:
        if a.pan:
            by_pan[a.pan].append(tl[a.id].arrival)
    first_app_with_pan = {}
    for a in apps:
        if a.pan and a.pan not in first_app_with_pan:
            first_app_with_pan[a.pan] = a.id
    profile_rows = []
    for p in profiles:
        r = row(p)
        if p.pan in first_app_with_pan:
            dates(r, first_app_with_pan[p.pan], ("profile",))
        times = by_pan.get(p.pan) or [start]
        r["created_at"] = (min(times) - timedelta(minutes=2)).isoformat()
        r["updated_at"] = (max(times) - timedelta(minutes=2)).isoformat()
        profile_rows.append(r)

    # ---- resulting stage timings (what the dashboard will show), from the new event times
    durations = defaultdict(list)
    changes = defaultdict(list)
    for r in ev_rows:
        if r["event_type"] == "STATE_CHANGE":
            changes[r["application_id"]].append(r)
    for chs in changes.values():
        for a_, b_ in zip(chs, chs[1:], strict=False):
            durations[a_["to_state"]].append((datetime.fromisoformat(b_["created_at"]) - datetime.fromisoformat(a_["created_at"])).total_seconds())
    timings = {}
    for state, d in durations.items():
        timings[state] = {"n": len(d), "median_s": round(percentile(d, 0.5), 1), "p90_s": round(percentile(d, 0.9), 1)}

    meta = {
        "seed_version": SEED_VERSION,
        "rng_seed": RNG_SEED,
        "as_of": AS_OF.isoformat(),
        "window_days": WINDOW_DAYS,
        "policy_version": 1,
        "policy_created_at": (start - timedelta(days=1)).isoformat(),
        "source": "Clean run of scripts/run_simulation.py (500/500 match) on seed policy v1, re-timed by scripts/build_demo_seed.py.",
        "assumed_distributions": {k: {"median_s": m, "p90_s": p, "what": w, "family": "log-normal"} for k, (m, p, w) in DURATIONS.items()},
        "offer_accept_cap_s": OFFER_ACCEPT_CAP,
        "resulting_stage_timings": timings,
        "counts": {"applicants": len(applicant_rows), "applications": len(app_rows), "events": len(ev_rows),
                   "integration_calls": len(call_rows), "decisions": len(dec_rows), "offers": len(offer_rows),
                   "mock_profiles": len(profile_rows), "referral_reviews": len(review_rows)},
        "note": "Synthetic data. Stage durations are SIMULATED from the assumed distributions above, not measured.",
    }
    seed = {"meta": meta, "mock_profiles": profile_rows, "applicants": applicant_rows, "applications": app_rows,
            "application_events": ev_rows, "integration_calls": call_rows, "decisions": dec_rows, "offers": offer_rows,
            "referral_reviews": review_rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(args.output, "wb", mtime=0) as fh:
        fh.write(json.dumps(seed, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    print(f"Wrote {args.output} ({args.output.stat().st_size // 1024} KB): {meta['counts']}")
    print(f"Window: {start.isoformat()} to {AS_OF.isoformat()}")
    for state in ("DRAFT", "KYC_PENDING", "UNDER_ASSESSMENT", "REFERRED", "APPROVED"):
        print(f"  {state:<17} {timings.get(state, 'no completed stays')}")


if __name__ == "__main__":
    main()
