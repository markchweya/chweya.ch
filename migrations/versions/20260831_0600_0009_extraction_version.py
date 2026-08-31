"""Room for the extraction version in the crawl change detector.

Revision ID: 0009_extraction_version
Revises: 0008_feedback
Created: 2026-08-31

The crawled URL's content hash now carries the extraction version, like
"<sha256>:v2", so improving the extractor forces every page through it again
on the next crawl. The column grows to fit the marker.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_extraction_version"
down_revision: str | None = "0008_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "crawled_urls",
        "content_hash",
        existing_type=sa.String(length=64),
        type_=sa.String(length=80),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "crawled_urls",
        "content_hash",
        existing_type=sa.String(length=80),
        type_=sa.String(length=64),
        existing_nullable=True,
    )
