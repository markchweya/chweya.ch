"""Initial identity schema: roles, users, sessions and the audit log.

Revision ID: 0001_identity
Revises:
Created: 2026-08-29

Creates the tables that authentication, authorisation and auditing need, seeds
the fixed role set, and applies the database-level protection that makes the
audit log append-only for the application role.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_identity"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Role rows are seeded here rather than by application code, so a fresh
# database is usable immediately and every environment has identical role
# identifiers. Descriptions are duplicated from app.db.models.user on purpose:
# a migration must not import application code, because the code will change
# and an old migration has to keep producing the schema it originally did.
SEED_ROLES: list[tuple[str, str]] = [
    (
        "super_admin",
        "Full administrative access, including user and role management and "
        "system configuration.",
    ),
    (
        "content_admin",
        "Manages sources, crawl scheduling and document uploads. Approves "
        "content into the public index.",
    ),
    (
        "reviewer",
        "Resolves contradiction findings and reviews flagged answers. Cannot "
        "change system configuration or manage users.",
    ),
    (
        "support_operator",
        "Reads anonymised chat feedback and retrieval diagnostics in order to "
        "investigate reported problems. No content or configuration rights.",
    ),
    (
        "auditor",
        "Read-only access to audit events and system state. Holds no rights "
        "to change anything, by design.",
    ),
]


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("password_algorithm", sa.String(length=32), nullable=False, server_default="argon2id"),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    # Case-insensitive uniqueness. Without it, "Anna@zug.ch" and "anna@zug.ch"
    # are two accounts for one person, which breaks both lockout counting and
    # the audit trail.
    op.create_index("ix_users_email_lower", "users", [sa.text("lower(email)")], unique=True)
    op.create_index("ix_users_is_active", "users", ["is_active"])

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("granted_by_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_roles_user_id_users", ondelete="CASCADE"
        ),
        # RESTRICT: a role that is still granted to someone must not vanish.
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name="fk_user_roles_role_id_roles", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_id"],
            ["users.id"],
            name="fk_user_roles_granted_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_roles"),
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=64), nullable=True),
        sa.Column("client_address_hash", sa.String(length=64), nullable=True),
        sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_sessions_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_absolute_expires_at", "user_sessions", ["absolute_expires_at"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_label", sa.String(length=120), nullable=False, server_default="system"),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=True),
        sa.Column("object_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("client_address_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "detail",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.Column("entry_hash", sa.String(length=64), nullable=False),
        # SET NULL rather than CASCADE: deleting a user must never delete the
        # record of what that user did. actor_label preserves the reference.
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_audit_events_actor_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index(
        "ix_audit_events_object_type_object_id", "audit_events", ["object_type", "object_id"]
    )

    for name, description in SEED_ROLES:
        op.execute(
            sa.text("INSERT INTO roles (name, description) VALUES (:name, :description)").bindparams(
                name=name, description=description
            )
        )

    _apply_audit_log_hardening()


def _apply_audit_log_hardening() -> None:
    """Make audit_events append-only for the application role.

    The hash chain makes tampering detectable. This makes it difficult, by
    removing the privilege entirely.

    It only takes effect when the application connects as a role that does not
    own the tables, because an owner keeps its privileges regardless of any
    REVOKE. Set DATABASE_APP_ROLE to that role and run migrations as the owner.
    When it is unset, the schema is created without this protection and the
    hash chain is the only defence. That configuration is acceptable for local
    development and is refused in production by the deployment checklist.
    """
    app_role = os.environ.get("DATABASE_APP_ROLE", "").strip()
    if not app_role:
        op.execute(
            sa.text(
                "DO $$ BEGIN RAISE NOTICE "
                "'DATABASE_APP_ROLE unset: audit_events left writable by the owner. "
                "Acceptable in development only.'; END $$;"
            )
        )
        return

    # Quote the identifier so a role name never becomes an injection point,
    # even though it comes from the operator's own environment.
    quoted = f'"{app_role}"'
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {quoted}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {quoted}")
    # The application may append and read. It may not rewrite or erase.
    op.execute(f"REVOKE UPDATE, DELETE ON audit_events FROM {quoted}")


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("user_sessions")
    op.drop_table("user_roles")
    op.drop_index("ix_users_is_active", table_name="users")
    op.drop_index("ix_users_email_lower", table_name="users")
    op.drop_table("users")
    op.drop_table("roles")
