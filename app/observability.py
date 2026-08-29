"""Structured logging and request correlation.

Logs are JSON in deployment so they can be shipped and queried, and
human-readable when developing.

Two rules the whole application depends on:

* A request identifier is attached to every log line and returned in the
  X-Request-ID response header, so a user reporting a problem can quote an
  identifier that finds the exact request without anyone storing their
  question.
* Question text and retrieved source content never enter a log line or a
  metric label. Section 18 of the brief requires it, and it is also the only
  way an operational log stays free of personal data.
"""

from __future__ import annotations

import contextvars
import logging
import sys
import uuid
from typing import Any

import structlog

from app.config import get_settings

# Carries the current request identifier across await points without threading
# it through every function signature.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


def new_request_id() -> str:
    """Return a short, unique request identifier."""
    return uuid.uuid4().hex[:16]


def _add_request_id(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Attach the current request identifier to every event."""
    rid = request_id_var.get()
    if rid:
        event_dict["request_id"] = rid
    return event_dict


# Keys that must never be logged, whatever a call site passes. This mirrors the
# audit log's filter; the two exist separately because one protects the
# operational log and the other the audit record, and they are read by
# different people for different reasons.
FORBIDDEN_LOG_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "authorization",
        "cookie",
        "credential",
        # Content that would turn an operational log into a record of what
        # residents asked.
        "question",
        "query_text",
        "answer",
        "passage",
        "chunk_text",
    }
)


def _drop_forbidden_keys(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive and personal keys before an event is rendered."""
    for key in list(event_dict):
        if key.lower() in FORBIDDEN_LOG_KEYS:
            event_dict[key] = "[dropped]"
    return event_dict


def configure_logging() -> None:
    """Configure structlog and the standard library logger. Idempotent."""
    settings = get_settings()

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level),
        force=True,
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_request_id,
        _drop_forbidden_keys,
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.log_format == "json":
        # format_exc_info turns an exception into a string field rather than
        # letting a traceback escape into an HTTP response.
        processors += [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
    else:
        processors += [structlog.dev.ConsoleRenderer()]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
