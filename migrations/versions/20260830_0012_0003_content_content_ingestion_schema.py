"""Content ingestion schema: sources, URLs, documents, versions and chunks.

Creates the tables that carry crawled and uploaded content, and everything a
citation needs to point back at the exact page, section and PDF page a passage
came from.

Revision ID: 14c4e27f5cf0
Revises: 0002_system_settings
Created: 2026-08-30 00:12:30.424853+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_content"
down_revision: str | None = "0002_system_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("excluded_paths", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("is_paused", sa.Boolean(), nullable=False),
        sa.Column("default_language", sa.String(length=5), nullable=False),
        sa.Column("department", sa.String(length=200), nullable=True),
        sa.Column("last_crawl_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_crawl_succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
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
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_sources_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        sa.UniqueConstraint("base_url", name="uq_sources_base_url"),
    )
    op.create_index("ix_sources_is_paused", "sources", ["is_paused"], unique=False)
    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("triggered_by_id", sa.UUID(), nullable=True),
        sa.Column("is_scheduled", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("urls_discovered", sa.Integer(), nullable=False),
        sa.Column("urls_fetched", sa.Integer(), nullable=False),
        sa.Column("urls_unchanged", sa.Integer(), nullable=False),
        sa.Column("urls_failed", sa.Integer(), nullable=False),
        sa.Column("urls_blocked", sa.Integer(), nullable=False),
        sa.Column("documents_created", sa.Integer(), nullable=False),
        sa.Column("versions_created", sa.Integer(), nullable=False),
        sa.Column(
            "blocked_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("error_summary", sa.Text(), nullable=False),
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
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_crawl_runs_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["triggered_by_id"],
            ["users.id"],
            name=op.f("fk_crawl_runs_triggered_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_crawl_runs")),
    )
    op.create_index("ix_crawl_runs_source_id", "crawl_runs", ["source_id"], unique=False)
    op.create_index("ix_crawl_runs_started_at", "crawl_runs", ["started_at"], unique=False)
    op.create_index("ix_crawl_runs_state", "crawl_runs", ["state"], unique=False)
    op.create_table(
        "crawled_urls",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("canonical_url", sa.String(length=2048), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_failure_reason", sa.String(length=64), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("etag", sa.String(length=256), nullable=True),
        sa.Column("last_modified_header", sa.String(length=128), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_excluded", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reason", sa.Text(), nullable=False),
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
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_crawled_urls_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_crawled_urls")),
        sa.UniqueConstraint("url", name="uq_crawled_urls_url"),
    )
    op.create_index(
        "ix_crawled_urls_last_failure_reason", "crawled_urls", ["last_failure_reason"], unique=False
    )
    op.create_index(
        "ix_crawled_urls_last_fetched_at", "crawled_urls", ["last_fetched_at"], unique=False
    )
    op.create_index("ix_crawled_urls_source_id", "crawled_urls", ["source_id"], unique=False)
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("crawled_url_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False),
        sa.Column("publication_state", sa.String(length=32), nullable=False),
        sa.Column(
            "breadcrumbs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("department", sa.String(length=200), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_version_id", sa.UUID(), nullable=True),
        sa.Column("uploaded_by_id", sa.UUID(), nullable=True),
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
            ["crawled_url_id"],
            ["crawled_urls.id"],
            name=op.f("fk_documents_crawled_url_id_crawled_urls"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_documents_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name=op.f("fk_documents_uploaded_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index("ix_documents_kind", "documents", ["kind"], unique=False)
    op.create_index("ix_documents_language", "documents", ["language"], unique=False)
    op.create_index(
        "ix_documents_publication_state", "documents", ["publication_state"], unique=False
    )
    op.create_index("ix_documents_source_id", "documents", ["source_id"], unique=False)
    op.create_table(
        "document_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("extraction_quality", sa.String(length=16), nullable=False),
        sa.Column("extraction_notes", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "http_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "injection_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("reviewed_by_id", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=False),
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
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"],
            ["users.id"],
            name=op.f("fk_document_versions_reviewed_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_document_id_version_number"
        ),
    )
    op.create_index(
        "ix_document_versions_content_hash", "document_versions", ["content_hash"], unique=False
    )
    op.create_index(
        "ix_document_versions_document_id", "document_versions", ["document_id"], unique=False
    )
    op.create_index("ix_document_versions_status", "document_versions", ["status"], unique=False)
    op.create_table(
        "chunks",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False),
        sa.Column(
            "section_path",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("anchor", sa.String(length=256), nullable=True),
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
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_chunks_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document_versions.id"],
            name=op.f("fk_chunks_version_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.UniqueConstraint("version_id", "ordinal", name="uq_chunks_version_id_ordinal"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"], unique=False)
    op.create_index("ix_chunks_language", "chunks", ["language"], unique=False)
    op.create_index("ix_chunks_version_id", "chunks", ["version_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_chunks_version_id", table_name="chunks")
    op.drop_index("ix_chunks_language", table_name="chunks")
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_table("chunks")
    op.drop_index("ix_document_versions_status", table_name="document_versions")
    op.drop_index("ix_document_versions_document_id", table_name="document_versions")
    op.drop_index("ix_document_versions_content_hash", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_index("ix_documents_source_id", table_name="documents")
    op.drop_index("ix_documents_publication_state", table_name="documents")
    op.drop_index("ix_documents_language", table_name="documents")
    op.drop_index("ix_documents_kind", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_crawled_urls_source_id", table_name="crawled_urls")
    op.drop_index("ix_crawled_urls_last_fetched_at", table_name="crawled_urls")
    op.drop_index("ix_crawled_urls_last_failure_reason", table_name="crawled_urls")
    op.drop_table("crawled_urls")
    op.drop_index("ix_crawl_runs_state", table_name="crawl_runs")
    op.drop_index("ix_crawl_runs_started_at", table_name="crawl_runs")
    op.drop_index("ix_crawl_runs_source_id", table_name="crawl_runs")
    op.drop_table("crawl_runs")
    op.drop_index("ix_sources_is_paused", table_name="sources")
    op.drop_table("sources")
