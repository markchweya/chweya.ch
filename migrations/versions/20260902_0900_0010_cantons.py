"""Sources and feedback carry their canton.

Revision ID: 0010_cantons
Revises: 0009_extraction_version
Created: 2026-09-02

One Dumi now serves several cantons. A source belongs to exactly one, and
retrieval only reads sources of the canton being served; feedback records
which canton the answer came from. Existing rows are Zug, which is what the
defaults say.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_cantons"
down_revision: str | None = "0009_extraction_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("canton", sa.String(length=16), nullable=False, server_default="zug"),
    )
    op.add_column(
        "answer_feedback",
        sa.Column("canton", sa.String(length=16), nullable=False, server_default="zug"),
    )


def downgrade() -> None:
    op.drop_column("answer_feedback", "canton")
    op.drop_column("sources", "canton")
