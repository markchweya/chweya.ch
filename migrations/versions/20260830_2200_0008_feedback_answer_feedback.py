"""Answer feedback table.

Revision ID: 0008_feedback
Revises: 0007_uploads
Created: 2026-08-30

One row per thumbs up or down on an answer. The question and the answer text
are never stored; the row carries only the vote and the answer's coarse
shape, so feedback can be read without keeping a transcript nobody agreed to.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_feedback"
down_revision: str | None = "0007_uploads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "answer_feedback",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("vote", sa.String(length=8), nullable=False),
        sa.Column("language", sa.String(length=8), server_default="", nullable=False),
        sa.Column("confidence", sa.String(length=16), server_default="", nullable=False),
        sa.Column("is_refusal", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "citation_urls", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("vote IN ('up', 'down')", name="ck_answer_feedback_vote_known"),
        sa.PrimaryKeyConstraint("id", name="pk_answer_feedback"),
    )


def downgrade() -> None:
    op.drop_table("answer_feedback")
