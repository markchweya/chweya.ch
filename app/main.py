"""FastAPI application assembly.

Run with:

    uvicorn app.main:app --reload

Startup order matters. Logging is configured first so that a later failure is
logged in the configured format, then settings are validated, which is where a
production deployment carrying a development password stops.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, admin_review, admin_uploads, chat, health
from app.config import Environment, get_settings
from app.middleware import (
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
    auth_redirect_handler,
    unhandled_exception_handler,
)
from app.observability import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate configuration at startup and log what the process will do."""
    configure_logging()
    settings = get_settings()

    # Nothing here logs a credential. The fields chosen are the ones an
    # operator needs in order to confirm the process came up as intended.
    logger.info(
        "application.starting",
        environment=settings.environment.value,
        apertus_model=settings.apertus_model,
        crawler_hosts=len(settings.allowed_hosts),
        transcripts_stored=settings.store_chat_transcripts,
    )

    if settings.environment is not Environment.PRODUCTION:
        logger.warning(
            "application.not_production",
            note="Development configuration. Not Swiss-hosted and not for public use.",
        )

    # Crawls run in this process, so a restart kills them mid-run. Repair any
    # row a dead process left claiming RUNNING, or it would block its source
    # forever. Best-effort: an unreachable database must not stop the process
    # from starting, because /readyz is how that condition gets reported.
    try:
        from app.db.session import get_session_factory
        from app.ingest.runner import fail_orphaned_runs

        with get_session_factory()() as db:
            fail_orphaned_runs(db)
            db.commit()
    except Exception as exc:  # noqa: BLE001 - startup must survive a down database
        logger.warning("crawl.orphan_cleanup_skipped", error=type(exc).__name__)

    yield

    logger.info("application.stopping")


def create_app() -> FastAPI:
    """Build the application. A factory so tests can build isolated instances."""
    settings = get_settings()

    app = FastAPI(
        title="Dumi",
        description=(
            "Unofficial AI information assistant for public Canton of Zug content. "
            "Not operated or endorsed by the Canton of Zug."
        ),
        version="0.1.0",
        lifespan=lifespan,
        # The interactive API documentation is a map of the attack surface.
        # Useful while developing, closed in production.
        docs_url="/docs" if settings.environment is not Environment.PRODUCTION else None,
        redoc_url=None,
        openapi_url=(
            "/openapi.json" if settings.environment is not Environment.PRODUCTION else None
        ),
    )

    # Order matters: the request identifier must exist before anything else
    # runs, so middleware added later wraps it on the way in.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)

    app.add_exception_handler(Exception, unhandled_exception_handler)
    # Browsers navigating to an admin page without a session get the
    # sign-in page; API callers keep their status codes.
    from starlette.exceptions import HTTPException as StarletteHTTPException

    app.add_exception_handler(StarletteHTTPException, auth_redirect_handler)

    # The Dumi design system is served unchanged from shared/brand. It is not
    # copied into the application: one canonical copy means the interface and
    # the brand specimen can never drift apart.
    app.mount("/brand", StaticFiles(directory="shared/brand"), name="brand")
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        """Browsers request this path directly, before parsing any markup."""
        return FileResponse("shared/brand/favicon/favicon.ico")

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(admin.router)
    app.include_router(admin_uploads.router)
    app.include_router(admin_review.router)

    return app


app = create_app()
