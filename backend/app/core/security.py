"""JWT issuing/decoding and role-based access dependencies.

Roles: applicant (from OTP), ops and admin (from environment-configured login).
"""

import hmac
import uuid
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

import jwt
from fastapi import Depends, Request

from app.core.clock import Clock, get_clock
from app.core.config import Settings
from app.core.errors import AppError

ALGORITHM = "HS256"


class Role(StrEnum):
    APPLICANT = "applicant"
    OPS = "ops"
    ADMIN = "admin"


@dataclass(frozen=True)
class Principal:
    subject: str
    role: Role

    @property
    def applicant_id(self) -> uuid.UUID:
        if self.role != Role.APPLICANT:
            raise AppError(403, "FORBIDDEN", "This action is only available to applicants.")
        return uuid.UUID(self.subject)

    @property
    def actor(self) -> str:
        """How this principal is recorded in event logs."""
        return "applicant" if self.role == Role.APPLICANT else f"{self.role.value}:{self.subject}"


def create_token(settings: Settings, clock: Clock, subject: str, role: Role) -> str:
    now = clock.now()
    payload = {
        "sub": subject,
        "role": role.value,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(settings: Settings, clock: Clock, token: str) -> Principal:
    try:
        # Expiry is checked against the injectable clock, not the wall clock.
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[ALGORITHM], options={"verify_exp": False}
        )
        role = Role(payload["role"])
        subject = str(payload["sub"])
        exp = int(payload["exp"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise AppError(401, "UNAUTHENTICATED", "Your session is invalid. Please sign in again.") from None
    if clock.now().timestamp() >= exp:
        raise AppError(401, "UNAUTHENTICATED", "Your session has expired. Please sign in again.")
    return Principal(subject=subject, role=role)


def check_internal_credentials(settings: Settings, username: str, password: str) -> Role | None:
    def same(a: str, b: str) -> bool:
        return hmac.compare_digest(a.encode(), b.encode())

    if same(username, settings.admin_username) and same(password, settings.admin_password):
        return Role.ADMIN
    if (
        settings.ops_username
        and settings.ops_password
        and same(username, settings.ops_username)
        and same(password, settings.ops_password)
    ):
        return Role.OPS
    return None


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_optional_principal(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    clock: Clock = Depends(get_clock),
) -> Principal | None:
    header = request.headers.get("Authorization", "")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AppError(401, "UNAUTHENTICATED", "Use an 'Authorization: Bearer <token>' header.")
    return decode_token(settings, clock, token)


def get_principal(principal: Principal | None = Depends(get_optional_principal)) -> Principal:
    if principal is None:
        raise AppError(401, "UNAUTHENTICATED", "Please sign in to continue.")
    return principal


def require_roles(*roles: Role):
    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in roles:
            raise AppError(403, "FORBIDDEN", "You don't have access to this action.")
        return principal

    return dependency


require_applicant = require_roles(Role.APPLICANT)
require_admin = require_roles(Role.ADMIN)
require_ops_or_admin = require_roles(Role.OPS, Role.ADMIN)
