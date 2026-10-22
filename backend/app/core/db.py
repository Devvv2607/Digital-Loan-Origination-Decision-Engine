"""Database engine and session handling (SQLAlchemy 2.0, synchronous)."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def normalise_database_url(url: str) -> str:
    """Use the psycopg 3 driver for plain postgres:// or postgresql:// URLs (as hosted providers give them)."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(database_url: str) -> Engine:
    # pool_pre_ping: hosted Postgres (e.g. Neon) closes idle connections when it scales to zero.
    return create_engine(normalise_database_url(database_url), pool_pre_ping=True, future=True)


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    session = request.app.state.sessionmaker()
    try:
        yield session
    finally:
        session.close()
