# Lendwise (Demo) — Backend

> Demo prototype. Simulated integrations and synthetic data. Not affiliated with any bank or lender.

FastAPI + SQLAlchemy 2.0 + Alembic + PostgreSQL. Python 3.11.

## Run locally

From the repository root:

```bash
docker compose up -d --wait db            # Postgres on localhost:55432 (dev + test databases)
cd backend
py -3.11 -m venv .venv                    # or python3.11 -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # .venv/bin/pip on macOS/Linux
cp .env.example .env                      # then replace the change-me values
.venv/Scripts/alembic upgrade head
.venv/Scripts/uvicorn app.main:create_app --factory --reload
```

- Swagger: http://localhost:8000/docs
- Health: http://localhost:8000/health

The app refuses to start if required environment variables are missing or invalid, and lists which ones.

## Tests

```bash
.venv/Scripts/python -m pytest --cov
```

Tests rebuild the `lendwise_test` database from the Alembic migrations once per run, then run each test inside a rolled-back transaction. Time is controlled with a `FrozenClock`, so lockouts and 30-day expiry are tested without waiting.

## Layout

| Path | Contents |
|---|---|
| `app/core/` | Settings, DB session, injectable clock, error shape, masking, JWT roles, rate limits |
| `app/models/` | SQLAlchemy models (all PRD tables + idempotency keys) |
| `app/state_machine/` | 8 states, allowed transitions, event log, event-log checker |
| `app/integrations/` | Provider interfaces, deterministic mocks, logged calls with retries |
| `app/engine/` | Versioned policy, 6 rules, 4 fraud checks, decision engine, pricing (EMI/APR) |
| `app/services/` | OTP, applications, PAN / e-KYC / AA verification, assessment, offers, expiry, idempotency |
| `policy/` | `policy_template.json` (defaults) and `seed_policy.json` (written by `scripts/seed_policy_from_cutoff.py`) |
| `app/api/` | Routers: health, auth, applications, verification, admin, `/mock/*` |
| `alembic/` | Migrations |
| `tests/` | pytest suite |
