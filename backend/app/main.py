"""FastAPI application factory.

Run locally:  uvicorn app.main:create_app --factory --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import admin, applications, auth, health, mock, verification
from app.core.clock import Clock
from app.core.config import Settings, load_settings
from app.core.db import make_engine, make_sessionmaker
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.rate_limit import RateLimiter

DISCLAIMER = (
    "**Demo prototype. Simulated integrations and synthetic data. "
    "Not affiliated with any bank or lender.**\n\n"
    "Lendwise (Demo) is a fictional lender. All errors use one shape: "
    '`{"error_code", "message", "details"}`.'
)


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or load_settings()  # fails fast on missing/invalid env vars
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Lendwise (Demo) — Loan Origination API",
        description=DISCLAIMER,
        version=__version__,
    )
    engine = make_engine(settings.database_url)
    app.state.settings = settings
    app.state.clock = clock or Clock()
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.rate_limiter = RateLimiter()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Device-Id"],
        expose_headers=["Idempotent-Replay", "Retry-After"],
    )
    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(applications.router)
    app.include_router(verification.router)
    app.include_router(admin.router)
    app.include_router(mock.router)
    return app
