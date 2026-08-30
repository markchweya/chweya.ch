"""Server-side session handling.

Sessions live in the database so revocation takes effect immediately. A signed
stateless token cannot be revoked before it expires, and section 13 requires
revocation.

The cookie carries a random token; the database stores only its SHA-256. A
database disclosure therefore yields no usable session.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import User, UserSession
from app.security.hashing import (
    hash_client_address,
    hash_session_token,
    hash_user_agent,
    new_session_token,
)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def create_session(
    db: Session,
    user: User,
    *,
    client_host: str | None = None,
    user_agent: str | None = None,
    settings: Settings | None = None,
) -> tuple[UserSession, str]:
    """Create a session and return it with the token to send to the client.

    The token is returned once and never stored. Losing it means the session
    cannot be used, which is the intended property.
    """
    settings = settings or get_settings()
    token = new_session_token()
    now = _now()

    session_row = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        idle_expires_at=now + dt.timedelta(minutes=settings.session_idle_timeout_minutes),
        absolute_expires_at=now + dt.timedelta(hours=settings.session_absolute_timeout_hours),
        client_address_hash=hash_client_address(client_host),
        user_agent_hash=hash_user_agent(user_agent),
    )
    db.add(session_row)
    db.flush()
    return session_row, token


def load_session(db: Session, token: str | None) -> UserSession | None:
    """Return the live session for a token, or None.

    Refreshes the idle expiry on a successful load, so an active person is not
    logged out mid-task, while the absolute expiry still applies.
    """
    if not token:
        return None

    row = db.execute(
        select(UserSession).where(UserSession.token_hash == hash_session_token(token))
    ).scalar_one_or_none()
    if row is None:
        return None

    now = _now()
    if not row.is_usable(now):
        return None

    settings = get_settings()
    row.last_seen_at = now
    row.idle_expires_at = now + dt.timedelta(minutes=settings.session_idle_timeout_minutes)
    return row


def revoke_session(db: Session, session_id: uuid.UUID, *, reason: str = "logout") -> None:
    """Revoke one session."""
    db.execute(
        update(UserSession)
        .where(UserSession.id == session_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_now(), revoked_reason=reason[:64])
    )


def revoke_all_for_user(db: Session, user_id: uuid.UUID, *, reason: str) -> int:
    """Revoke every live session for a user.

    Used on password change and on deactivation. A password change that leaves
    old sessions alive does not actually lock anyone out.
    """
    result = db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_now(), revoked_reason=reason[:64])
    )
    return result.rowcount or 0


def purge_expired(db: Session) -> int:
    """Delete sessions that can no longer authenticate anything."""
    from sqlalchemy import delete

    result = db.execute(
        delete(UserSession).where(UserSession.absolute_expires_at < _now())
    )
    return result.rowcount or 0
