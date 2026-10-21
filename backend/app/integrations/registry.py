"""Builds the provider set used by a request. Swap mocks for real adapters here."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.config import Settings
from app.core.db import get_db
from app.integrations.base import AaProvider, BureauProvider, KycProvider, PanProvider
from app.integrations.mock.providers import (
    MockAaProvider,
    MockBureauProvider,
    MockKycProvider,
    MockPanProvider,
)
from app.models import MockProfile


@dataclass
class Providers:
    pan: PanProvider
    kyc: KycProvider
    bureau: BureauProvider
    aa: AaProvider


class MockProfileStore:
    def __init__(self, db: Session):
        self._db = db

    def get(self, pan: str) -> dict[str, Any] | None:
        row = self._db.get(MockProfile, pan)
        return row.profile if row else None

    def upsert(self, pan: str, profile: dict[str, Any], actor: str, now: datetime) -> MockProfile:
        row = self._db.get(MockProfile, pan)
        if row is None:
            row = MockProfile(pan=pan, profile=profile, created_by=actor, created_at=now, updated_at=now)
            self._db.add(row)
        else:
            row.profile = profile
            row.updated_at = now
        return row


def build_mock_providers(settings: Settings, clock: Clock, db: Session) -> Providers:
    fixtures = MockProfileStore(db).get
    latency = settings.mock_latency_ms
    return Providers(
        pan=MockPanProvider(latency, fixtures),
        kyc=MockKycProvider(latency, fixtures),
        bureau=MockBureauProvider(latency, fixtures),
        aa=MockAaProvider(latency, fixtures, clock),
    )


def get_providers(request: Request, db: Session = Depends(get_db)) -> Providers:
    return build_mock_providers(request.app.state.settings, request.app.state.clock, db)
