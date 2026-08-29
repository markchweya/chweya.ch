"""System state and configuration that is safe to hold in the database.

Only non-secret operational values belong here. Credentials, signing keys and
API tokens stay in the environment or a secret manager, because anything in
this table is visible to anyone with database access, including whoever is
using the local Adminer instance.

The table also carries bootstrap markers. The administrator bootstrap uses one
to satisfy the requirement that a deleted administrator is not silently
recreated on the next run.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SettingKey:
    """Well-known setting keys, so call sites do not depend on loose strings."""

    ADMIN_BOOTSTRAPPED_AT = "admin.bootstrapped_at"
    ACTIVE_INDEX_VERSION = "index.active_version"
    LAST_SYNC_COMPLETED_AT = "sync.last_completed_at"
    PUBLIC_NOTICE_VERSION = "notice.version"


class SystemSetting(Base, TimestampMixin):
    """One configuration or state value.

    Values are stored as text and parsed by the caller. A JSON column would
    invite storing structures that belong in their own tables.
    """

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    # Free-text note explaining why the value is what it is, so an operator
    # reading the table later is not left guessing.
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<SystemSetting {self.key}>"


def get_setting(session, key: str) -> str | None:  # type: ignore[no-untyped-def]
    """Return a setting value, or None when it has never been set."""
    row = session.get(SystemSetting, key)
    return row.value if row is not None else None


def set_setting(
    session,  # type: ignore[no-untyped-def]
    key: str,
    value: str,
    *,
    note: str = "",
    updated_by_id: uuid.UUID | None = None,
) -> SystemSetting:
    """Insert or update a setting. Does not commit."""
    row = session.get(SystemSetting, key)
    if row is None:
        row = SystemSetting(key=key, value=value, note=note, updated_by_id=updated_by_id)
        session.add(row)
    else:
        row.value = value
        if note:
            row.note = note
        row.updated_by_id = updated_by_id
    return row


def utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string, for setting values."""
    return dt.datetime.now(dt.UTC).isoformat()
