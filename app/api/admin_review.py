"""The contradiction review interface.

Every route requires the contradiction-resolution permission, which the
reviewer role holds and the auditor deliberately does not. The routes stay
thin: what a resolution means lives in app.review.resolution, where it can be
tested without HTTP.

The detail page shows both passages in full, with their documents, dates and
extracted values. The reviewer is deciding which official statement is
current, and a decision made from a truncated excerpt is a guess wearing a
uniform.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AuditAction, ContradictionFinding, ReviewState
from app.db.session import db_session
from app.i18n import STRINGS, negotiate_language, t
from app.ingest.contradictions import detect
from app.observability import get_logger
from app.review import resolution
from app.security.audit import record
from app.security.auth import CurrentUser, Permission, require

logger = get_logger(__name__)
router = APIRouter(prefix="/admin/review", tags=["admin", "review"])
templates = Jinja2Templates(directory="app/templates")


def _language(request: Request) -> str:
    return negotiate_language(request.headers.get("Accept-Language"))


def _context(request: Request, language: str, **extra: Any) -> dict[str, Any]:
    context: dict[str, Any] = {
        "request": request,
        "language": language,
        "t": lambda key: t(key, language),
        "permission": Permission,
        "review_states": ReviewState,
        "resolutions": resolution.RESOLUTIONS,
    }
    context.update(extra)
    return context


def _messages(problems: str, language: str) -> list[str]:
    """Resolve message keys from the query string.

    Only keys present in the string table are rendered, because t() falls
    back to returning the key and that would put text from the URL onto the
    page.
    """
    return [t(key, language) for key in problems.split(",")[:10] if key in STRINGS]


def _load(db: Session, finding_id: uuid.UUID) -> ContradictionFinding:
    finding = db.get(ContradictionFinding, finding_id)
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="finding_not_found")
    return finding


def _redirect(finding: ContradictionFinding, *, problems: list[str] | None = None) -> RedirectResponse:
    target = f"/admin/review/{finding.id}"
    if problems:
        target += "?problems=" + ",".join(problems)
    return RedirectResponse(target, status_code=303)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def review_queue(
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser = Depends(require(Permission.RESOLVE_CONTRADICTIONS)),
    message: str = "",
) -> HTMLResponse:
    """The queue, most urgent first, with the recent decisions below it."""
    language = _language(request)

    counts = dict(
        db.execute(
            select(ContradictionFinding.state, func.count()).group_by(
                ContradictionFinding.state
            )
        ).all()
    )

    return templates.TemplateResponse(
        request=request,
        name="admin_review.html",
        context=_context(
            request,
            language,
            who=who,
            queue=resolution.open_queue(db),
            decided=resolution.recent_decisions(db),
            counts=counts,
            message=t(message, language) if message and message in STRINGS else "",
        ),
    )


@router.post("/detect")
def run_detection(
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser = Depends(require(Permission.RESOLVE_CONTRADICTIONS)),
) -> RedirectResponse:
    """Compare the approved corpus and file new findings.

    Filing a finding decides nothing, so a reviewer may trigger it. The run
    is audited because it writes rows a person will spend attention on.
    """
    findings = detect(db)
    record(
        db,
        action=AuditAction.CONTRADICTION_DETECTION_RUN,
        actor_user_id=who.user.id,
        actor_label=f"user:{who.user.id}",
        detail={"findings_filed": len(findings)},
    )
    db.commit()
    logger.info("review.detection_run", findings=len(findings))
    return RedirectResponse("/admin/review?message=review.detection_completed", status_code=303)


@router.get("/{finding_id}", response_class=HTMLResponse)
def finding_detail(
    finding_id: uuid.UUID,
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser = Depends(require(Permission.RESOLVE_CONTRADICTIONS)),
    problems: str = "",
) -> HTMLResponse:
    """One finding: both passages in full, and the decision form."""
    language = _language(request)
    finding = _load(db, finding_id)
    context = resolution.load_context(db, finding)

    return templates.TemplateResponse(
        request=request,
        name="admin_review_detail.html",
        context=_context(
            request,
            language,
            who=who,
            finding=finding,
            ctx=context,
            actionable=ReviewState(finding.state) in resolution.ACTIONABLE_STATES,
            problems=_messages(problems, language),
        ),
    )


@router.post("/{finding_id}/claim")
def claim_finding(
    finding_id: uuid.UUID,
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser = Depends(require(Permission.RESOLVE_CONTRADICTIONS)),
) -> RedirectResponse:
    """Mark a finding as being looked at."""
    finding = _load(db, finding_id)
    problems = resolution.claim(
        db, finding, actor=who.user, request_id=getattr(request.state, "request_id", None)
    )
    if problems:
        db.rollback()
        return _redirect(finding, problems=problems)
    db.commit()
    return _redirect(finding)


@router.post("/{finding_id}/resolve")
def resolve_finding(
    finding_id: uuid.UUID,
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser = Depends(require(Permission.RESOLVE_CONTRADICTIONS)),
    outcome: str = Form(""),
    note: str = Form(""),
) -> RedirectResponse:
    """Apply the reviewer's decision."""
    finding = _load(db, finding_id)
    problems = resolution.resolve(
        db,
        finding,
        outcome,
        actor=who.user,
        note=note,
        request_id=getattr(request.state, "request_id", None),
    )
    if problems:
        db.rollback()
        return _redirect(finding, problems=problems)
    db.commit()
    return _redirect(finding)
