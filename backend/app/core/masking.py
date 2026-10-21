"""Masking and hashing of personal identifiers (PAN, phone).

Raw PANs and phone numbers must never reach logs, `integration_calls` or event metadata.
"""

import hashlib
import hmac
import re
from typing import Any

PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[- ]?)?[6-9]\d{9}(?!\d)")


def mask_pan(pan: str | None) -> str | None:
    if not pan:
        return pan
    if len(pan) != 10:
        return "**********"
    return f"{pan[:5]}****{pan[-1]}"


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return phone
    digits = re.sub(r"\D", "", phone)
    return "******" + digits[-4:] if len(digits) >= 4 else "******"


def mask_text(text: str) -> str:
    """Mask anything that looks like a PAN or an Indian mobile number inside free text."""
    text = PAN_RE.sub(lambda m: mask_pan(m.group(0)) or "", text)
    return PHONE_RE.sub(lambda m: mask_phone(m.group(0)) or "", text)


def mask_value(value: Any) -> Any:
    """Recursively mask strings inside JSON-like structures."""
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {k: mask_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [mask_value(v) for v in value]
    return value


def hash_pii(value: str, key: str) -> str:
    """Keyed hash used to look up identifiers without storing them in clear."""
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()
