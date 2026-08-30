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
        # Also on request.state. The unhandled-exception handler runs in the
        # outermost error middleware, after the finally below has reset the
        # contextvar, so the contextvar alone would hand it an empty string.
        request.state.request_id = request_id
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
    # Read from request.state, not the contextvar: this handler runs in the
    # outermost error middleware, after RequestIdMiddleware has reset the
    # contextvar, which is how the body ended up telling people to quote an
    # empty string.
    request_id = getattr(request.state, "request_id", "") or request_id_var.get()
    logger.exception(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "Something went wrong. Quote the request id when reporting this.",
            "request_id": request_id,
        },
        # The header carries it too, matching every non-error response.
        headers={"X-Request-ID": request_id} if request_id else None,
    )


async def auth_redirect_handler(request: Request, exc: Exception) -> Response:
    """Send a browser to the sign-in page instead of showing it raw JSON.

    The authentication dependencies raise HTTP errors, which is right for a
    fetch call: the chat script and any API client get a status code they can
    act on. A person navigating with a browser gets {"detail":
    "login_required"} on a black page, which tells them nothing. The Accept
    header distinguishes the two: a navigation asks for text/html, a fetch
    does not.
    """
    from fastapi.exception_handlers import http_exception_handler
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from starlette.responses import RedirectResponse

    # Registered for StarletteHTTPException only; anything else goes to the
    # default handler untouched.
    if isinstance(exc, StarletteHTTPException):
        wants_html = "text/html" in (request.headers.get("Accept") or "")
        if wants_html and exc.status_code == 401 and exc.detail == "login_required":
            return RedirectResponse("/admin/login", status_code=303)
        if (
            wants_html
            and exc.status_code == 403
            and exc.detail == "password_change_required"
        ):
            # The account exists but must set its own password first; the
            # page for that is the only one it may reach.
            return RedirectResponse("/admin/password", status_code=303)

    return await http_exception_handler(request, exc)  # type: ignore[arg-type]
