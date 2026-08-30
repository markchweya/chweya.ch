"""Administrative routes.

Every route here requires authentication, and every privileged one names the
permission it needs through a dependency, so the check runs before the handler
body and cannot be forgotten.

The one route reachable while an account still has ``must_change_password``
set is the password change itself. That is what makes the bootstrap credential
usable exactly once.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    AuditAction,
    Chunk,
    ContentStatus,
    CrawlRun,
    Document,
    DocumentVersion,
    Source,
    User,
)
from app.db.session import db_session
from app.i18n import negotiate_language, t
from app.observability import get_logger
from app.security.audit import record
from app.security.auth import (
    CurrentUser,
    Permission,
    authenticate,
    current_user,
    require,
    require_login,
    require_login_allowing_password_change,
)
from app.security.passwords import hash_password, validate_password
from app.security.sessions import create_session, revoke_all_for_user, revoke_session

logger = get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


def _language(request: Request) -> str:
    return negotiate_language(request.headers.get("Accept-Language"))


def _context(request: Request, language: str, **extra: Any) -> dict[str, Any]:
    context = {
        "request": request,
        "language": language,
        "languages": [("de", "DE"), ("en", "EN"), ("fr", "FR"), ("it", "IT")],
        "t": lambda key: t(key, language),
        # Exposed so a template can ask what the user may do. The template is
        # never the enforcement point; the dependency already refused anyone
        # without the permission. This only decides whether a link is shown.
        "permission": Permission,
    }
    context.update(extra)
    return context


def _set_session_cookie(response: Response, token: str) -> None:
    """Attach the session cookie with the settings section 13 requires."""
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        # HttpOnly: script cannot read it, so an XSS does not hand over a
        # session. Secure: never sent over plain HTTP. SameSite: not sent on
        # cross-site requests, which is the CSRF defence for this cookie.
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        max_age=settings.session_absolute_timeout_hours * 3600,
        path="/",
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = "") -> HTMLResponse:
    language = _language(request)
    return templates.TemplateResponse(
        request=request,
        name="admin_login.html",
        context=_context(request, language, error=error),
    )


@router.post("/login")
def login(
    request: Request,
    response: Response,
    db: Session = Depends(db_session),
    email: str = Form(...),
    password: str = Form(...),
) -> Any:
    language = _language(request)
    result = authenticate(
        db,
        email,
        password,
        client_host=request.client.host if request.client else None,
    )

    if not result.ok or result.user is None:
        db.commit()  # the failed attempt and its audit entry
        return templates.TemplateResponse(
            request=request,
            name="admin_login.html",
            context=_context(request, language, error=t(result.error, language)),
            status_code=401,
        )

    _, token = create_session(
        db,
        result.user,
        client_host=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    db.commit()

    target = "/admin/password" if result.user.must_change_password else "/admin"
    redirect = RedirectResponse(target, status_code=303)
    _set_session_cookie(redirect, token)
    return redirect


@router.post("/logout")
def logout(
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser | None = Depends(current_user),
) -> RedirectResponse:
    if who is not None:
        revoke_session(db, who.session.id)
        record(
            db,
            action=AuditAction.LOGOUT,
            actor_user_id=who.user.id,
            actor_label=f"user:{who.user.id}",
        )
        db.commit()

    redirect = RedirectResponse("/admin/login", status_code=303)
    redirect.delete_cookie(get_settings().session_cookie_name, path="/")
    return redirect


@router.get("/password", response_class=HTMLResponse)
def password_page(
    request: Request,
    who: CurrentUser = Depends(require_login_allowing_password_change),
    error: str = "",
) -> HTMLResponse:
    language = _language(request)
    return templates.TemplateResponse(
        request=request,
        name="admin_password.html",
        context=_context(
            request, language, error=error, forced=who.user.must_change_password
        ),
    )


@router.post("/password")
def change_password(
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser = Depends(require_login_allowing_password_change),
    current: str = Form(...),
    new_password: str = Form(...),
    repeat: str = Form(...),
) -> Any:
    """Change the signed-in user's password.

    The current password is required even for a forced change, so a session
    left open on an unattended machine cannot be used to take the account over.
    """
    from app.security.passwords import verify_password

    language = _language(request)

    def fail(message: str, status_code: int = 400) -> Any:
        return templates.TemplateResponse(
            request=request,
            name="admin_password.html",
            context=_context(
                request, language, error=message, forced=who.user.must_change_password
            ),
            status_code=status_code,
        )

    valid, _ = verify_password(who.user.password_hash, current)
    if not valid:
        return fail(t("auth.invalid_credentials", language), 401)

    if new_password != repeat:
        return fail(t("auth.passwords_differ", language))

    check = validate_password(new_password, email=who.user.email)
    if not check.ok:
        return fail(" ".join(t(problem, language) for problem in check.problems))

    who.user.password_hash = hash_password(new_password)
    who.user.must_change_password = False
    who.user.password_changed_at = func.now()

    # Every other session ends. A password change that leaves old sessions
    # alive does not actually lock anyone out.
    revoked = revoke_all_for_user(db, who.user.id, reason="password_changed")
    # Except this one, which the person is actively using.
    who.session.revoked_at = None
    who.session.revoked_reason = None

    record(
        db,
        action=AuditAction.PASSWORD_CHANGED,
        actor_user_id=who.user.id,
        actor_label=f"user:{who.user.id}",
        detail={"other_sessions_revoked": max(0, revoked - 1)},
    )
    db.commit()
    return RedirectResponse("/admin", status_code=303)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser = Depends(require_login),
) -> HTMLResponse:
    """System overview.

    Every number here is a live count. Nothing is a placeholder, because a
    dashboard showing invented figures is worse than one showing none.
    """
    language = _language(request)

    def count(model, *conditions) -> int:  # type: ignore[no-untyped-def]
        query = select(func.count()).select_from(model)
        for condition in conditions:
            query = query.where(condition)
        return int(db.execute(query).scalar_one())

    latest_run = db.execute(
        select(CrawlRun).order_by(CrawlRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()

    languages = db.execute(
        select(Document.language, func.count()).group_by(Document.language)
    ).all()

    stats = {
        "sources": count(Source),
        "sources_paused": count(Source, Source.is_paused.is_(True)),
        "documents": count(Document),
        "versions": count(DocumentVersion),
        "chunks": count(Chunk),
        "chunks_embedded": count(Chunk, Chunk.embedding.is_not(None)),
        "awaiting_review": count(
            DocumentVersion, DocumentVersion.status == ContentStatus.AWAITING_REVIEW.value
        ),
        "approved": count(
            DocumentVersion, DocumentVersion.status == ContentStatus.APPROVED.value
        ),
        "users": count(User, User.is_active.is_(True)),
        "languages": dict(languages),
    }

    return templates.TemplateResponse(
        request=request,
        name="admin_dashboard.html",
        context=_context(
            request, language, who=who, stats=stats, latest_run=latest_run
        ),
    )


@router.get("/sources", response_class=HTMLResponse)
def sources_page(
    request: Request,
    db: Session = Depends(db_session),
    who: CurrentUser = Depends(require(Permission.MANAGE_SOURCES)),
) -> HTMLResponse:
    """List configured sources. Requires the source management permission."""
    language = _language(request)
    sources = list(db.execute(select(Source).order_by(Source.name)).scalars())
    return templates.TemplateResponse(
        request=request,
        name="admin_sources.html",
        context=_context(request, language, who=who, sources=sources),
    )
