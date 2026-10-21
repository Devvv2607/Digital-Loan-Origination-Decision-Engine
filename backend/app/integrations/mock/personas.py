"""One-click demo personas for the landing page (PRD §9).

Each start registers a mock fixture for a *fresh* synthetic PAN, so two visitors trying the
same persona never collide on the duplicate-PAN check. The Duplicate PAN persona instead
reuses a PAN held by a standing demo application, which is kept active.
"""

import secrets
import string
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.masking import hash_pii
from app.integrations.registry import MockProfileStore
from app.models import Applicant, Application, MockProfile
from app.services.applications import create_application, touch
from app.state_machine.machine import transition
from app.state_machine.states import ACTIVE_STATES, AppState

DUPLICATE_PAN = "LWDPP0001K"
HOLDER_PHONE_KEY = "demo-duplicate-pan-holder"  # hashed like a phone; not a real number

BASE_DETAILS = {
    "date_of_birth": "1994-03-12",
    "employment_type": "SALARIED",
    "employer_name": "Example Systems Pvt Ltd",
    "months_in_current_job": 30,
    "declared_monthly_income": 85000,
    "loan_amount": 500000,
    "tenure_months": 36,
    "purpose": "HOME_RENOVATION",
}

PERSONAS: dict[str, dict[str, Any]] = {
    "strong": {
        "label": "Strong borrower",
        "description": "Salaried, good bureau score, low existing EMIs, bank data shared.",
        "expected_outcome": "Instant approval and a KFS-style offer you can accept, e-sign and disburse.",
        "details": {**BASE_DETAILS, "full_name": "Asha Verma"},
        "bureau": {"behaviour": "OK", "score": 781, "existing_monthly_emis": 6000, "active_loans": 1},
        "aa": {"average_monthly_income": 84200},
        "aa_decision": "APPROVE",
    },
    "new-to-credit": {
        "label": "New to credit",
        "description": "First job, no credit history with the bureau.",
        "expected_outcome": "Referred to a credit analyst, not declined (thin file).",
        "details": {**BASE_DETAILS, "full_name": "Kabir Rao", "date_of_birth": "2002-08-21",
                    "months_in_current_job": 14, "declared_monthly_income": 52000, "loan_amount": 200000,
                    "tenure_months": 24},
        "bureau": {"behaviour": "NTC"},
        "aa": {"average_monthly_income": 51800},
        "aa_decision": "APPROVE",
    },
    "high-foir": {
        "label": "High FOIR",
        "description": "Good score, but existing EMIs already take a large share of income.",
        "expected_outcome": "Referred: repayments would be 50-60% of income (FOIR grey zone).",
        "details": {**BASE_DETAILS, "full_name": "Meera Iyer"},
        "bureau": {"behaviour": "OK", "score": 762, "existing_monthly_emis": 30000, "active_loans": 3},
        "aa": {"average_monthly_income": 84600},
        "aa_decision": "APPROVE",
    },
    "duplicate-pan": {
        "label": "Duplicate PAN",
        "description": "This PAN already has an application in progress.",
        "expected_outcome": "Stopped at the PAN step with a neutral message (fraud check F1).",
        "details": {**BASE_DETAILS, "full_name": "Rohan Mehta"},
        "bureau": {"behaviour": "OK", "score": 790},
        "aa": {"average_monthly_income": 85000},
        "aa_decision": "APPROVE",
    },
    "income-mismatch": {
        "label": "Income mismatch",
        "description": "Declares ₹1,20,000 a month; bank data shows about ₹72,000.",
        "expected_outcome": "Referred with a neutral 'we need to review a few details' (fraud check F4).",
        "details": {**BASE_DETAILS, "full_name": "Priya Nair", "declared_monthly_income": 120000},
        "bureau": {"behaviour": "OK", "score": 774, "existing_monthly_emis": 4000, "active_loans": 1},
        "aa": {"average_monthly_income": 72400},
        "aa_decision": "APPROVE",
    },
}


def _fixture(persona: dict[str, Any]) -> dict[str, Any]:
    d = persona["details"]
    return {
        "pan_name": d["full_name"],
        "pan_dob": d["date_of_birth"],
        "kyc": {"behaviour": "OK"},
        "bureau": persona["bureau"],
        "aa": persona["aa"],
    }


def _fresh_pan(db: Session) -> str:
    letters = string.ascii_uppercase
    while True:
        pan = (
            "".join(secrets.choice(letters) for _ in range(3)) + "P" + secrets.choice(letters)
            + f"{secrets.randbelow(10_000):04d}" + secrets.choice(letters)
        )
        taken = db.get(MockProfile, pan) or db.scalar(select(Application.id).where(Application.pan == pan).limit(1))
        if not taken:
            return pan


def _demo_phone() -> str:
    # Synthetic range used only by the demo; no SMS is ever sent and numbers are stored hashed.
    return f"90000{secrets.randbelow(100_000):05d}"


def ensure_duplicate_holder(db: Session, settings: Settings, now: datetime) -> Application:
    """Keep one active application holding DUPLICATE_PAN so the F1 persona always triggers."""
    holder = db.scalar(
        select(Application).where(
            Application.pan == DUPLICATE_PAN,
            Application.state.in_([s.value for s in ACTIVE_STATES]),
        ).limit(1)
    )
    if holder is not None:
        touch(holder, now)  # never let it expire while the demo is in use
        return holder

    phone_hash = hash_pii(HOLDER_PHONE_KEY, settings.pii_hash_key)
    applicant = db.scalar(select(Applicant).where(Applicant.phone_hash == phone_hash))
    if applicant is None:
        applicant = Applicant(phone_hash=phone_hash, phone_last4="0000", created_at=now)
        db.add(applicant)
        db.flush()
    holder = create_application(db, applicant.id, "demo-holder-device", now)
    persona = PERSONAS["duplicate-pan"]
    for field, value in persona["details"].items():
        setattr(holder, field, datetime.fromisoformat(value).date() if field == "date_of_birth" else value)
    transition(db, holder, AppState.KYC_PENDING, actor="system", reason="DEMO_HOLDER", now=now)
    holder.pan = DUPLICATE_PAN
    holder.pan_status = "VERIFIED"
    holder.pan_name = persona["details"]["full_name"].upper()
    holder.pan_name_similarity = 1.0
    return holder


def start_persona(db: Session, settings: Settings, persona_id: str, now: datetime) -> dict[str, Any] | None:
    persona = PERSONAS.get(persona_id)
    if persona is None:
        return None
    store = MockProfileStore(db)
    if persona_id == "duplicate-pan":
        store.upsert(DUPLICATE_PAN, _fixture(persona), "demo", now)
        ensure_duplicate_holder(db, settings, now)
        pan = DUPLICATE_PAN
    else:
        pan = _fresh_pan(db)
        store.upsert(pan, _fixture(persona), "demo", now)
    db.commit()
    return {
        "persona_id": persona_id,
        "label": persona["label"],
        "description": persona["description"],
        "expected_outcome": persona["expected_outcome"],
        "phone": _demo_phone(),
        "pan": pan,
        "details": persona["details"],
        "aa_decision": persona["aa_decision"],
    }
