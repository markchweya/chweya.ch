"""Sources, crawled URLs, documents, versions and chunks.

The shape of this schema follows one requirement in section 11: every
substantive answer must carry a citation that points at the exact official
page or PDF page it came from, and that citation must remain traceable to the
version of the source it was drawn from.

That means a chunk cannot simply store text. It has to reach back through its
version to the document, the URL and the retrieval time, so an answer given
today can still be explained after the canton edits the page tomorrow.

Lifecycle states are explicit rather than implied by nulls. "This document has
no current version" and "this document was withdrawn by a reviewer" are
different situations that a null would render identical.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk

# The width of the embedding column. Fixed at migration time: PostgreSQL
# vector columns have a declared dimension, so changing the embedding model to
# one with a different output size requires a migration and a re-embed, not a
# configuration change. Kept in step with EMBEDDING_DIMENSIONS.
EMBEDDING_DIMENSIONS = 768

# Maps a chunk's language to the PostgreSQL text search configuration that
# stems it correctly. Without the right configuration, German compound words
# and French elisions are indexed as-is and a query never matches them.
TEXT_SEARCH_CONFIG: dict[str, str] = {
    "de": "german",
    "en": "english",
    "fr": "french",
    "it": "italian",
}
DEFAULT_TEXT_SEARCH_CONFIG = "simple"


class SourceKind(StrEnum):
    """Where a document came from.

    Kept separate from the media type. A PDF discovered by crawling and a PDF
    uploaded by an administrator need different review rules, even though both
    are PDFs.
    """

    CRAWLED_PAGE = "crawled_page"
    CRAWLED_DOCUMENT = "crawled_document"
    ADMIN_UPLOAD = "admin_upload"


class ContentStatus(StrEnum):
    """Whether a document version may be used to answer questions.

    Only APPROVED content reaches public retrieval. Everything else is held
    back, which is what section 16 means by requiring explicit approval before
    a document enters the public index.
    """

    # Fetched or uploaded, not yet processed.
    PENDING = "pending"
    # Extracted and indexed, awaiting a reviewer where review is required.
    AWAITING_REVIEW = "awaiting_review"
    # Usable in answers.
    APPROVED = "approved"
    # A newer version has replaced this one. Retained for citation history.
    SUPERSEDED = "superseded"
    # A reviewer determined this must not be used. Retained with its reason.
    EXCLUDED = "excluded"
    # Removed from the canton site. Retained so old citations stay explicable.
    GONE = "gone"
    # Failed extraction or a failed safety check.
    FAILED = "failed"
    # Held pending a malware or content check.
    QUARANTINED = "quarantined"


class PublicationState(StrEnum):
    """How authoritative a document claims to be.

    Set by an administrator on upload. Only OFFICIAL and SUPPLEMENTARY may
    reach public retrieval; DRAFT and INTERNAL never do, whatever their
    ContentStatus says. Section 16 requires that separation.
    """

    OFFICIAL = "official"
    SUPPLEMENTARY = "supplementary"
    DRAFT = "draft"
    INTERNAL = "internal"


class CrawlRunState(StrEnum):
    """Lifecycle of one crawl or synchronisation run."""

    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExtractionQuality(StrEnum):
    """How much to trust the text pulled out of a document.

    LOW and FAILED are the interesting ones. A scanned PDF that OCR read badly
    produces text that looks plausible and is wrong, which is worse than no
    text at all, so it is flagged for a human rather than indexed silently.
    """

    GOOD = "good"
    PARTIAL = "partial"
    LOW = "low"
    FAILED = "failed"


class Source(Base, TimestampMixin):
    """A configured area of a site that may be crawled.

    A source is a policy decision, not a URL. Adding one widens what the
    crawler will fetch, so creation is restricted to a content administrator
    and is audited.
    """

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Must be on the configured hostname allowlist. Checked server-side on
    # every write; a value here is never trusted at crawl time.
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # Path prefixes under base_url that are excluded, one per line.
    excluded_paths: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Higher runs first when a run is bounded by CRAWLER_MAX_PAGES_PER_RUN.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Expected primary language, used as a fallback when detection is
    # inconclusive on a short page.
    default_language: Mapped[str] = mapped_column(String(5), nullable=False, default="de")

    # Which office publishes this area, when it can be determined. Shown beside
    # citations so a resident knows who to contact.
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)

    last_crawl_started_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_crawl_succeeded_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    documents: Mapped[list[Document]] = relationship(back_populates="source")

    __table_args__ = (
        UniqueConstraint("base_url", name="uq_sources_base_url"),
        Index("ix_sources_is_paused", "is_paused"),
    )

    def __repr__(self) -> str:
        return f"<Source {self.name}>"


class CrawledUrl(Base, TimestampMixin):
    """One URL the crawler knows about, and what happened to it.

    Separate from Document because most URLs never become documents. They
    redirect, return 404, fall outside the allowlist, or are excluded by
    robots.txt, and all of that is worth keeping so a run does not rediscover
    and re-refuse the same URLs every time.
    """

    __tablename__ = "crawled_urls"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )

    # The normalised form. Uniqueness is on this, so the same page reached by
    # several spellings is one row.
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # Where the canonical link element pointed, when the page declared one.
    canonical_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Empty when the last fetch succeeded. Otherwise the machine-readable
    # refusal reason, so blocked attempts can be counted by cause.
    last_failure_reason: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Conditional request state, so an unchanged page costs one round trip and
    # no body.
    etag: Mapped[str | None] = mapped_column(String(256), nullable=True)
    last_modified_header: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    first_seen_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_fetched_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_changed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Excluded by an administrator, independently of robots.txt.
    is_excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exclusion_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("url", name="uq_crawled_urls_url"),
        Index("ix_crawled_urls_source_id", "source_id"),
        Index("ix_crawled_urls_last_fetched_at", "last_fetched_at"),
        Index("ix_crawled_urls_last_failure_reason", "last_failure_reason"),
    )


class Document(Base, TimestampMixin):
    """A logical document: one page or one file, across all its versions."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    crawled_url_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("crawled_urls.id", ondelete="SET NULL"), nullable=True
    )

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    media_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    language: Mapped[str] = mapped_column(String(5), nullable=False, default="de")

    # Set by an administrator for uploads; official for crawled canton pages.
    publication_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PublicationState.OFFICIAL.value
    )

    # Navigation path on the canton site, stored as an ordered JSON array.
    # Shown with citations, because "Steuern > Natürliche Personen > Fristen"
    # tells a resident far more than a URL does.
    breadcrumbs: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Dates the document itself claims, when it states them. Distinct from the
    # crawl timestamps, which say when we looked.
    published_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_from: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Points at the version currently used for answers. Null means nothing of
    # this document is approved, which is different from the document being
    # withdrawn.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )

    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    source: Mapped[Source | None] = relationship(back_populates="documents")
    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        foreign_keys="DocumentVersion.document_id",
    )

    __table_args__ = (
        Index("ix_documents_source_id", "source_id"),
        Index("ix_documents_language", "language"),
        Index("ix_documents_kind", "kind"),
        Index("ix_documents_publication_state", "publication_state"),
    )

    def __repr__(self) -> str:
        return f"<Document {self.id} {self.title[:40]!r}>"


class DocumentVersion(Base, TimestampMixin):
    """One retrieved state of a document.

    A new version is created whenever the content hash changes. Old versions
    are kept rather than overwritten, so a citation issued last month can still
    be explained after the canton edits the page.
    """

    __tablename__ = "document_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )

    # Monotonic per document, starting at 1. Human-facing, unlike the UUID.
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ContentStatus.PENDING.value
    )

    # The cleaned text used for chunking and retrieval. Kept so an extraction
    # change can be re-run without re-fetching the whole site.
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extraction_quality: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ExtractionQuality.GOOD.value
    )
    extraction_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Where the original bytes live, for PDFs and uploads. A server-generated
    # random name, never anything derived from the uploaded filename.
    storage_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Response headers worth keeping, filtered to the ones that matter for
    # caching and provenance. Not the whole header set: cookies and
    # authentication headers have no business being stored.
    http_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    retrieved_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # When this version was last confirmed to still be what the site serves.
    last_verified_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Set when a prompt-injection pattern was found in the content. The
    # document is still indexed, because canton pages legitimately contain
    # instruction-like text, but it is flagged for review.
    injection_flags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")

    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    document: Mapped[Document] = relationship(
        back_populates="versions", foreign_keys=[document_id]
    )
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_document_id_version_number"
        ),
        Index("ix_document_versions_document_id", "document_id"),
        Index("ix_document_versions_status", "status"),
        Index("ix_document_versions_content_hash", "content_hash"),
    )

    def __repr__(self) -> str:
        return f"<DocumentVersion {self.document_id} v{self.version_number} {self.status}>"


class Chunk(Base, TimestampMixin):
    """A retrievable passage, carrying everything a citation needs.

    Every field here that looks like duplication from the parent tables is
    there so a citation can be rendered from one row. Retrieval returns
    hundreds of chunks and discards most of them; joining four tables for each
    one just to find out it was not used is waste.
    """

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = uuid_pk()
    version_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )

    # Position within the document, so adjacent chunks can be reassembled when
    # an answer needs more context than one passage carries.
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    language: Mapped[str] = mapped_column(String(5), nullable=False, default="de")

    # --- citation anchors --------------------------------------------------
    # The heading trail this passage sits under, so a citation can say which
    # section of a long page it came from.
    section_path: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    # For PDFs. Required by section 7: a PDF citation without a page number
    # sends a resident to search a fifty-page document by hand.
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # A fragment identifier when the source page provides a usable anchor, so
    # a citation link lands on the passage rather than the top of the page.
    anchor: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # --- retrieval ---------------------------------------------------------
    # The semantic arm of hybrid search. Nullable because a chunk exists
    # before it is embedded, and an embedding run can fail without losing the
    # text.
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )
    # Which model produced the vector. Vectors from two models are not
    # comparable, so mixing them silently degrades every result, and a model
    # change has to be detectable rather than inferred from a deployment date.
    embedding_model: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # The keyword arm. Populated at write time with the PostgreSQL text search
    # configuration matching the chunk's language, rather than by a generated
    # column, because a generated column can only carry one fixed
    # configuration and this system indexes four languages.
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)

    version: Mapped[DocumentVersion] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("version_id", "ordinal", name="uq_chunks_version_id_ordinal"),
        Index("ix_chunks_version_id", "version_id"),
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_language", "language"),
        # GIN for full-text search. Created in the migration rather than here
        # because it needs a postgresql_using clause.
        Index("ix_chunks_search_vector", "search_vector", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        return f"<Chunk {self.document_id} #{self.ordinal}>"


class CrawlRun(Base, TimestampMixin):
    """One crawl or synchronisation run, and what it did.

    Kept so an administrator can see what a run touched, and so a failed run
    can be diagnosed without re-running it.
    """

    __tablename__ = "crawl_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )

    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CrawlRunState.QUEUED.value
    )
    # Whether a person started this or the scheduler did.
    triggered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_scheduled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    urls_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    urls_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    urls_unchanged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    urls_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    urls_blocked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    documents_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    versions_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Counts of refusals by reason, so the dashboard can show why URLs were
    # skipped without storing every skipped URL.
    blocked_reasons: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    error_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        Index("ix_crawl_runs_source_id", "source_id"),
        Index("ix_crawl_runs_state", "state"),
        Index("ix_crawl_runs_started_at", "started_at"),
    )

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()
