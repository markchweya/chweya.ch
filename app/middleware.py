"""HTTP middleware: request identity, security headers, safe error handling."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import Environment, get_settings
from app.observability import get_logger, new_request_id, request_id_var

logger = get_logger(__name__)

Handler = Callable[[Request], Awaitable[Response]]


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assign every request an identifier and echo it back.

    An inbound X-Request-ID is accepted only when it looks like an identifier
    we would have issued. Reflecting arbitrary client input into a response
    header, and into every log line, would be a log injection and header
    injection vector.
    """

    MAX_LENGTH = 64

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        supplied = request.headers.get("X-Request-ID", "")
        if supplied and len(supplied) <= self.MAX_LENGTH and supplied.isalnum():
            request_id = supplied
        else:
            request_id = new_request_id()

        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)

        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply security headers to every response.

    The Content-Security-Policy is strict because the application renders
    content extracted from crawled pages and uploaded PDFs. If cleaning ever
    lets markup through, the policy is the layer that stops it executing.

    There is no 'unsafe-inline' for scripts. The templates load their
    JavaScript from same-origin files, so inline script is not needed, and
    allowing it would defeat most of the value of having a policy.
    """

    def __init__(self, app, *, csp: str | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._csp = csp or self._default_csp()

    @staticmethod
    def _default_csp() -> str:
        return "; ".join(
            [
                "default-src 'self'",
                "script-src 'self'",
                # Style needs 'unsafe-inline' because the Dumi mark sets
                # per-instance size through a style attribute. Scripts do not,
                # and that is the distinction that matters for XSS.
                "style-src 'self' 'unsafe-inline'",
                "img-src 'self' data:",
                "font-src 'self'",
                # No third-party endpoints. The application talks only to its
                # own origin from the browser.
                "connect-src 'self'",
                "form-action 'self'",
                "frame-ancestors 'none'",
                "base-uri 'none'",
                "object-src 'none'",
            ]
        )

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        response = await call_next(request)
        settings = get_settings()

        response.headers.setdefault("Content-Security-Policy", self._csp)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # Disable device APIs the application never uses, so a compromised
        # page cannot reach them either.
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=(), payment=()"
        )
        # Only over HTTPS. Sending HSTS over plain HTTP is ignored by browsers
        # and would wrongly suggest the development server is secure.
        if settings.environment is Environment.PRODUCTION:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a safe error body and log the detail server-side.

    The response carries the request identifier and nothing else. Section 13
    forbids exposing stack traces or internal detail, and a traceback rendered
    to a user is both an information disclosure and an unpleasant experience.
    """
    logger.exception("unhandled_exception", path=request.url.path, method=request.method)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "Something went wrong. Quote the request id when reporting this.",
            "request_id": request_id_var.get(),
        },
    )
