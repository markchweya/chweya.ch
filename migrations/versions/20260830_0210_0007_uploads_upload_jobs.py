"""Administrator upload jobs.

One row per submitted file, kept whatever became of the file itself. A refused
upload keeps no bytes and a deleted one loses them, and in both cases the row
stays so the audit trail has something to point at.

Revision ID: 0007_uploads
Revises: 0006_defaults
Created: 2026-08-30 02:10:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_uploads"
down_revision: str | None = "0006_defaults"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "upload_jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("state", sa.String(length=32), server_default="received", nullable=False),
        sa.Column("uploaded_by_id", sa.UUID(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column(
            "declared_media_type", sa.String(length=128), server_default="", nullable=False
        ),
        sa.Column(
            "detected_media_type", sa.String(length=128), server_default="", nullable=False
        ),
        sa.Column("upload_kind", sa.String(length=16), server_default="", nullable=False),
        sa.Column("byte_size", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("content_hash", sa.String(length=64), server_default="", nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=True),
        sa.Column("is_quarantined", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("refusal_reason", sa.String(length=64), server_default="", nullable=False),
        sa.Column("scan_outcome", sa.String(length=16), server_default="", nullable=False),
        sa.Column("scan_detail", sa.Text(), server_default="", nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("version_id", sa.UUID(), nullable=True),
        sa.Column("replaces_id", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column("decided_by_id", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Every reference to a person or to produced content is SET NULL on
        # delete. Removing a user account under the retention policy must not
        # take the upload history with it, and the same holds for a document
        # that is purged later.
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name=op.f("fk_upload_jobs_uploaded_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            name=op.f("fk_upload_jobs_decided_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_upload_jobs_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document_versions.id"],
            name=op.f("fk_upload_jobs_version_id_document_versions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["replaces_id"],
            ["upload_jobs.id"],
            name=op.f("fk_upload_jobs_replaces_id_upload_jobs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_upload_jobs")),
    )

    op.create_index(op.f("ix_upload_jobs_state"), "upload_jobs", ["state"])
    op.create_index(op.f("ix_upload_jobs_uploaded_by_id"), "upload_jobs", ["uploaded_by_id"])
    op.create_index(op.f("ix_upload_jobs_document_id"), "upload_jobs", ["document_id"])
    # Looked up on every submission to recognise a file that was already sent.
    op.create_index(op.f("ix_upload_jobs_content_hash"), "upload_jobs", ["content_hash"])
    op.create_index(op.f("ix_upload_jobs_created_at"), "upload_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_upload_jobs_created_at"), table_name="upload_jobs")
    op.drop_index(op.f("ix_upload_jobs_content_hash"), table_name="upload_jobs")
    op.drop_index(op.f("ix_upload_jobs_document_id"), table_name="upload_jobs")
    op.drop_index(op.f("ix_upload_jobs_uploaded_by_id"), table_name="upload_jobs")
    op.drop_index(op.f("ix_upload_jobs_state"), table_name="upload_jobs")
    op.drop_table("upload_jobs")
