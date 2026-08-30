"""Contradiction findings and their review states.

A finding records what looks inconsistent between two passages. It never
records a verdict: only a reviewer resolves one, and the resolution is
audited.

Revision ID: 572a7397833e
Revises: 0004_retrieval
Created: 2026-08-30 01:01:14.899215+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_review"
down_revision: str | None = "0004_retrieval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contradiction_findings",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("first_chunk_id", sa.UUID(), nullable=False),
        sa.Column("second_chunk_id", sa.UUID(), nullable=False),
        sa.Column("first_value", sa.Text(), nullable=False),
        sa.Column("second_value", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "shared_context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("resolved_by_id", sa.UUID(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer_note", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["first_chunk_id"],
            ["chunks.id"],
            name=op.f("fk_contradiction_findings_first_chunk_id_chunks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_id"],
            ["users.id"],
            name=op.f("fk_contradiction_findings_resolved_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["second_chunk_id"],
            ["chunks.id"],
            name=op.f("fk_contradiction_findings_second_chunk_id_chunks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contradiction_findings")),
    )
    op.create_index(
        "ix_contradiction_findings_first_chunk_id",
        "contradiction_findings",
        ["first_chunk_id"],
        unique=False,
    )
    op.create_index(
        "ix_contradiction_findings_priority", "contradiction_findings", ["priority"], unique=False
    )
    op.create_index(
        "ix_contradiction_findings_second_chunk_id",
        "contradiction_findings",
        ["second_chunk_id"],
        unique=False,
    )
    op.create_index(
        "ix_contradiction_findings_state", "contradiction_findings", ["state"], unique=False
    )
    op.drop_index(
        op.f("ix_chunks_embedding_hnsw"),
        table_name="chunks",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_using="hnsw",
    )


def downgrade() -> None:
    op.create_index(
        op.f("ix_chunks_embedding_hnsw"),
        "chunks",
        ["embedding"],
        unique=False,
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_using="hnsw",
    )
    op.drop_index("ix_contradiction_findings_state", table_name="contradiction_findings")
    op.drop_index("ix_contradiction_findings_second_chunk_id", table_name="contradiction_findings")
    op.drop_index("ix_contradiction_findings_priority", table_name="contradiction_findings")
    op.drop_index("ix_contradiction_findings_first_chunk_id", table_name="contradiction_findings")
    op.drop_table("contradiction_findings")
