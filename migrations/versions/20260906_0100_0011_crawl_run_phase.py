"""Live progress on crawl runs.

Revision ID: 0011_crawl_run_phase
Revises: 0010_cantons
Created: 2026-09-06

The sources page now reports a run while it happens. The crawl writes its
counters every few pages, and the runner records which phase follows the
crawl, indexing or embedding, and how many passages it has embedded so far.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_crawl_run_phase"
down_revision: str | None = "0010_cantons"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "crawl_runs",
        sa.Column("phase", sa.String(length=16), nullable=False, server_default="crawling"),
    )
    op.add_column(
        "crawl_runs",
        sa.Column("chunks_embedded", sa.Integer(), nullable=False, server_default="0"),
    )
    # Every run that already finished is done; only a live one is crawling.
    op.execute("UPDATE crawl_runs SET phase = 'done' WHERE state NOT IN ('queued', 'running')")


def downgrade() -> None:
    op.drop_column("crawl_runs", "chunks_embedded")
    op.drop_column("crawl_runs", "phase")
