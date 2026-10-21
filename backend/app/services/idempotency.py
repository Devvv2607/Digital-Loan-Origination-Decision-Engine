"""Idempotency-Key handling (docs/API.md §0.4).

Same key + same body -> stored response is replayed. Same key + different body -> 422.
Errors are not stored, so a failed request can be retried with the same key.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import product
from app.core.errors import AppError
from app.models import IdempotencyKey

MAX_KEY_LENGTH = 128


@dataclass
class IdempotentResult:
    status_code: int
    body: dict[str, Any]
    replayed: bool


def _request_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _lookup(db: Session, key: str, endpoint: str, scope: str, now: datetime) -> IdempotencyKey | None:
    """Return the live record for this key, deleting it first if it is older than the TTL."""
    record = db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.key == key,
            IdempotencyKey.endpoint == endpoint,
            IdempotencyKey.scope == scope,
        )
    )
    if record is not None and record.created_at <= now - product.IDEMPOTENCY_KEY_TTL:
        db.delete(record)
        db.flush()
        return None
    return record


def _replay(record: IdempotencyKey, request_hash: str) -> IdempotentResult:
    if record.request_hash != request_hash:
        raise AppError(
            422,
            "IDEMPOTENCY_KEY_REUSED",
            "This Idempotency-Key was already used with a different request.",
        )
    return IdempotentResult(record.response_status, record.response_body, replayed=True)


def run_idempotent(
    db: Session,
    *,
    key: str | None,
    endpoint: str,
    scope: str,
    payload: Any,
    now: datetime,
    handler: Callable[[], tuple[int, dict[str, Any]]],
) -> IdempotentResult:
    """Run `handler` at most once per (key, endpoint, scope). The handler must not commit."""
    if key is None:
        status, body = handler()
        db.commit()
        return IdempotentResult(status, body, replayed=False)

    if not key or len(key) > MAX_KEY_LENGTH:
        raise AppError(422, "VALIDATION_ERROR", f"Idempotency-Key must be 1-{MAX_KEY_LENGTH} characters.")

    request_hash = _request_hash(payload)
    if existing := _lookup(db, key, endpoint, scope, now):
        return _replay(existing, request_hash)

    status, body = handler()
    db.add(
        IdempotencyKey(
            key=key,
            endpoint=endpoint,
            scope=scope,
            request_hash=request_hash,
            response_status=status,
            response_body=body,
            created_at=now,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request with the same key won; its work is the one that counts.
        db.rollback()
        existing = _lookup(db, key, endpoint, scope, now)
        if existing is None:
            raise
        return _replay(existing, request_hash)
    return IdempotentResult(status, body, replayed=False)
