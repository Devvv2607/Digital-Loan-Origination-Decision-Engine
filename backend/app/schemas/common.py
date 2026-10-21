from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """The single error shape used by every endpoint."""

    error_code: str = Field(examples=["OTP_LOCKED"])
    message: str = Field(examples=["Too many wrong attempts. Try again after 14:35 UTC."])
    details: dict[str, Any] = Field(default_factory=dict)


def error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses=` helper so Swagger documents the error shape."""
    return {code: {"model": ErrorResponse} for code in codes}
