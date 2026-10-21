"""F1 — Duplicate PAN (EC-11).

Runs at PAN verification, before any provider call. If another non-terminal
application already holds this PAN, the PAN step is blocked with a neutral 409;
no decision is created. From Phase 3 the enabled flag comes from the F1 policy row.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application
from app.state_machine.states import ACTIVE_STATES

RULE_ID = "F1"
REASON_CODE = "FRAUD_DUPLICATE_PAN"
# PAN statuses that mean "this application has claimed the PAN".
CLAIMING_PAN_STATUSES = ("VERIFIED", "NAME_CONFIRMATION_REQUIRED")


def find_active_duplicate(db: Session, pan: str, exclude_application_id: uuid.UUID) -> Application | None:
    return db.scalar(
        select(Application)
        .where(
            Application.pan == pan,
            Application.id != exclude_application_id,
            Application.state.in_([s.value for s in ACTIVE_STATES]),
            Application.pan_status.in_(CLAIMING_PAN_STATUSES),
        )
        .limit(1)
    )
