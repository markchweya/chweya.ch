"""Users, roles and authenticated sessions.

Design notes that matter for review:

* A user holds a set of roles rather than a single role. A person is often
  both a content administrator and a reviewer, and modelling that as one
  column forces either a fake combined role or a second account.
* Password hashes are never exposed through the API or the administration
  interface. Section 16 of the brief prohibits it, and the ORM attribute is
  named so that an accidental ``model_dump()`` is easy to spot in review.
* Session rows store a hash of the session token, never the token. A database
  leak must not hand the attacker usable sessions.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk


class RoleName(StrEnum):
    """The fixed set of roles from section 13 of the brief.

    Roles are a closed set rather than free text. An operator inventing a role
    name would silently receive no permissions, because authorisation checks
    match on these members.
    """

    SUPER_ADMIN = "super_admin"
    CONTENT_ADMIN = "content_admin"
    REVIEWER = "reviewer"
    SUPPORT_OPERATOR = "support_operator"
    AUDITOR = "auditor"


ROLE_DESCRIPTIONS: dict[RoleName, str] = {
    RoleName.SUPER_ADMIN: (
        "Full administrative access, including user and role management and "
        "system configuration."
    ),
    RoleName.CONTENT_ADMIN: (
        "Manages sources, crawl scheduling and document uploads. Approves "
        "content into the public index."
    ),
    RoleName.REVIEWER: (
        "Resolves contradiction findings and reviews flagged answers. Cannot "
        "change system configuration or manage users."
    ),
    RoleName.SUPPORT_OPERATOR: (
        "Reads anonymised chat feedback and retrieval diagnostics in order to "
        "investigate reported problems. No content or configuration rights."
    ),
    RoleName.AUDITOR: (
        "Read-only access to audit events and system state. Holds no rights "
        "to change anything, by design."
    ),
}


class Role(Base, TimestampMixin):
    """A named role. Rows are seeded by migration from :class:`RoleName`."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    users: Mapped[list[UserRole]] = relationship(back_populates="role")

    def __repr__(self) -> str:
        return f"<Role {self.name}>"


class User(Base, TimestampMixin):
    """An administrative user.

    The public chatbot requires no account, so every row here is a member of
    canton or operator staff.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()

    # Stored lower-case. Compared case-insensitively so that one person cannot
    # hold two accounts differing only in capitalisation.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    # Argon2id encoded hash, including its parameters and salt. Never returned
    # by any endpoint or shown in the administration interface.
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # Recorded so that a future algorithm change can rehash on next login
    # without guessing what produced an existing hash.
    password_algorithm: Mapped[str] = mapped_column(String(32), nullable=False, default="argon2id")
    password_changed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Set on the bootstrap administrator and on any administrative reset. While
    # true, every route except the password-change route is refused.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Login throttling. Counted in the database rather than in Redis so that a
    # cache flush cannot reset an attacker's budget.
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    locked_until: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Deactivated accounts are retained rather than deleted, because audit
    # events reference them. See docs/privacy.md for the retention rule.
    deactivated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    roles: Mapped[list[UserRole]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_users_email_lower", "email", unique=True),
        Index("ix_users_is_active", "is_active"),
    )

    def role_names(self) -> set[str]:
        """Return the role names granted to this user."""
        return {assignment.role.name for assignment in self.roles}

    def has_role(self, role: RoleName) -> bool:
        """Return True if the user holds ``role``."""
        return role.value in self.role_names()

    def __repr__(self) -> str:
        # Deliberately does not include the email address, so that a repr in a
        # log or a traceback does not become a personal data disclosure.
        return f"<User {self.id}>"


class UserRole(Base):
    """Grant of one role to one user, with provenance.

    ``granted_by_id`` is kept so the audit trail can answer who gave an
    account its privileges, which the audit event alone cannot if events are
    later pruned by retention policy.
    """

    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True
    )
    granted_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    granted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="roles", foreign_keys=[user_id])
    role: Mapped[Role] = relationship(back_populates="users")

    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_id_role_id"),)


class UserSession(Base):
    """A server-side authenticated session.

    Sessions are held in the database rather than only in a signed cookie so
    that revocation is immediate. Section 13 requires session revocation, and a
    stateless token cannot be revoked before it expires.
    """

    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # SHA-256 of the session token. The token itself exists only in the
    # client's cookie, so a database disclosure yields no usable session.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    last_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    # Two independent expiries: idle timeout, refreshed on use, and an absolute
    # cap that no amount of activity extends.
    idle_expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Hashed, not stored raw, under the data minimisation rule in section 14.
    client_address_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")

    __table_args__ = (
        Index("ix_user_sessions_user_id", "user_id"),
        # Supports the sweep that deletes expired sessions.
        Index("ix_user_sessions_absolute_expires_at", "absolute_expires_at"),
    )

    def is_usable(self, now: dt.datetime) -> bool:
        """Return True if this session may still authenticate a request."""
        if self.revoked_at is not None:
            return False
        return now < self.idle_expires_at and now < self.absolute_expires_at
