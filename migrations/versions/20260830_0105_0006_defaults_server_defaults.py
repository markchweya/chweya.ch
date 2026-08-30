"""Add server defaults to NOT NULL columns that had only Python defaults.

Revision ID: 0006_defaults
Revises: 0005_review
Created: 2026-08-30

Columns declared with a SQLAlchemy ``default=`` get their value from Python on
insert, so the database column is NOT NULL with no default of its own. Any
insert that does not go through the ORM then fails.

That is not hypothetical here. Section 5 requires a local database interface
and an administrator correcting a row by hand through Adminer hits exactly
this, as did the contradiction test fixtures. A column whose value is
"empty string" or "zero" should say so in the schema.

Columns that genuinely have no sensible default, such as identifiers, foreign
keys and content hashes, are left alone: a row without them is a broken row
and should be refused.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_defaults"
down_revision: str | None = "0005_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (table, column, default expression)
DEFAULTS: list[tuple[str, str, str]] = [
    ("documents", "title", "''"),
    ("documents", "media_type", "''"),
    ("documents", "language", "'de'"),
    ("documents", "publication_state", "'official'"),
    ("document_versions", "extracted_text", "''"),
    ("document_versions", "extraction_quality", "'good'"),
    ("document_versions", "extraction_notes", "''"),
    ("document_versions", "review_note", "''"),
    ("document_versions", "status", "'pending'"),
    ("chunks", "language", "'de'"),
    ("chunks", "token_estimate", "0"),
    ("sources", "excluded_paths", "''"),
    ("sources", "default_language", "'de'"),
    ("sources", "priority", "100"),
    ("sources", "is_paused", "false"),
    ("crawled_urls", "last_failure_reason", "''"),
    ("crawled_urls", "consecutive_failures", "0"),
    ("crawled_urls", "is_excluded", "false"),
    ("crawled_urls", "exclusion_reason", "''"),
    ("crawl_runs", "state", "'queued'"),
    ("crawl_runs", "is_scheduled", "false"),
    ("crawl_runs", "urls_discovered", "0"),
    ("crawl_runs", "urls_fetched", "0"),
    ("crawl_runs", "urls_unchanged", "0"),
    ("crawl_runs", "urls_failed", "0"),
    ("crawl_runs", "urls_blocked", "0"),
    ("crawl_runs", "documents_created", "0"),
    ("crawl_runs", "versions_created", "0"),
    ("crawl_runs", "error_summary", "''"),
    ("contradiction_findings", "state", "'open'"),
    ("contradiction_findings", "priority", "50"),
    ("contradiction_findings", "first_value", "''"),
    ("contradiction_findings", "second_value", "''"),
    ("contradiction_findings", "explanation", "''"),
    ("contradiction_findings", "reviewer_note", "''"),
]


def upgrade() -> None:
    for table, column, default in DEFAULTS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT {default}")


def downgrade() -> None:
    for table, column, _ in DEFAULTS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
