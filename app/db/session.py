"""Database engine and session handling.

The application is synchronous where it touches the database. FastAPI runs
plain ``def`` endpoints in a worker thread, so a synchronous session is safe
there, and the background workers are synchronous anyway. Keeping one style
avoids a second driver and a second set of session semantics for no benefit.

The only asynchronous work in the request path is the call to Apertus, which
is streamed with httpx and does not touch the database while streaming.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Return the process-wide engine, creating it on first use."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            str(settings.database_url),
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            # Recycle below the usual one-hour idle timeouts of proxies and
            # managed networks, so a pooled connection is never handed out
            # after the other end has already closed it.
            pool_recycle=1800,
            pool_pre_ping=True,
            future=True,
        )

        @event.listens_for(_engine, "connect")
        def _set_statement_timeout(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
            """Bound every statement on every new connection.

            Retrieval queries run against attacker-influenced input. A
            statement timeout means a pathological query fails rather than
            holding a pooled connection open indefinitely.
            """
            with dbapi_connection.cursor() as cursor:
                cursor.execute(f"SET statement_timeout = {settings.database_statement_timeout_ms}")

    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session that commits or rolls back.

    Used by workers and CLI commands. Request handlers use
    :func:`db_session` instead, so that FastAPI manages the lifetime.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def db_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session for the life of one request.

    The session is rolled back rather than committed on the way out. Handlers
    commit explicitly, so a handler that raises after a partial write cannot
    accidentally persist half of it.
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def reset_engine() -> None:
    """Dispose of the engine and factory. Used by tests between databases."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
