"""Admin "Reset demo data": wipe applications and fixtures, restore policy version 1."""

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.engine.policy import seed_policy
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


def reset_demo_data(db: Session, now: datetime) -> dict:
    deleted = {}
    for model in WIPE_ORDER:
        deleted[model.__tablename__] = db.execute(delete(model)).rowcount
    db.flush()
    seed_policy(db, now)  # commits
    return {"status": "reset", "policy_version": 1, "deleted": deleted}
