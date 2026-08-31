"""Administrative routes for uploading and managing documents.

Every route names the permission it needs through a dependency, so the check
runs before the handler body. Uploading, correcting metadata, downloading the
original and deleting all need document management; approving and withdrawing
need the approval permission, because putting something in front of a resident
is a different decision from putting it in the system.

Uploads are read with a hard byte cap applied while reading rather than after,
so a client claiming a small file and sending a large one runs out of budget
instead of memory.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import SUPPORTED_LANGUAGES, get_settings
from app.assets import asset_version
from app.db.models import (
    Chunk,
    Document,
    DocumentVersion,
    PublicationState,
    UploadJob,
    UploadState,
)
from app.db.session import db_session
from app.i18n import STRINGS, negotiate_language, t
from app.observability import get_logger
from app.retrieval.indexer import update_search_vectors
from app.security.auth import CurrentUser, Permission, require
from app.uploads import pipeline
from app.uploads.pipeline import DocumentMetadata

logger = get_logger(__name__)
router = APIRouter(prefix="/admin/uploads", tags=["admin", "uploads"])
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["asset_version"] = asset_version()

# Read this much at a time. Large enough that a fifty megabyte PDF does not
# cost thousands of iterations, small enough that a single read cannot commit
# the process to an unbounded allocation.
READ_CHUNK_BYTES = 1024 * 1024

# How much of the extracted text the detail page shows. The point is to let a
# reviewer confirm the extraction worked, which the opening paragraphs settle;
# rendering a two hundred page document into one page helps nobody.
PREVIEW_CHARACTERS = 4000

# Characters permitted in the ASCII form of a Content-Disposition filename.
# Anything else is dropped rather than escaped, because the full name is sent
# separately in the RFC 5987 form that browsers prefer.
DISPOSITION_SAFE = re.compile(r"[^A-Za-z0-9._ -]")


def _language(request: Request) -> str:
    return negotiate_language(request.headers.get("Accept-Language"))


def _context(request: Request, language: str, **extra: Any) -> dict[str, Any]:
    context: dict[str, Any] = {
        "request": request,
        "language": language,
        "t": lambda key: t(key, language),
        "languages": list(SUPPORTED_LANGUAGES),
        "publication_states": [state.value for state in PublicationState],
        "upload_states": UploadState,
        "permission": Permission,
    }
    context.update(extra)
    return context


async def _read_capped(upload: UploadFile, limit: int) -> bytes | None:
    """Read an uploaded file, refusing anything over the limit.

    Returns None when the limit is exceeded. The cap is applied while reading,
    because Content-Length is supplied by the client and a chunked request does
    not carry one at all.
    """
    parts: list[bytes] = []
    total = 0
    while True:
        piece = await upload.read(READ_CHUNK_BYTES)
        if not piece:
            break
        total += len(piece)
        if total > limit:
            return None
        parts.append(piece)
    return b"".join(parts)


def _parse_date(raw: str) -> dt.datetime | None:
    """Parse a date field from the form.

    Stored at midnight UTC. A document's publication date is a calendar date,
    not an instant, and pretending otherwise would make it shift by a day
    depending on where the reader is.
    """
    value = (raw or "").strip()
    if not value:
        return None
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        return None
    return dt.datetime.combine(parsed, dt.time.min, tzinfo=dt.UTC)


def _load(db: Session, upload_id: uuid.UUID) -> UploadJob:
    job = pipeline.get_job(db, upload_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="upload_not_found")
    return job


def _redirect(job: UploadJob, *, problems: list[str] | None = None) -> RedirectResponse:
    """Send the browser back to the upload after a form post.

    Post-then-redirect, so a reload does not resubmit. Problems travel as
    message keys in the query string and are resolved against the string table
    on the way back, so nothing from the URL is ever rendered.
    """
    target = f"/admin/uploads/{job.id}"
    if problems:
        target += "?problems=" + ",".join(problems)
    return RedirectResponse(target, status_code=303)


def _messages(problems: str, language: str) -> list[str]:
    """Resolve message keys from the query string.

    Only keys that exist in the string table survive. Anything else is dropped
    rather than displayed, because t() falls back to returning the key and that
    would put text from the URL onto the page.
    """
    return [
        t(key, language)
        for key in problems.split(",")[:10]
        if key in STRINGS
    ]


def _disposition(filename: str) -> str:
    """Build a Content-Disposition header for a download.

    Two forms: a stripped ASCII one that every client understands, and the
    UTF-8 form for the full name. The ASCII form carries no quotes or
    semicolons, so a crafted filename cannot add a header parameter of its own.
    """
    ascii_name = DISPOSITION_SAFE.sub("_", filename).strip() or "document"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


# --------------------------------------------------------------------- list


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def uploads_page(
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser = Depends(require(Permission.MANAGE_DOCUMENTS)),
    message: str = "",
) -> HTMLResponse:
    """List uploads, newest first, with the form for a new one."""
    language = _language(request)
    settings = get_settings()

    jobs = list(
        db.execute(select(UploadJob).order_by(UploadJob.created_at.desc()).limit(200)).scalars()
    )
    documents = {
        document.id: document
        for document in db.execute(
            select(Document).where(
                Document.id.in_([job.document_id for job in jobs if job.document_id])
            )
        ).scalars()
    } if jobs else {}

    return templates.TemplateResponse(
        request=request,
        name="admin_uploads.html",
        context=_context(
            request,
            language,
            who=who,
            jobs=jobs,
            documents=documents,
            max_megabytes=settings.upload_max_bytes // (1024 * 1024),
            message=t(message, language) if message else "",
        ),
    )


@router.post("")
@router.post("/")
async def create_upload(
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser = Depends(require(Permission.MANAGE_DOCUMENTS)),
    file: UploadFile = File(...),
    language: str = Form("de"),
) -> Any:
    """Accept one file and run it through validation, scanning and extraction."""
    settings = get_settings()
    data = await _read_capped(file, settings.upload_max_bytes)

    if data is None:
        return RedirectResponse(
            "/admin/uploads?message=upload.refused.file_too_large", status_code=303
        )

    if language not in SUPPORTED_LANGUAGES:
        language = "de"

    duplicate = pipeline.find_duplicate(db, hashlib.sha256(data).hexdigest())
    if duplicate is not None:
        # Nothing is written. The administrator is sent to the upload that
        # already holds these bytes, which is almost always what they wanted.
        db.commit()
        return _redirect(duplicate, problems=["upload.duplicate_of_existing"])

    outcome = pipeline.receive_upload(
        db,
        filename=file.filename or "unnamed",
        declared_media_type=file.content_type or "",
        data=data,
        actor=who.user,
        language=language,
        request_id=getattr(request.state, "request_id", None),
        settings=settings,
    )
    db.commit()

    return _redirect(outcome.job, problems=[] if outcome.accepted else [outcome.message_key])


# ------------------------------------------------------------------- detail


@router.get("/{upload_id}", response_class=HTMLResponse)
def upload_detail(
    upload_id: uuid.UUID,
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser = Depends(require(Permission.MANAGE_DOCUMENTS)),
    problems: str = "",
) -> HTMLResponse:
    """Show one upload: its state, its metadata form and a text preview."""
    language = _language(request)
    job = _load(db, upload_id)

    document = db.get(Document, job.document_id) if job.document_id else None
    version = db.get(DocumentVersion, job.version_id) if job.version_id else None
    chunk_count = (
        db.query(Chunk).filter(Chunk.version_id == job.version_id).count()
        if job.version_id
        else 0
    )

    # The preview is the extracted text, which is what retrieval will actually
    # see. Showing a rendered version of the original would hide exactly the
    # extraction failures this page exists to catch.
    preview = ""
    truncated = False
    if version is not None:
        preview = version.extracted_text[:PREVIEW_CHARACTERS]
        truncated = len(version.extracted_text) > PREVIEW_CHARACTERS

    return templates.TemplateResponse(
        request=request,
        name="admin_upload_detail.html",
        context=_context(
            request,
            language,
            who=who,
            job=job,
            document=document,
            version=version,
            chunk_count=chunk_count,
            preview=preview,
            truncated=truncated,
            problems=_messages(problems, language),
        ),
    )


@router.post("/{upload_id}/metadata")
def save_metadata(
    upload_id: uuid.UUID,
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser = Depends(require(Permission.MANAGE_DOCUMENTS)),
    title: str = Form(""),
    department: str = Form(""),
    language: str = Form("de"),
    publication_state: str = Form(PublicationState.OFFICIAL.value),
    published_at: str = Form(""),
    valid_from: str = Form(""),
    valid_until: str = Form(""),
) -> Any:
    """Record or correct the metadata a citation is rendered from."""
    job = _load(db, upload_id)

    problems = pipeline.apply_metadata(
        db,
        job,
        DocumentMetadata(
            title=title,
            department=department,
            language=language,
            publication_state=publication_state,
            published_at=_parse_date(published_at),
            valid_from=_parse_date(valid_from),
            valid_until=_parse_date(valid_until),
        ),
        actor=who.user,
        request_id=getattr(request.state, "request_id", None),
    )

    if problems:
        db.rollback()
        return _redirect(job, problems=problems)

    db.commit()
    return _redirect(job)


@router.post("/{upload_id}/approve")
def approve_upload(
    upload_id: uuid.UUID,
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser = Depends(require(Permission.APPROVE_CONTENT)),
    note: str = Form(""),
) -> Any:
    """Put an uploaded document into the public index."""
    job = _load(db, upload_id)

    problems = pipeline.approve(
        db,
        job,
        actor=who.user,
        note=note,
        request_id=getattr(request.state, "request_id", None),
    )

    if problems:
        db.rollback()
        return _redirect(job, problems=problems)

    # Keyword retrieval works from this point. Embeddings are filled in by the
    # indexing run, which loads a model and does not belong in a request.
    update_search_vectors(db, version_id=job.version_id)
    db.commit()
    return _redirect(job)


@router.post("/{upload_id}/withdraw")
def withdraw_upload(
    upload_id: uuid.UUID,
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser = Depends(require(Permission.APPROVE_CONTENT)),
    reason: str = Form(""),
) -> Any:
    """Take an uploaded document out of the index, keeping the file."""
    job = _load(db, upload_id)

    problems = pipeline.withdraw(
        db,
        job,
        actor=who.user,
        reason=reason,
        request_id=getattr(request.state, "request_id", None),
    )

    if problems:
        db.rollback()
        return _redirect(job, problems=problems)

    db.commit()
    return _redirect(job)


@router.post("/{upload_id}/replace")
async def replace_upload(
    upload_id: uuid.UUID,
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser = Depends(require(Permission.MANAGE_DOCUMENTS)),
    file: UploadFile = File(...),
) -> Any:
    """Upload a newer file for the same document, keeping the old version."""
    settings = get_settings()
    job = _load(db, upload_id)

    data = await _read_capped(file, settings.upload_max_bytes)
    if data is None:
        return _redirect(job, problems=["upload.refused.file_too_large"])

    outcome = pipeline.replace(
        db,
        job,
        filename=file.filename or "unnamed",
        declared_media_type=file.content_type or "",
        data=data,
        actor=who.user,
        request_id=getattr(request.state, "request_id", None),
        settings=settings,
    )
    db.commit()

    return _redirect(outcome.job, problems=[] if outcome.accepted else [outcome.message_key])


@router.post("/{upload_id}/delete")
def delete_upload(
    upload_id: uuid.UUID,
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser = Depends(require(Permission.MANAGE_DOCUMENTS)),
    reason: str = Form(""),
) -> Any:
    """Remove an upload's bytes and chunks, keeping the record of it."""
    job = _load(db, upload_id)

    problems = pipeline.delete_upload(
        db,
        job,
        actor=who.user,
        reason=reason,
        request_id=getattr(request.state, "request_id", None),
    )

    if problems:
        db.rollback()
        return _redirect(job, problems=problems)

    db.commit()
    return _redirect(job)


@router.get("/{upload_id}/original")
def download_original(
    upload_id: uuid.UUID,
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser = Depends(require(Permission.MANAGE_DOCUMENTS)),
) -> Response:
    """Return the stored original, recording the download in the audit log."""
    job = _load(db, upload_id)

    data = pipeline.read_original(
        db, job, actor=who.user, request_id=getattr(request.state, "request_id", None)
    )
    if data is None:
        db.commit()  # the audit entry for a failed read, if one was written
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file_not_available")

    db.commit()

    return Response(
        content=data,
        # Served as a download with a generic type, never as the detected type.
        # A stored HTML file returned as text/html would run in the
        # administrator's session; an attachment with an opaque type cannot.
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": _disposition(job.original_filename),
            # Without this a browser may sniff the bytes and decide the
            # octet-stream above was really HTML.
            "X-Content-Type-Options": "nosniff",
        },
    )
