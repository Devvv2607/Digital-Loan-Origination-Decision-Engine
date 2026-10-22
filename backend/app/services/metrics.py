"""PM metrics (US-12; definitions in docs/PRD.md §7). Computed from applications,
application_events and decisions. Fine for demo-scale data; a real system would
pre-aggregate.
"""

import math
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, ApplicationEvent, Decision
from app.state_machine.states import AppState, EventType

FUNNEL = [
    ("CREATED", None),
    ("SUBMITTED", AppState.KYC_PENDING),
    ("ASSESSED", AppState.UNDER_ASSESSMENT),
    ("APPROVED", AppState.APPROVED),
    ("DISBURSED", AppState.DISBURSED),
]
TAT_STATES = [AppState.DRAFT, AppState.KYC_PENDING, AppState.UNDER_ASSESSMENT, AppState.REFERRED, AppState.APPROVED]

DEFINITIONS = {
    "conversion_application_to_disbursal": "Applications that reached DISBURSED ÷ applications created in the period.",
    "drop_off_from_previous": "1 − (applications reaching this stage ÷ applications reaching the previous stage).",
    "instant_decision_rate": "Engine decisions that were APPROVED or DECLINED ÷ all engine decisions (analyst decisions excluded).",
    "referral_rate": "Engine decisions that were REFERRED ÷ all engine decisions.",
    "fraud_flag_rate": "Applications with at least one FRAUD_* signal (including duplicate-PAN blocks) ÷ applications that attempted PAN verification.",
    "top_reason_codes": "How often each reason code appears across engine decisions.",
    "tat": "Time between entering a state and leaving it, from the event log. Median and 90th percentile over applications that have left the state.",
}


def _period(frm: date | None, to: date | None):
    start = datetime.combine(frm, time.min, tzinfo=UTC) if frm else None
    end = datetime.combine(to + timedelta(days=1), time.min, tzinfo=UTC) if to else None
    return start, end


def _apps(db: Session, frm: date | None, to: date | None) -> list[Application]:
    start, end = _period(frm, to)
    stmt = select(Application)
    if start:
        stmt = stmt.where(Application.created_at >= start)
    if end:
        stmt = stmt.where(Application.created_at < end)
    return list(db.scalars(stmt).all())


def _events_by_app(db: Session, ids: list) -> dict:
    out: dict = defaultdict(list)
    if not ids:
        return out
    for e in db.scalars(
        select(ApplicationEvent).where(ApplicationEvent.application_id.in_(ids)).order_by(ApplicationEvent.seq)
    ):
        out[e.application_id].append(e)
    return out


def _ratio(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def funnel(db: Session, frm: date | None = None, to: date | None = None) -> dict[str, Any]:
    apps = _apps(db, frm, to)
    ids = [a.id for a in apps]
    events = _events_by_app(db, ids)

    reached: dict[str, int] = {}
    for stage, state in FUNNEL:
        if state is None:
            reached[stage] = len(apps)
        else:
            reached[stage] = sum(
                any(e.event_type == EventType.STATE_CHANGE and e.to_state == state for e in events[a.id]) for a in apps
            )
    stages, previous = [], None
    for stage, _ in FUNNEL:
        row: dict[str, Any] = {"stage": stage, "count": reached[stage]}
        if previous is not None:
            row["drop_off_from_previous"] = round(1 - reached[stage] / reached[previous], 4) if reached[previous] else None
        stages.append(row)
        previous = stage

    decisions = list(db.scalars(select(Decision).where(Decision.application_id.in_(ids)))) if ids else []
    engine = [d for d in decisions if d.source == "ENGINE"]
    manual = [d for d in decisions if d.source == "MANUAL"]
    mix = Counter(d.outcome for d in engine)
    reasons = Counter(code for d in engine for code in d.reason_codes)

    attempted = flagged = 0
    for a in apps:
        f1 = any(e.event_type == EventType.FRAUD_CHECK for e in events[a.id])
        if a.pan_status != "NOT_STARTED" or f1:
            attempted += 1
            engine_codes = next((d.reason_codes for d in engine if d.application_id == a.id), [])
            if f1 or any(c.startswith("FRAUD_") for c in engine_codes):
                flagged += 1

    return {
        "period": {"from": frm.isoformat() if frm else None, "to": to.isoformat() if to else None},
        "stages": stages,
        "conversion_application_to_disbursal": _ratio(reached["DISBURSED"], reached["CREATED"]),
        "decision_mix": {k: mix.get(k, 0) for k in ("APPROVED", "REFERRED", "DECLINED")},
        "analyst_decisions": {k: sum(d.outcome == k for d in manual) for k in ("APPROVED", "DECLINED")},
        "engine_decisions": len(engine),
        "instant_decision_rate": _ratio(mix["APPROVED"] + mix["DECLINED"], len(engine)),
        "referral_rate": _ratio(mix["REFERRED"], len(engine)),
        "fraud_flag_rate": _ratio(flagged, attempted),
        "fraud_flags": flagged,
        "pan_attempts": attempted,
        "top_reason_codes": [{"code": c, "count": n} for c, n in reasons.most_common(10)],
        "definitions": DEFINITIONS,
    }


def percentile(values: list[float], q: float) -> float | None:
    """Linear interpolation between closest ranks (the common 'type 7' definition)."""
    if not values:
        return None
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def tat(db: Session, frm: date | None = None, to: date | None = None) -> dict[str, Any]:
    apps = _apps(db, frm, to)
    events = _events_by_app(db, [a.id for a in apps])
    durations: dict[str, list[float]] = defaultdict(list)
    current: Counter = Counter()
    for a in apps:
        changes = [e for e in events[a.id] if e.event_type == EventType.STATE_CHANGE]
        for entered, left in zip(changes, changes[1:], strict=False):
            durations[entered.to_state].append((left.created_at - entered.created_at).total_seconds())
        if changes and changes[-1].to_state in {s.value for s in TAT_STATES}:
            current[changes[-1].to_state] += 1
    rows = []
    for state in TAT_STATES:
        d = durations[state.value]
        rows.append({
            "state": state.value,
            "n_completed": len(d),
            "median": round(percentile(d, 0.5), 3) if d else None,
            "p90": round(percentile(d, 0.9), 3) if d else None,
            "currently_in_state": current[state.value],
        })
    seeded = sum(a.is_seeded for a in apps)
    return {
        "unit": "seconds", "states": rows, "definition": DEFINITIONS["tat"],
        # Seeded demo applications carry simulated stage durations, not measurements (D-44).
        "simulated_timings": seeded > 0,
        "seeded_applications": seeded,
        "applications": len(apps),
    }
