"""The record of one administrator upload, from arrival to whatever became of it.

An upload is not the same thing as a document. Most of what this table holds
concerns files that never became documents at all: a refused executable, a
file the scanner flagged, a PDF with no text layer. Those outcomes matter as
much as the successful ones, because section 16 requires that an administrator
can see what happened to a file they submitted, and section 13 requires that
every upload, replacement, download, approval and deletion is auditable.

So the row survives its file. When an upload is refused, no bytes are kept and
the row records why. When an upload is deleted, the bytes go and the row stays,
so a citation issued against it before the deletion can still be explained.

The document and version this upload produced are referenced rather than
duplicated. An uploaded document is an ordinary Document with its own version
history, which is what lets a replacement reuse the machinery the crawler
already uses for a changed page.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk


class UploadState(StrEnum):
    """Where an upload has reached.

    The unhappy outcomes are separate states rather than one "failed", because
    an administrator needs to know whether to fix the file, fix the metadata or
    call somebody. "Refused" and "infected" call for very different responses.
    """

    # Bytes written to quarantine, nothing decided yet. Transient.
    RECEIVED = "received"
    # Validation rejected the file. No bytes retained.
    REFUSED = "refused"
    # The scanner reported a detection. Bytes deleted, record kept.
    INFECTED = "infected"
    # The scanner could not reach a verdict. Bytes held in quarantine.
    SCAN_FAILED = "scan_failed"
    # The file is clean but nothing readable came out of it.
    EXTRACTION_FAILED = "extraction_failed"
    # Text extracted and chunked. Waiting for someone to supply the metadata
    # a citation needs: title, office, language, validity.
    AWAITING_METADATA = "awaiting_metadata"
    # Metadata supplied. Waiting for approval before it can answer anything.
    AWAITING_APPROVAL = "awaiting_approval"
    # Live in the public index.
    APPROVED = "approved"
    # Taken out of the index by a person. The version is retained.
    WITHDRAWN = "withdrawn"
    # A newer upload took its place.
    REPLACED = "replaced"
    # Bytes and chunks removed. The record is retained.
    DELETED = "deleted"

    @property
    def has_stored_file(self) -> bool:
        """Whether bytes for this upload are still expected on disk."""
        return self not in (
            UploadState.REFUSED,
            UploadState.INFECTED,
            UploadState.DELETED,
        )

    @property
    def is_final(self) -> bool:
        """Whether the upload has reached an outcome that will not change."""
        return self in (
            UploadState.REFUSED,
            UploadState.INFECTED,
            UploadState.REPLACED,
            UploadState.DELETED,
        )


class UploadJob(Base, TimestampMixin):
    """One file an administrator submitted."""

    __tablename__ = "upload_jobs"

    id: Mapped[uuid.UUID] = uuid_pk()

    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=UploadState.RECEIVED.value,
        server_default=UploadState.RECEIVED.value,
    )

    # Who submitted it. Nullable only so that removing an account under the
    # retention policy does not delete the upload history along with it.
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # --- what arrived ------------------------------------------------------
    # The sanitised display form of the name the browser sent. Attacker
    # controlled text, shown but never used to build a path.
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # What the client said it was sending, kept because a disagreement with the
    # detected type is worth being able to look up afterwards.
    declared_media_type: Mapped[str] = mapped_column(
        String(128), nullable=False, default="", server_default=""
    )
    # What the bytes actually are.
    detected_media_type: Mapped[str] = mapped_column(
        String(128), nullable=False, default="", server_default=""
    )
    upload_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="", server_default=""
    )
    byte_size: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    # SHA-256 of the submitted bytes, so re-uploading the same file can be
    # recognised rather than silently producing a duplicate version.
    content_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )

    # --- where it went -----------------------------------------------------
    # Relative to the storage root, generated server-side. Null once the bytes
    # have been deleted or were never kept.
    storage_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_quarantined: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # --- what was decided --------------------------------------------------
    # A machine-readable refusal reason from app.uploads.validation. Empty when
    # validation passed, so refusals can be counted by cause.
    refusal_reason: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    scan_outcome: Mapped[str] = mapped_column(
        String(16), nullable=False, default="", server_default=""
    )
    # The scanner's own summary, trimmed. Useful to a reviewer, trusted for
    # nothing.
    scan_detail: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    scanned_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- what it became ----------------------------------------------------
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The upload this one replaced, so a chain of replacements can be walked
    # back to the original submission.
    replaces_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("upload_jobs.id", ondelete="SET NULL"), nullable=True
    )

    # Free text a person wrote when approving, withdrawing or deleting. The
    # reason a document was taken down is often the only record of a decision
    # made in a corridor.
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    replaces: Mapped[UploadJob | None] = relationship(remote_side=[id])

    __table_args__ = (
        Index("ix_upload_jobs_state", "state"),
        Index("ix_upload_jobs_uploaded_by_id", "uploaded_by_id"),
        Index("ix_upload_jobs_document_id", "document_id"),
        Index("ix_upload_jobs_content_hash", "content_hash"),
        Index("ix_upload_jobs_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<UploadJob {self.id} {self.state} {self.original_filename!r}>"
