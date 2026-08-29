"""Append-only audit log with a tamper-evident hash chain.

Section 13 of the brief requires audit logs that are "append-oriented and
resistant to casual modification". A database table is not append-only by
itself: anyone with an UPDATE grant, including someone using the local Adminer
instance, can rewrite a row.

Two mechanisms are combined:

1. Each entry stores the hash of the previous entry along with a hash of its
   own content. Editing or deleting any row breaks the chain from that point
   on, and :func:`app.security.audit.verify_chain` finds where. This makes
   tampering detectable rather than preventing it.
2. The migration revokes UPDATE and DELETE on this table from the application
   role, so the running application physically cannot rewrite history even if
   an endpoint is compromised.

Neither is a substitute for shipping entries off-host, which the operations
runbook covers.

What must never be written here: passwords, password hashes, full session
tokens, API keys, raw Authorization headers, and any personal data beyond what
an investigation genuinely requires. :func:`app.security.audit.record` filters
known-sensitive keys, but the caller is responsible for what it passes.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditAction(StrEnum):
    """Auditable actions.

    A closed set, so that querying the log does not depend on remembering how
    a particular call site spelled its action string.
    """

    # Authentication
    LOGIN_SUCCEEDED = "login.succeeded"
    LOGIN_FAILED = "login.failed"
    LOGIN_LOCKED_OUT = "login.locked_out"
    LOGOUT = "logout"
    PASSWORD_CHANGED = "password.changed"
    PASSWORD_RESET_BY_ADMIN = "password.reset_by_admin"
    SESSION_REVOKED = "session.revoked"

    # Users and roles
    USER_CREATED = "user.created"
    USER_DEACTIVATED = "user.deactivated"
    USER_REACTIVATED = "user.reactivated"
    ROLE_GRANTED = "role.granted"
    ROLE_REVOKED = "role.revoked"
    ADMIN_BOOTSTRAPPED = "admin.bootstrapped"

    # Sources and ingestion
    SOURCE_CREATED = "source.created"
    SOURCE_UPDATED = "source.updated"
    SOURCE_PAUSED = "source.paused"
    SOURCE_RESUMED = "source.resumed"
    SOURCE_REMOVED = "source.removed"
    CRAWL_STARTED = "crawl.started"
    CRAWL_FINISHED = "crawl.finished"
    CRAWL_CANCELLED = "crawl.cancelled"
    CRAWL_BLOCKED = "crawl.blocked"

    # Documents
    DOCUMENT_UPLOADED = "document.uploaded"
    DOCUMENT_APPROVED = "document.approved"
    DOCUMENT_REJECTED = "document.rejected"
    DOCUMENT_REPLACED = "document.replaced"
    DOCUMENT_WITHDRAWN = "document.withdrawn"
    DOCUMENT_DELETED = "document.deleted"
    DOCUMENT_DOWNLOADED = "document.downloaded"
    DOCUMENT_QUARANTINED = "document.quarantined"

    # Review
    CONTRADICTION_RESOLVED = "contradiction.resolved"
    CONTENT_EXCLUDED = "content.excluded"
    CONTENT_RESTORED = "content.restored"

    # Index lifecycle
    INDEX_BUILD_STARTED = "index.build_started"
    INDEX_PROMOTED = "index.promoted"
    INDEX_ROLLED_BACK = "index.rolled_back"

    # System
    CONFIGURATION_CHANGED = "configuration.changed"
    DATA_EXPORTED = "data.exported"
    DATA_DELETED = "data.deleted"
    SECURITY_ALERT = "security.alert"


class AuditOutcome(StrEnum):
    """Whether the audited action succeeded."""

    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


# The genesis value for the first row's ``previous_hash``. A fixed constant so
# that chain verification has a defined starting point.
GENESIS_HASH = "0" * 64


class AuditEvent(Base):
    """One recorded action.

    Rows are never updated. The application role holds no UPDATE or DELETE
    grant on this table; see the hardening step in the initial migration.
    """

    __tablename__ = "audit_events"

    # Sequential rather than a UUID, because the hash chain depends on a total
    # order and a monotonic key makes the chain cheap to walk.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    # Null for actions taken by the system itself, such as a scheduled crawl.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # A stable label for the actor, retained even if the user row is later
    # removed. Holds an opaque identifier or a system component name, never an
    # email address, so that pruning a user does not leave personal data here.
    actor_label: Mapped[str] = mapped_column(String(120), nullable=False, default="system")

    action: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)

    # What was acted on, for example "document" and its identifier.
    object_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Correlates an event with the request that caused it, so an investigation
    # can join audit entries to application logs without storing the request
    # body anywhere.
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Hashed under the data minimisation rule in section 14.
    client_address_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Additional structured context. Filtered for sensitive keys before it is
    # written; see app.security.audit.record.
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    # Tamper-evidence. ``entry_hash`` covers this row's content and the
    # previous row's hash, so any edit breaks verification from that row on.
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("ix_audit_events_occurred_at", "occurred_at"),
        Index("ix_audit_events_action", "action"),
        Index("ix_audit_events_actor_user_id", "actor_user_id"),
        Index("ix_audit_events_object_type_object_id", "object_type", "object_id"),
    )

    def __repr__(self) -> str:
        return f"<AuditEvent {self.id} {self.action} {self.outcome}>"
