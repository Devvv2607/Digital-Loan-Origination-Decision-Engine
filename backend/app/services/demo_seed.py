"""Load the deployed demo seed (DECISIONS.md D-42, D-44).

The seed (backend/seed/demo_seed.json.gz, built by scripts/build_demo_seed.py) holds the 500
simulated applications with simulated stage timings over the 14 days before its as-of date.
On load, the seed moves forward so its as-of date becomes today: timestamps by a whole number
of days, and calendar dates (including dates inside JSON, such as dates of birth and decision
dates) by the same number of positions on a 365-day calendar, so (month, day) order between
any two dates is kept and every recorded age stays exact across leap years. The demo always
shows the last 14 days and its open offers are still open.
"""

import gzip
import json
import re
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Date, DateTime, Numeric, Uuid, insert
from sqlalchemy.orm import Session

from app.core.masking import hash_pii
from app.engine.policy import seed_policy
from app.models import (
    Applicant,
    Application,
    ApplicationEvent,
    Decision,
    IntegrationCall,
    MockProfile,
    Offer,
    ReferralReview,
)

DEFAULT_SEED_PATH = Path(__file__).resolve().parents[2] / "seed" / "demo_seed.json.gz"

# Parents before children (foreign keys).
TABLES = [
    ("mock_profiles", MockProfile), ("applicants", Applicant), ("applications", Application),
    ("application_events", ApplicationEvent), ("integration_calls", IntegrationCall),
    ("decisions", Decision), ("offers", Offer), ("referral_reviews", ReferralReview),
]

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH = re.compile(r"^\d{4}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def read_seed(path: Path = DEFAULT_SEED_PATH) -> dict[str, Any]:
    with gzip.open(path, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def shift_days(as_of: datetime, now: datetime) -> int:
    """Whole days to move the seed so its as-of instant is the latest one not after `now`."""
    return (now - as_of).days  # floors, so the shifted as-of is never in the future


_CUMULATIVE = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365]  # non-leap year


def _position(d: date) -> int:
    """Position on a calendar of 365-day years (29 February counts as 28 February)."""
    day = 28 if (d.month, d.day) == (2, 29) else d.day
    return d.year * 365 + _CUMULATIVE[d.month - 1] + day - 1


def _from_position(pos: int) -> date:
    year, doy = divmod(pos, 365)
    month = next(m for m in range(1, 13) if doy < _CUMULATIVE[m])
    return date(year, month, doy - _CUMULATIVE[month - 1] + 1)


def shift_date(d: date, calendar_days: int) -> date:
    """Move a date by calendar positions. Ages between two shifted dates never change."""
    return _from_position(_position(d) + calendar_days)


def _add_months(month: str, months: int) -> str:
    y, m = map(int, month.split("-"))
    total = y * 12 + (m - 1) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def shift_value(value: Any, days: int, calendar_days: int, months: int) -> Any:
    """Shift, recursively: datetimes by `days`, dates by `calendar_days` positions, YYYY-MM by `months`."""
    if isinstance(value, dict):
        return {k: shift_value(v, days, calendar_days, months) for k, v in value.items()}
    if isinstance(value, list):
        return [shift_value(v, days, calendar_days, months) for v in value]
    if isinstance(value, str):
        if _DATE.match(value):
            return shift_date(date.fromisoformat(value), calendar_days).isoformat()
        if _DATETIME.match(value):
            try:
                return (datetime.fromisoformat(value) + timedelta(days=days)).isoformat()
            except ValueError:
                return value
        if _MONTH.match(value):
            return _add_months(value, months)
    return value


def _convert(model, row: dict[str, Any], days: int, calendar_days: int, months: int) -> dict[str, Any]:
    out = {}
    for name, value in row.items():
        key = "metadata" if name == "metadata_" else name  # ORM attribute vs column name
        col = model.__table__.columns[key]
        if value is None:
            out[key] = None
        elif isinstance(col.type, DateTime):
            out[key] = datetime.fromisoformat(value) + timedelta(days=days)
        elif isinstance(col.type, Date):
            out[key] = shift_date(date.fromisoformat(value), calendar_days)
        elif isinstance(col.type, Uuid):
            out[key] = uuid.UUID(value)
        elif isinstance(col.type, Numeric) and not isinstance(value, float | int):
            out[key] = Decimal(value)
        else:
            out[key] = shift_value(value, days, calendar_days, months)
    return out


def load_demo_seed(db: Session, now: datetime, pii_hash_key: str, path: Path = DEFAULT_SEED_PATH) -> dict[str, Any]:
    """Insert the seed into an EMPTY database (policy table included) and commit."""
    seed = read_seed(path)
    meta = seed["meta"]
    as_of = datetime.fromisoformat(meta["as_of"])
    days = shift_days(as_of, now)
    shifted_as_of = (as_of + timedelta(days=days)).date()
    calendar_days = _position(shifted_as_of) - _position(as_of.date())  # maps the as-of date exactly
    months = (shifted_as_of.year - as_of.year) * 12 + (shifted_as_of.month - as_of.month)

    seed_policy(db, datetime.fromisoformat(meta["policy_created_at"]) + timedelta(days=days))  # commits
    for key, model in TABLES:
        rows = []
        for raw in seed[key]:
            raw = dict(raw)
            if model is Applicant:
                raw["phone_hash"] = hash_pii(raw.pop("phone"), pii_hash_key)
            rows.append(_convert(model, raw, days, calendar_days, months))
        if rows:
            db.execute(insert(model.__table__), rows)
    db.commit()
    return {"seeded_applications": len(seed["applications"]), "shifted_days": days,
            "seed_as_of": shifted_as_of.isoformat()}
