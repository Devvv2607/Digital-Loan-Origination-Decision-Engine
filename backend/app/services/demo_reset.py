"""Admin "Reset demo data": wipe applications and fixtures, restore policy version 1, and (on the
deployed demo) restore the 500 seeded applications (D-42)."""

from datetime import datetime
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.engine.policy import seed_policy
from app.services.demo_seed import DEFAULT_SEED_PATH, load_demo_seed
from app.models import (
    Applicant,
    Application,
    ApplicationEvent,
    Decision,
    IdempotencyKey,
    IntegrationCall,
    MockProfile,
    Offer,
    OtpAttempt,
    ReferralReview,
    RuleConfig,
)

# Child tables first (foreign keys).
WIPE_ORDER = [IdempotencyKey, ReferralReview, Offer, Decision, IntegrationCall, ApplicationEvent, Application,
              OtpAttempt, Applicant, MockProfile, RuleConfig]


def reset_demo_data(db: Session, now: datetime, *, pii_hash_key: str | None = None,
                    seed_path: Path | None = None) -> dict:
    """Wipe everything. With `pii_hash_key`, restore the demo seed; otherwise leave only policy v1."""
    deleted = {}
    for model in WIPE_ORDER:
        deleted[model.__tablename__] = db.execute(delete(model)).rowcount
    db.flush()
    if pii_hash_key is None:
        seed_policy(db, now)  # commits
        return {"status": "reset", "policy_version": 1, "deleted": deleted, "seeded_applications": 0}
    loaded = load_demo_seed(db, now, pii_hash_key, seed_path or DEFAULT_SEED_PATH)  # commits
    return {"status": "reset", "policy_version": 1, "deleted": deleted, **loaded}
