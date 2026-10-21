"""Phone OTP: issue, verify, lockout (EC-01) and expiry/resend cap (EC-02).

No SMS is ever sent. In demo mode the code is returned to the caller to show on screen.
"""

import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import product
from app.core.config import Settings
from app.core.errors import AppError
from app.core.masking import hash_pii, mask_phone
from app.models import Applicant, OtpAttempt

logger = logging.getLogger(__name__)


@dataclass
class IssuedOtp:
    otp: OtpAttempt
    code: str
    sends_remaining: int


def _code_hash(settings: Settings, phone_hash: str, code: str) -> str:
    return hash_pii(f"{phone_hash}:{code}", settings.pii_hash_key)


def _active_lock(db: Session, phone_hash: str, now: datetime) -> datetime | None:
    return db.scalar(
        select(func.max(OtpAttempt.locked_until)).where(
            OtpAttempt.phone_hash == phone_hash, OtpAttempt.locked_until > now
        )
    )


def _locked_error(locked_until: datetime) -> AppError:
    return AppError(
        423,
        "OTP_LOCKED",
        f"Too many wrong attempts. Try again after {locked_until.strftime('%H:%M')} UTC.",
        {"locked_until": locked_until.isoformat()},
    )


def send_otp(db: Session, settings: Settings, phone: str, now: datetime) -> IssuedOtp:
    phone_hash = hash_pii(phone, settings.pii_hash_key)

    if locked_until := _active_lock(db, phone_hash, now):
        raise _locked_error(locked_until)

    window_start = now - product.OTP_SEND_WINDOW
    sends = db.scalar(
        select(func.count()).where(
            OtpAttempt.phone_hash == phone_hash, OtpAttempt.created_at > window_start
        )
    )
    if sends >= product.OTP_MAX_SENDS_PER_WINDOW:
        oldest = db.scalar(
            select(func.min(OtpAttempt.created_at)).where(
                OtpAttempt.phone_hash == phone_hash, OtpAttempt.created_at > window_start
            )
        )
        retry_at = oldest + product.OTP_SEND_WINDOW
        raise AppError(
            429,
            "OTP_RESEND_LIMIT",
            "You've requested too many codes. Please try again later.",
            {"retry_after": retry_at.isoformat(), "max_sends_per_hour": product.OTP_MAX_SENDS_PER_WINDOW},
        )

    code = f"{secrets.randbelow(10**product.OTP_LENGTH):0{product.OTP_LENGTH}d}"
    otp = OtpAttempt(
        phone_hash=phone_hash,
        code_hash=_code_hash(settings, phone_hash, code),
        created_at=now,
        expires_at=now + product.OTP_TTL,
        failed_attempts=0,
    )
    db.add(otp)
    db.commit()
    logger.info("OTP issued for %s", mask_phone(phone))
    return IssuedOtp(otp=otp, code=code, sends_remaining=product.OTP_MAX_SENDS_PER_WINDOW - sends - 1)


def verify_otp(db: Session, settings: Settings, phone: str, code: str, now: datetime) -> Applicant:
    phone_hash = hash_pii(phone, settings.pii_hash_key)

    if locked_until := _active_lock(db, phone_hash, now):
        raise _locked_error(locked_until)

    otp = db.scalar(
        select(OtpAttempt)
        .where(OtpAttempt.phone_hash == phone_hash, OtpAttempt.verified_at.is_(None))
        .order_by(OtpAttempt.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if otp is None or otp.locked_until is not None:
        raise AppError(400, "OTP_INVALID", "No active code for this number. Please request a new one.")

    if now >= otp.expires_at:
        logger.info("Expired OTP used for %s", mask_phone(phone))
        raise AppError(400, "OTP_EXPIRED", "This code has expired. Please request a new one.")

    if not hmac.compare_digest(otp.code_hash, _code_hash(settings, phone_hash, code)):
        otp.failed_attempts += 1
        remaining = product.OTP_MAX_WRONG_ATTEMPTS - otp.failed_attempts
        if remaining <= 0:
            otp.locked_until = now + product.OTP_LOCK_DURATION
            db.commit()
            logger.warning("OTP locked for %s after %d wrong attempts", mask_phone(phone), otp.failed_attempts)
            raise _locked_error(otp.locked_until)
        db.commit()
        raise AppError(
            400, "OTP_INVALID", "That code isn't right. Please try again.", {"attempts_remaining": remaining}
        )

    otp.verified_at = now
    applicant = db.scalar(select(Applicant).where(Applicant.phone_hash == phone_hash))
    if applicant is None:
        applicant = Applicant(phone_hash=phone_hash, phone_last4=phone[-4:], created_at=now)
        db.add(applicant)
    db.commit()
    logger.info("OTP verified for %s", mask_phone(phone))
    return applicant
