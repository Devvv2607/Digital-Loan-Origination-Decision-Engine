"""Demo helpers for the landing page: one-click personas (only when DEMO_MODE is on)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.clock import Clock, get_clock
from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import AppError
from app.core.rate_limit import rate_limit
from app.core.security import get_settings_dep
from app.integrations.mock.personas import PERSONAS, start_persona
from app.schemas.common import error_responses

router = APIRouter(prefix="/demo", tags=["Demo (simulated)"])


def _require_demo(settings: Settings) -> None:
    if not settings.demo_mode:
        raise AppError(404, "NOT_FOUND", "Demo personas are disabled.")


@router.get("/personas", summary="List one-click demo personas")
def list_personas(settings: Settings = Depends(get_settings_dep)) -> dict:
    _require_demo(settings)
    return {
        "items": [
            {"persona_id": pid, "label": p["label"], "applicant_name": p["details"]["full_name"],
             "description": p["description"], "expected_outcome": p["expected_outcome"]}
            for pid, p in PERSONAS.items()
        ]
    }


@router.post("/personas/{persona_id}", dependencies=[Depends(rate_limit("demo"))],
             responses=error_responses(404, 429),
             summary="Prepare a persona: registers a synthetic identity and returns prefilled details")
def start(
    persona_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    clock: Clock = Depends(get_clock),
) -> dict:
    _require_demo(settings)
    result = start_persona(db, settings, persona_id, clock.now())
    if result is None:
        raise AppError(404, "NOT_FOUND", f"Unknown persona '{persona_id}'.")
    return result
