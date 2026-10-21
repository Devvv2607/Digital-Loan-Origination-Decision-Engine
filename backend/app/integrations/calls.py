"""Every provider call goes through `logged_call`, which writes an `integration_calls`
row (masked request/response, latency, status, attempt). `call_with_retries` adds
retry-with-backoff on timeouts (EC-05, EC-07): 1 call + 2 retries by default.
"""

import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from app.core.masking import PAN_RE, mask_pan, mask_phone
from app.integrations.base import ProviderError, ProviderTimeout
from app.models import IntegrationCall

T = TypeVar("T")
DEFAULT_ATTEMPTS = 3  # first call + 2 retries


def mask_payload(value: Any) -> Any:
    """Mask PAN and phone fields (and any PAN-shaped string) in a JSON-like payload."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "pan" and isinstance(v, str):
                out[k] = mask_pan(v)
            elif k == "phone" and isinstance(v, str):
                out[k] = mask_phone(v)
            else:
                out[k] = mask_payload(v)
        return out
    if isinstance(value, list):
        return [mask_payload(v) for v in value]
    if isinstance(value, str):
        return PAN_RE.sub(lambda m: mask_pan(m.group(0)) or "", value)
    return value


def logged_call(
    db: Session,
    *,
    provider: str,
    operation: str,
    request: dict[str, Any],
    fn: Callable[[], T],
    now: datetime,
    application_id: uuid.UUID | None = None,
    attempt: int = 1,
) -> T:
    started = time.perf_counter()
    status, response = "ERROR", None
    try:
        result = fn()
        status = getattr(result, "call_status", "SUCCESS")
        response = result.to_dict() if hasattr(result, "to_dict") else None
        return result
    except ProviderTimeout:
        status, response = "TIMEOUT", {"error": "timeout"}
        raise
    except ProviderError as exc:
        status, response = "ERROR", {"error": str(exc)}
        raise
    finally:
        db.add(
            IntegrationCall(
                application_id=application_id,
                provider=provider,
                operation=operation,
                request=mask_payload(request),
                response=mask_payload(response) if response is not None else None,
                status=status,
                latency_ms=round((time.perf_counter() - started) * 1000),
                attempt=attempt,
                created_at=now,
            )
        )


def call_with_retries(
    db: Session,
    *,
    backoff_ms: int,
    attempts: int = DEFAULT_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
    **call_kwargs: Any,
) -> Any:
    """Retry `logged_call` on ProviderTimeout with exponential backoff; re-raise after the last attempt."""
    for attempt in range(1, attempts + 1):
        try:
            return logged_call(db, attempt=attempt, **call_kwargs)
        except ProviderTimeout:
            if attempt == attempts:
                raise
            delay_ms = backoff_ms * 2 ** (attempt - 1)
            if delay_ms:
                sleep(delay_ms / 1000)
    raise AssertionError("unreachable")
