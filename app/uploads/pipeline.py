"""The upload workflow: what happens to a file between arrival and approval.

The order of the steps is the whole design, so it is worth stating plainly:

1. Validate the bytes. Nothing is written to disk before this passes.
2. Write to quarantine under a generated name.
3. Scan. Nothing leaves quarantine before this passes.
4. Extract text. Only now does a parser see the file.
5. Create the document, its first version and its chunks, held back from the
   public index.
6. A person supplies the metadata a citation needs, and approves.

Steps 1 to 5 are automatic. Step 6 is not, and cannot be made so: section 16
requires explicit approval before an uploaded document can answer anything,
because an uploaded file carries no canton URL to check it against.

Every transition writes an audit entry in the same transaction as the change
it describes. An upload that is rolled back must not leave a log claiming it
happened.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import SUPPORTED_LANGUAGES, Settings, get_settings
from app.db.models import (
    AuditAction,
    AuditOutcome,
    Chunk,
    ContentStatus,
    Document,
    DocumentVersion,
    ExtractionQuality,
    PublicationState,
    SourceKind,
    UploadJob,
    UploadState,
    User,
)
from app.ingest.chunking import chunk_page, chunk_pdf
from app.ingest.extract_document import (
    ExtractedDocument,
    extract_csv,
    extract_docx,
    extract_markdown,
    extract_text,
)
from app.ingest.extract_html import extract_html
from app.ingest.extract_pdf import extract_pdf
from app.ingest.injection import scan as scan_for_injection
from app.observability import get_logger
from app.security.audit import record
from app.uploads.scanning import ScanOutcome, ScanResult, scan_file
from app.uploads.storage import DocumentStore
from app.uploads.validation import UploadKind, refusal_message_key, validate_upload

logger = get_logger(__name__)

# Publication states an uploaded document may hold and still be answerable.
# A draft or an internal paper is stored, versioned and searchable in the
# administration interface, and never reaches a resident.
PUBLIC_PUBLICATION_STATES = frozenset(
    {PublicationState.OFFICIAL.value, PublicationState.SUPPLEMENTARY.value}
)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass
class UploadOutcome:
    """What one submission produced.

    Carries the job either way. A refusal is an outcome with a record, not an
    exception, because the administrator needs to see what happened to the
    file they sent.
    """

    job: UploadJob
    accepted: bool
    # A message key for the interface, so the reason can be shown in the
    # administrator's language.
    message_key: str = ""


# ------------------------------------------------------------------ extract


@dataclass
class ExtractionOutcome:
    """Text and structure pulled from an uploaded file, whatever its format."""

    title: str
    text: str
    quality: ExtractionQuality
    notes: list[str]
    chunks: list  # list[TextChunk]
    page_count: int | None = None
    language: str | None = None
    breadcrumbs: list[str] | None = None
    # Active content found inside a PDF. Non-empty means a reviewer looks
    # before this is approved, so it is surfaced rather than only logged.
    active_content: list[str] | None = None


def extract_for_kind(
    kind: UploadKind, data: bytes, *, filename: str, language: str
) -> ExtractionOutcome:
    """Run the extractor matching the validated format.

    Dispatch is on the validated kind rather than on the extension, so a file
    is only ever handed to the parser for what its bytes say it is.
    """
    if kind is UploadKind.PDF:
        pdf = extract_pdf(data, filename=filename)
        return ExtractionOutcome(
            title=pdf.title,
            text=pdf.text,
            quality=pdf.quality,
            notes=list(pdf.notes),
            chunks=chunk_pdf(pdf, language=language),
            page_count=pdf.page_count,
            active_content=list(pdf.active_content),
        )

    if kind is UploadKind.HTML:
        page = extract_html(data.decode("utf-8", errors="replace"))
        return ExtractionOutcome(
            title=page.title,
            text=page.text,
            quality=ExtractionQuality.GOOD if page.is_usable else ExtractionQuality.LOW,
            notes=[page.quality_note] if page.quality_note else [],
            chunks=chunk_page(page, language=language),
            language=page.language,
            breadcrumbs=list(page.breadcrumbs),
        )

    extractors = {
        UploadKind.DOCX: extract_docx,
        UploadKind.TXT: extract_text,
        UploadKind.MARKDOWN: extract_markdown,
        UploadKind.CSV: extract_csv,
    }
    document: ExtractedDocument = extractors[kind](data, filename=filename)
    return ExtractionOutcome(
        title=document.title,
        text=document.text,
        quality=document.quality,
        notes=list(document.notes),
        chunks=chunk_page(document.as_page(), language=language),
    )


# ------------------------------------------------------------------ receive


def _audit(
    db: Session,
    *,
    action: AuditAction,
    job: UploadJob,
    actor: User | None,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    request_id: str | None = None,
    detail: dict | None = None,
) -> None:
    """Write one audit entry about an upload.

    The filename is included because it is what an administrator recognises the
    file by. It is attacker-controlled text, so it is the sanitised display
    form, and it is the only thing from the upload that is written here.
    """
    payload = {"filename": job.original_filename, "state": job.state}
    payload.update(detail or {})
    record(
        db,
        action=action,
        outcome=outcome,
        actor_user_id=actor.id if actor else None,
        actor_label=f"user:{actor.id}" if actor else "system",
        object_type="upload",
        object_id=str(job.id),
        request_id=request_id,
        detail=payload,
    )


def receive_upload(
    db: Session,
    *,
    filename: str,
    declared_media_type: str,
    data: bytes,
    actor: User,
    language: str = "de",
    replaces: UploadJob | None = None,
    request_id: str | None = None,
    settings: Settings | None = None,
    store: DocumentStore | None = None,
) -> UploadOutcome:
    """Take one submitted file through validation, scanning and extraction.

    Returns as soon as a step refuses. The job row records which step that was,
    so an administrator sees "refused: content does not match extension" rather
    than a generic failure.
    """
    settings = settings or get_settings()
    store = store or DocumentStore(settings)

    job = UploadJob(
        state=UploadState.RECEIVED.value,
        uploaded_by_id=actor.id,
        original_filename="",
        declared_media_type=(declared_media_type or "")[:128],
        byte_size=len(data),
        content_hash=hashlib.sha256(data).hexdigest(),
        replaces_id=replaces.id if replaces else None,
    )

    # --- 1. validate -------------------------------------------------------
    result = validate_upload(
        filename, declared_media_type, data, max_bytes=settings.upload_max_bytes
    )
    job.original_filename = result.safe_display_name
    job.detected_media_type = result.detected_media_type[:128]

    if not result.ok or result.kind is None:
        job.state = UploadState.REFUSED.value
        job.refusal_reason = result.reason
        db.add(job)
        db.flush()
        _audit(
            db,
            action=AuditAction.DOCUMENT_UPLOADED,
            job=job,
            actor=actor,
            outcome=AuditOutcome.FAILURE,
            request_id=request_id,
            detail={"reason": result.reason, "detected": result.detected_media_type},
        )
        logger.warning("upload.refused", reason=result.reason)
        return UploadOutcome(job, False, refusal_message_key(result.reason))

    job.upload_kind = result.kind.value
    db.add(job)
    db.flush()

    # --- 2. quarantine -----------------------------------------------------
    stored = store.write(data, quarantined=True)
    job.storage_path = stored.relative_path
    job.is_quarantined = True

    # --- 3. scan -----------------------------------------------------------
    scan = scan_file(str(store.path_of(stored.relative_path, quarantined=True)), settings)
    job.scan_outcome = scan.outcome.value
    job.scan_detail = scan.detail[:2000]
    job.scanned_at = _utcnow()

    if scan.outcome is ScanOutcome.INFECTED:
        # The bytes go immediately. Holding a known-infected file so that an
        # administrator can look at it serves nobody and creates a second
        # problem.
        store.delete(stored.relative_path, quarantined=True)
        job.storage_path = None
        job.state = UploadState.INFECTED.value
        _audit(
            db,
            action=AuditAction.DOCUMENT_QUARANTINED,
            job=job,
            actor=actor,
            outcome=AuditOutcome.FAILURE,
            request_id=request_id,
            detail={"scan": scan.outcome.value},
        )
        logger.error("upload.infected")
        return UploadOutcome(job, False, "upload.refused.infected")

    if not scan.outcome.may_promote:
        # The file stays in quarantine. A scanner that could not decide is not
        # the same as a detection, and deleting the file would destroy the only
        # copy of something that may be perfectly fine.
        job.state = UploadState.SCAN_FAILED.value
        _audit(
            db,
            action=AuditAction.DOCUMENT_QUARANTINED,
            job=job,
            actor=actor,
            outcome=AuditOutcome.FAILURE,
            request_id=request_id,
            detail={"scan": scan.outcome.value},
        )
        return UploadOutcome(job, False, "upload.refused.scan_failed")

    # --- 4. extract --------------------------------------------------------
    extraction = extract_for_kind(
        result.kind, data, filename=job.original_filename, language=language
    )

    if extraction.quality is ExtractionQuality.FAILED or not extraction.chunks:
        job.state = UploadState.EXTRACTION_FAILED.value
        _audit(
            db,
            action=AuditAction.DOCUMENT_UPLOADED,
            job=job,
            actor=actor,
            outcome=AuditOutcome.FAILURE,
            request_id=request_id,
            detail={"reason": "extraction_failed", "notes": extraction.notes[:5]},
        )
        return UploadOutcome(job, False, "upload.refused.extraction_failed")

    # --- 5. promote and persist -------------------------------------------
    promoted = store.promote(stored.relative_path)
    job.is_quarantined = False

    document = _document_for(db, job, extraction, actor=actor, language=language, replaces=replaces)
    version = _version_for(
        db,
        job,
        document,
        extraction,
        scan=scan,
        storage_path=promoted.relative_path,
        byte_size=promoted.byte_size,
    )

    job.document_id = document.id
    job.version_id = version.id
    job.state = UploadState.AWAITING_METADATA.value
    db.flush()

    _audit(
        db,
        action=AuditAction.DOCUMENT_UPLOADED,
        job=job,
        actor=actor,
        request_id=request_id,
        detail={
            "document_id": str(document.id),
            "version": version.version_number,
            "chunks": len(extraction.chunks),
            "quality": extraction.quality.value,
        },
    )
    logger.info(
        "upload.accepted",
        kind=job.upload_kind,
        chunks=len(extraction.chunks),
        quality=extraction.quality.value,
    )
    return UploadOutcome(job, True, "upload.accepted")


def _document_for(
    db: Session,
    job: UploadJob,
    extraction: ExtractionOutcome,
    *,
    actor: User,
    language: str,
    replaces: UploadJob | None,
) -> Document:
    """Return the document this upload belongs to.

    A replacement reuses the document it replaces, which is what makes the old
    version history and the citations against it stay coherent. Anything else
    starts a new document.
    """
    if replaces is not None and replaces.document_id is not None:
        existing = db.get(Document, replaces.document_id)
        if existing is not None:
            return existing

    document = Document(
        kind=SourceKind.ADMIN_UPLOAD.value,
        url=None,
        title=extraction.title or job.original_filename,
        media_type=job.detected_media_type,
        language=extraction.language or language,
        # An upload claims nothing until a person says what it is. Draft keeps
        # it out of the public index even if some later code path approves the
        # version by mistake.
        publication_state=PublicationState.DRAFT.value,
        breadcrumbs=extraction.breadcrumbs or [],
        uploaded_by_id=actor.id,
    )
    db.add(document)
    db.flush()
    return document


def _version_for(
    db: Session,
    job: UploadJob,
    document: Document,
    extraction: ExtractionOutcome,
    *,
    scan: ScanResult,
    storage_path: str,
    byte_size: int,
) -> DocumentVersion:
    """Create the version and its chunks, held out of the public index."""
    next_number = (
        db.execute(
            select(func.coalesce(func.max(DocumentVersion.version_number), 0)).where(
                DocumentVersion.document_id == document.id
            )
        ).scalar_one()
        + 1
    )

    # An uploaded file is untrusted content like any other. It is indexed and
    # flagged rather than refused, because an office circular explaining a
    # procedure legitimately contains instruction-shaped text.
    injection = scan_for_injection(extraction.text)
    if injection.is_suspicious:
        logger.warning(
            "upload.injection_flagged", categories=",".join(injection.categories)
        )

    notes = list(extraction.notes)
    if extraction.active_content:
        notes.append("active_content: " + ", ".join(extraction.active_content))
    if scan.outcome is ScanOutcome.NOT_CONFIGURED:
        notes.append("uploaded_without_malware_scanning")

    version = DocumentVersion(
        document_id=document.id,
        version_number=next_number,
        content_hash=job.content_hash,
        # Never APPROVED on arrival, whatever the extraction quality. That is
        # the difference between an upload and a crawled canton page: the page
        # has a public URL anyone can check, the upload has only the word of
        # whoever sent it.
        status=ContentStatus.AWAITING_REVIEW.value,
        extracted_text=extraction.text,
        extraction_quality=extraction.quality.value,
        extraction_notes="; ".join(notes),
        storage_path=storage_path,
        byte_size=byte_size,
        page_count=extraction.page_count,
        http_metadata={},
        retrieved_at=_utcnow(),
        last_verified_at=_utcnow(),
        injection_flags=[
            {"category": finding.category, "excerpt": finding.excerpt}
            for finding in injection.findings
        ],
    )
    db.add(version)
    db.flush()

    for chunk in extraction.chunks:
        db.add(
            Chunk(
                version_id=version.id,
                document_id=document.id,
                ordinal=chunk.ordinal,
                text=chunk.text,
                token_estimate=chunk.token_estimate,
                language=chunk.language,
                section_path=list(chunk.section_path),
                page_number=chunk.page_number,
                anchor=chunk.anchor,
            )
        )

    return version


# ----------------------------------------------------------------- metadata


@dataclass(frozen=True)
class DocumentMetadata:
    """What a person must supply before an upload can be approved.

    None of it can be inferred reliably. A PDF's own title field is often the
    filename the author started from, and its language is frequently absent or
    wrong. Guessing here would put an invented office name next to a citation.
    """

    title: str
    department: str
    language: str
    publication_state: str
    published_at: dt.datetime | None = None
    valid_from: dt.datetime | None = None
    valid_until: dt.datetime | None = None


def metadata_problems(metadata: DocumentMetadata, *, languages: frozenset[str]) -> list[str]:
    """Return message keys for everything wrong with the supplied metadata."""
    problems: list[str] = []

    if len(metadata.title.strip()) < 3:
        problems.append("upload.metadata.title_required")
    if not metadata.department.strip():
        problems.append("upload.metadata.department_required")
    if metadata.language not in languages:
        problems.append("upload.metadata.language_unsupported")
    if metadata.publication_state not in {state.value for state in PublicationState}:
        problems.append("upload.metadata.publication_state_invalid")
    if (
        metadata.valid_from is not None
        and metadata.valid_until is not None
        and metadata.valid_until < metadata.valid_from
    ):
        problems.append("upload.metadata.validity_reversed")

    return problems


def apply_metadata(
    db: Session,
    job: UploadJob,
    metadata: DocumentMetadata,
    *,
    actor: User,
    request_id: str | None = None,
) -> list[str]:
    """Record the metadata for an uploaded document.

    Returns the list of problems. An empty list means it was applied and the
    upload is now waiting for approval.
    """
    problems = metadata_problems(metadata, languages=frozenset(SUPPORTED_LANGUAGES))
    if problems:
        return problems

    if job.document_id is None:
        return ["upload.metadata.no_document"]

    document = db.get(Document, job.document_id)
    if document is None:
        return ["upload.metadata.no_document"]

    document.title = metadata.title.strip()
    document.department = metadata.department.strip()
    document.language = metadata.language
    document.publication_state = metadata.publication_state
    document.published_at = metadata.published_at
    document.valid_from = metadata.valid_from
    document.valid_until = metadata.valid_until

    # The chunks were written with the language guessed at extraction time. If
    # the person correcting the metadata says otherwise, the chunks have to
    # follow, because the language decides which text search configuration
    # stems them and a German chunk indexed as English will not be found.
    db.query(Chunk).filter(Chunk.version_id == job.version_id).update(
        {Chunk.language: metadata.language, Chunk.search_vector: None},
        synchronize_session=False,
    )

    if job.state == UploadState.AWAITING_METADATA.value:
        job.state = UploadState.AWAITING_APPROVAL.value

    _audit(
        db,
        action=AuditAction.DOCUMENT_UPLOADED,
        job=job,
        actor=actor,
        request_id=request_id,
        detail={
            "step": "metadata",
            "document_id": str(document.id),
            "publication_state": metadata.publication_state,
            "language": metadata.language,
        },
    )
    return []


# ----------------------------------------------------------------- decisions


def approve(
    db: Session,
    job: UploadJob,
    *,
    actor: User,
    note: str = "",
    request_id: str | None = None,
) -> list[str]:
    """Put an uploaded document into the public index.

    Refuses unless the metadata is complete and the publication state is one a
    resident may be shown. A draft can be approved as a stored document; it
    still does not become answerable.
    """
    if job.state != UploadState.AWAITING_APPROVAL.value:
        return ["upload.approve.wrong_state"]
    if job.version_id is None or job.document_id is None:
        return ["upload.approve.no_document"]

    document = db.get(Document, job.document_id)
    version = db.get(DocumentVersion, job.version_id)
    if document is None or version is None:
        return ["upload.approve.no_document"]

    if document.publication_state not in PUBLIC_PUBLICATION_STATES:
        return ["upload.approve.not_public_state"]

    # Supersede whatever this document was serving before, rather than
    # deleting it. A citation issued last week against the old version has to
    # stay explicable.
    if document.current_version_id is not None and document.current_version_id != version.id:
        previous = db.get(DocumentVersion, document.current_version_id)
        if previous is not None and previous.status == ContentStatus.APPROVED.value:
            previous.status = ContentStatus.SUPERSEDED.value

    version.status = ContentStatus.APPROVED.value
    version.reviewed_by_id = actor.id
    version.reviewed_at = _utcnow()
    version.review_note = note.strip()[:2000]
    document.current_version_id = version.id

    job.state = UploadState.APPROVED.value
    job.decided_by_id = actor.id
    job.decided_at = _utcnow()
    job.note = note.strip()[:2000]

    _audit(
        db,
        action=AuditAction.DOCUMENT_APPROVED,
        job=job,
        actor=actor,
        request_id=request_id,
        detail={"document_id": str(document.id), "version": version.version_number},
    )
    logger.info("upload.approved", version=version.version_number)
    return []


def withdraw(
    db: Session,
    job: UploadJob,
    *,
    actor: User,
    reason: str,
    request_id: str | None = None,
) -> list[str]:
    """Take an uploaded document out of the index, keeping the file.

    Used when a document is superseded by a decision rather than by a newer
    file: a fee schedule that stopped applying, a form that was withdrawn. The
    bytes and the version stay, so the reason it was pulled is on record.
    """
    if job.state not in (UploadState.APPROVED.value, UploadState.AWAITING_APPROVAL.value):
        return ["upload.withdraw.wrong_state"]
    if not reason.strip():
        return ["upload.withdraw.reason_required"]

    document = db.get(Document, job.document_id) if job.document_id else None
    version = db.get(DocumentVersion, job.version_id) if job.version_id else None
    if document is None or version is None:
        return ["upload.withdraw.no_document"]

    version.status = ContentStatus.EXCLUDED.value
    version.review_note = reason.strip()[:2000]
    version.reviewed_by_id = actor.id
    version.reviewed_at = _utcnow()

    if document.current_version_id == version.id:
        document.current_version_id = None

    job.state = UploadState.WITHDRAWN.value
    job.decided_by_id = actor.id
    job.decided_at = _utcnow()
    job.note = reason.strip()[:2000]

    _audit(
        db,
        action=AuditAction.DOCUMENT_WITHDRAWN,
        job=job,
        actor=actor,
        request_id=request_id,
        detail={"document_id": str(document.id), "reason": reason.strip()[:200]},
    )
    return []


def replace(
    db: Session,
    previous: UploadJob,
    *,
    filename: str,
    declared_media_type: str,
    data: bytes,
    actor: User,
    request_id: str | None = None,
    settings: Settings | None = None,
    store: DocumentStore | None = None,
) -> UploadOutcome:
    """Upload a new file in place of an existing one.

    The new file becomes a further version of the same document, so the old
    version, its chunks and its citations remain. Nothing is overwritten.
    """
    if previous.document_id is None:
        return UploadOutcome(previous, False, "upload.replace.no_document")

    document = db.get(Document, previous.document_id)
    language = document.language if document else "de"

    outcome = receive_upload(
        db,
        filename=filename,
        declared_media_type=declared_media_type,
        data=data,
        actor=actor,
        language=language,
        replaces=previous,
        request_id=request_id,
        settings=settings,
        store=store,
    )

    if not outcome.accepted:
        # The previous upload is untouched. A refused replacement must not take
        # a working document out of the index.
        return outcome

    # Carry the metadata across. It described the document, and the document is
    # the same one; asking for it again would invite a typo into a field a
    # citation is rendered from.
    if document is not None:
        outcome.job.state = UploadState.AWAITING_APPROVAL.value

    previous.state = UploadState.REPLACED.value
    previous.decided_by_id = actor.id
    previous.decided_at = _utcnow()

    _audit(
        db,
        action=AuditAction.DOCUMENT_REPLACED,
        job=outcome.job,
        actor=actor,
        request_id=request_id,
        detail={
            "replaces_upload_id": str(previous.id),
            "document_id": str(previous.document_id),
        },
    )
    return outcome


def delete_upload(
    db: Session,
    job: UploadJob,
    *,
    actor: User,
    reason: str,
    request_id: str | None = None,
    store: DocumentStore | None = None,
) -> list[str]:
    """Remove an upload's bytes and chunks, keeping the record of it.

    The file and everything retrievable from it go. The version row stays, with
    its status set to gone, so a citation issued before the deletion can still
    be explained rather than turning into a dangling identifier.
    """
    if not reason.strip():
        return ["upload.delete.reason_required"]
    if job.state == UploadState.DELETED.value:
        return ["upload.delete.already_deleted"]

    store = store or DocumentStore()

    if job.storage_path:
        store.delete(job.storage_path, quarantined=job.is_quarantined)
        job.storage_path = None

    removed_chunks = 0
    if job.version_id is not None:
        removed_chunks = (
            db.query(Chunk).filter(Chunk.version_id == job.version_id).delete(
                synchronize_session=False
            )
        )
        version = db.get(DocumentVersion, job.version_id)
        if version is not None:
            version.status = ContentStatus.GONE.value
            version.extracted_text = ""
            version.storage_path = None
            version.review_note = reason.strip()[:2000]
            version.reviewed_by_id = actor.id
            version.reviewed_at = _utcnow()

            document = db.get(Document, version.document_id)
            if document is not None and document.current_version_id == version.id:
                document.current_version_id = None

    job.state = UploadState.DELETED.value
    job.decided_by_id = actor.id
    job.decided_at = _utcnow()
    job.note = reason.strip()[:2000]

    _audit(
        db,
        action=AuditAction.DOCUMENT_DELETED,
        job=job,
        actor=actor,
        request_id=request_id,
        detail={"chunks_removed": removed_chunks, "reason": reason.strip()[:200]},
    )
    logger.info("upload.deleted", chunks_removed=removed_chunks)
    return []


def read_original(
    db: Session,
    job: UploadJob,
    *,
    actor: User,
    request_id: str | None = None,
    store: DocumentStore | None = None,
) -> bytes | None:
    """Return the stored bytes of an upload, recording the download.

    Every download is audited. An administrator retrieving a file is a normal
    action, and section 13 still requires it on the record: it is the one
    operation that takes content out of the system.
    """
    if not job.storage_path:
        return None

    store = store or DocumentStore()
    try:
        data = store.read(job.storage_path, quarantined=job.is_quarantined)
    except (OSError, ValueError):
        logger.error("upload.download_failed", upload_id=str(job.id))
        return None

    _audit(
        db,
        action=AuditAction.DOCUMENT_DOWNLOADED,
        job=job,
        actor=actor,
        request_id=request_id,
        detail={"bytes": len(data), "quarantined": job.is_quarantined},
    )
    return data


def find_duplicate(db: Session, content_hash: str) -> UploadJob | None:
    """Return an earlier upload of exactly these bytes, if there is one.

    Re-uploading the same file is usually somebody who was not sure the first
    attempt worked. Creating a second document for it would put two identical
    citations in front of a resident.
    """
    return db.execute(
        select(UploadJob)
        .where(
            UploadJob.content_hash == content_hash,
            UploadJob.state.notin_(
                [
                    UploadState.REFUSED.value,
                    UploadState.DELETED.value,
                    UploadState.INFECTED.value,
                ]
            ),
        )
        .order_by(UploadJob.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def get_job(db: Session, job_id: uuid.UUID) -> UploadJob | None:
    """Load one upload by identifier."""
    return db.get(UploadJob, job_id)
