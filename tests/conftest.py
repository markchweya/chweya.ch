"""Shared test fixtures.

Tests run against a real PostgreSQL database rather than SQLite. The schema
uses PostgreSQL-specific types (JSONB, UUID with gen_random_uuid, a functional
unique index on lower(email)), and a SQLite substitute would test a different
schema from the one that ships.

Set TEST_DATABASE_URL to point at a scratch database. Tests that need it are
skipped when it is unset, so the pure-logic suite still runs anywhere.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Drop the cached settings around every test.

    get_settings is cached for the life of the process. Without this, a test
    that changes the environment would leak its configuration into the next
    one, and the production-refusal tests do exactly that.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def database_url() -> str:
    """Return the scratch database URL, or skip the test."""
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; database tests are skipped")
    return url


@pytest.fixture(scope="session")
def engine(database_url: str):  # type: ignore[no-untyped-def]
    """A session-scoped engine against the scratch database."""
    eng = create_engine(database_url, future=True)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine) -> Iterator[Session]:  # type: ignore[no-untyped-def]
    """A clean session with every table truncated.

    Truncating rather than recreating keeps the suite fast while guaranteeing
    that one test cannot see another's rows. Audit chain tests in particular
    depend on starting from an empty log.
    """
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = factory()
    session.execute(
        text(
            "TRUNCATE answer_feedback, audit_events, user_sessions, user_roles, users, "
            "system_settings RESTART IDENTITY CASCADE"
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
