"""Application settings, loaded from environment variables (and backend/.env locally).

Required variables are validated at startup so a misconfigured deploy fails fast
with a readable message instead of failing on the first request.
"""

from datetime import datetime
from functools import lru_cache
from typing import Literal

from pydantic import Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EXAMPLE_MARKER = "change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["development", "test", "production"] = "development"

    database_url: str = Field(min_length=1)

    jwt_secret: str = Field(min_length=32)
    jwt_ttl_minutes: int = Field(default=60, ge=1, le=24 * 60)
    pii_hash_key: str = Field(min_length=16)

    admin_username: str = Field(min_length=1)
    admin_password: str = Field(min_length=8)
    ops_username: str | None = None
    ops_password: str | None = None

    demo_mode: bool = True
    demo_read_only: bool = True
    mock_latency_ms: int = Field(default=300, ge=0, le=10_000)
    # Backoff before retry n is base * 2^(n-1): 500 ms, then 1 s (EC-05, EC-07).
    provider_retry_backoff_ms: int = Field(default=500, ge=0, le=10_000)
    rate_limit_profile: Literal["default", "simulation", "off"] = "default"
    auto_seed_policy: bool = True  # seed policy/seed_policy.json on startup if no policy exists
    # Optional fixed start for the business clock (ISO 8601 with offset). Used for the
    # simulation and e2e runs so age-dependent cases never expire. Not allowed in production.
    clock_start: datetime | None = None

    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _check_consistency(self) -> "Settings":
        if (self.ops_username is None) != (self.ops_password is None):
            raise ValueError("OPS_USERNAME and OPS_PASSWORD must be set together")
        if self.ops_password is not None and len(self.ops_password) < 8:
            raise ValueError("OPS_PASSWORD must be at least 8 characters")
        if self.clock_start is not None and self.clock_start.tzinfo is None:
            raise ValueError("CLOCK_START needs a timezone offset, e.g. 2026-10-22T09:00:00+05:30")
        if self.env == "production" and self.clock_start is not None:
            raise ValueError("CLOCK_START must not be set in production")
        if self.env == "production":
            for name in ("jwt_secret", "pii_hash_key", "admin_password", "ops_password"):
                value = getattr(self, name)
                if value and EXAMPLE_MARKER in value:
                    raise ValueError(f"{name.upper()} still has the example value from .env.example")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


class ConfigurationError(RuntimeError):
    """Raised at startup when required environment variables are missing or invalid."""


def load_settings(**overrides) -> Settings:
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            field = ".".join(str(p) for p in err["loc"]).upper() or "SETTINGS"
            problems.append(f"  - {field}: {err['msg']}")
        raise ConfigurationError(
            "Invalid configuration. Check backend/.env (see .env.example):\n" + "\n".join(problems)
        ) from None


@lru_cache
def get_settings() -> Settings:
    return load_settings()
