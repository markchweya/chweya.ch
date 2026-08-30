"""The public chat surface.

Two ways in, deliberately:

* ``POST /ask`` with an HTML accept header renders the whole page. The form
  works with JavaScript disabled, which matters for a public service and makes
  the accessibility target realistic.
* ``POST /ask`` with a JSON accept header returns the answer as data, which is
  what the progressive enhancement in chat.js uses.

Both go through exactly the same answering path. There is no code path where
one surface can answer something the other cannot.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.ratelimit import FixedWindowLimiter, client_key
from app.config import get_settings
from app.db.session import db_session
from app.i18n import SUPPORTED_LANGUAGES, negotiate_language, normalise_language, t
from app.llm.apertus import ApertusProvider
from app.llm.base import LLMProvider
from app.observability import get_logger
from app.retrieval.answer import Answer, answer_question
from app.retrieval.embeddings import (
    EmbeddingProvider,
    UnavailableEmbeddings,
    build_embedding_provider,
)

logger = get_logger(__name__)
router = APIRouter(tags=["chat"])

templates = Jinja2Templates(directory="app/templates")

LANGUAGE_LABELS = [("de", "DE"), ("en", "EN"), ("fr", "FR"), ("it", "IT")]


@dataclass
class ViewMessage:
    """One transcript entry, shaped for the template."""

    role: str
    text: str
    confidence: str = ""
    citations: list = field(default_factory=list)
    notices: list = field(default_factory=list)


def _language_for(request: Request, explicit: str | None) -> str:
    """Choose the interface language.

    An explicit choice wins, then the Accept-Language header. The choice is
    not stored: the public chat requires no account and sets no cookie it does
    not need, which is the data minimisation rule in section 14.
    """
    if explicit:
        return normalise_language(explicit)
    return negotiate_language(request.headers.get("Accept-Language"))


def _template_context(request: Request, language: str, messages: list[ViewMessage]) -> dict[str, Any]:
    return {
        "request": request,
        "language": language,
        "languages": LANGUAGE_LABELS,
        "messages": messages,
        # Bound so templates call t('key') without threading the language
        # through every call site.
        "t": lambda key: t(key, language),
    }


@router.get("/", response_class=HTMLResponse)
def chat_page(request: Request, lang: str | None = None) -> HTMLResponse:
    """Render the empty chat surface."""
    language = _language_for(request, lang)
    return templates.TemplateResponse(
        request=request,
        name="chat.html",
        context=_template_context(request, language, []),
    )


def _answer_payload(answer: Answer, language: str) -> dict[str, Any]:
    """Shape an answer for the JSON surface."""
    return {
        "text": answer.text,
        "language": answer.language,
        "confidence": answer.confidence.value,
        "is_refusal": answer.is_refusal,
        "citations": [
            {
                "number": citation.number,
                "title": citation.title,
                "url": citation.url,
                "locator": citation.locator,
                "language": citation.language,
                "cross_language": citation.is_cross_language,
                "last_checked": (
                    citation.last_checked.strftime("%d.%m.%Y")
                    if citation.last_checked
                    else None
                ),
            }
            for citation in answer.citations
        ],
        "notices": [{"key": key, "text": t(key, language)} for key in answer.notices],
        "labels": {
            "sources": t("answer.sources", language),
            "source_language": t("answer.source_language_note", language),
            "last_checked": t("answer.last_checked", language),
        },
        # Never returned to the client: reasons name internal policy signals
        # and would leak how retrieval is scored. They go to the log instead.
    }


def get_llm_provider() -> LLMProvider:
    """Return the language model provider for one request.

    A FastAPI dependency rather than a direct construction, so tests can
    override it with app.dependency_overrides and exercise the real endpoint
    without a running model. Constructing the provider inside the handler
    would make the whole surface untestable here, which is how an endpoint
    ends up verified only by hand.
    """
    return ApertusProvider(get_settings())


# The provider is cached per configuration for the life of the process. A
# sentence-transformers model is hundreds of megabytes; constructing it per
# request would load it per request. A construction failure is also cached,
# briefly: loading can mean downloading, a host with a cold cache behind a
# restricted network cannot, and paying the download timeout on every single
# question would turn one unavailable model into a slow site.
_provider_cache: dict[str, EmbeddingProvider] = {}
_provider_failures: dict[str, float] = {}
PROVIDER_RETRY_SECONDS = 300.0


def get_embedding_provider() -> EmbeddingProvider:
    """Return the embedding provider for one request.

    A provider that cannot be constructed becomes :class:`UnavailableEmbeddings`
    rather than an exception. Retrieval treats its failing embed methods as a
    degraded search and answers from the keyword arm, which is the honest
    behaviour: the site stays up, and the answer says less rather than nothing.
    """
    settings = get_settings()
    key = f"{settings.embedding_model}:{settings.embedding_dimensions}"

    cached = _provider_cache.get(key)
    if cached is not None:
        if not isinstance(cached, UnavailableEmbeddings):
            return cached
        # A cached failure is retried once its hold expires, so a transient
        # network problem does not disable semantic search until a restart.
        if time.monotonic() - _provider_failures.get(key, 0.0) < PROVIDER_RETRY_SECONDS:
            return cached
        del _provider_cache[key]

    try:
        provider: EmbeddingProvider = build_embedding_provider(settings)
    except Exception as exc:  # noqa: BLE001 - any load failure degrades, none aborts
        logger.warning(
            "embeddings.load_failed",
            model=settings.embedding_model,
            error=type(exc).__name__,
            retry_in_seconds=int(PROVIDER_RETRY_SECONDS),
        )
        provider = UnavailableEmbeddings(
            reason=type(exc).__name__, dimensions=settings.embedding_dimensions
        )
        _provider_failures[key] = time.monotonic()

    _provider_cache[key] = provider
    return provider


async def _produce_answer(
    session: Session,
    question: str,
    language: str,
    llm: LLMProvider,
    embedder: EmbeddingProvider,
) -> Answer:
    """Run the answering pipeline."""
    settings = get_settings()
    try:
        return await answer_question(
            session,
            embedder,
            llm,
            question,
            language=language,
            max_context_tokens=settings.apertus_max_context_tokens,
        )
    finally:
        close = getattr(llm, "aclose", None)
        if close is not None:
            await close()


@router.post("/ask")
async def ask(
    request: Request,
    session: Session = Depends(db_session),
    question: str = Form(default=""),
    lang: str = Form(default=""),
    llm: LLMProvider = Depends(get_llm_provider),
    embedder: EmbeddingProvider = Depends(get_embedding_provider),
) -> Any:
    """Answer a question, as HTML or JSON depending on what was asked for."""
    settings = get_settings()
    wants_json = "application/json" in (request.headers.get("Accept") or "")

    # A JSON request carries its body as JSON, not as form fields.
    if wants_json:
        try:
            body = await request.json()
        except ValueError:
            body = {}
        question = str(body.get("question", ""))
        lang = str(body.get("lang", ""))

    language = _language_for(request, lang or None)

    limiter = _limiter_for(settings.rate_limit_chat_per_minute)
    decision = limiter.check(client_key(request.client.host if request.client else None))
    if not decision.allowed:
        message = t("error.too_many_requests", language)
        logger.info("chat.rate_limited")
        if wants_json:
            return JSONResponse(
                {"text": message, "confidence": "insufficient", "is_refusal": True},
                status_code=429,
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
        return templates.TemplateResponse(
            request=request,
            name="chat.html",
            context=_template_context(
                request, language, [ViewMessage(role="bot", text=message)]
            ),
            status_code=429,
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )

    answer = await _produce_answer(session, question.strip(), language, llm, embedder)

    # The question text is never logged. Section 18 forbids it, and an
    # operational log should not become a record of what residents asked.
    logger.info(
        "chat.answered",
        confidence=answer.confidence.value,
        citations=len(answer.citations),
        refusal=answer.is_refusal,
        language=answer.language,
        degraded=answer.degraded_reason or "no",
    )

    if wants_json:
        return JSONResponse(_answer_payload(answer, language))

    messages = [
        ViewMessage(role="user", text=question.strip()),
        ViewMessage(
            role="bot",
            text=answer.text,
            confidence=answer.confidence.value,
            citations=answer.citations,
            notices=answer.notices,
        ),
    ]
    return templates.TemplateResponse(
        request=request,
        name="chat.html",
        context=_template_context(request, language, messages),
    )


_LIMITERS: dict[int, Any] = {}


def _limiter_for(limit: int):  # type: ignore[no-untyped-def]
    """Return the process-wide limiter for a given rate."""
    if limit not in _LIMITERS:
        _LIMITERS[limit] = FixedWindowLimiter(limit)
    return _LIMITERS[limit]


# Re-exported so the template context and tests can see what is supported.
__all__ = ["SUPPORTED_LANGUAGES", "router"]
