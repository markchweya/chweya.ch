"""The language model interface the rest of the application programs against.

Only this package knows how Apertus is served. Everything else depends on the
:class:`LLMProvider` protocol, so replacing vLLM with Ollama, or moving from a
developer desktop to Swiss-hosted infrastructure, does not touch a call site.

The protocol is deliberately small. It offers text generation and a health
check, and nothing else. In particular it exposes no tool calling: section 13
of the brief requires that retrieved content cannot cause the model to select
a tool, modify configuration or start a network call, and the simplest way to
guarantee that is for the model to have no tools to reach for.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Role(StrEnum):
    """Who authored a message in the conversation sent to the model.

    ``SYSTEM`` carries instructions the operator controls. ``USER`` carries the
    question and the retrieved evidence, both of which are untrusted. Nothing
    untrusted is ever given the system role.
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class ChatMessage:
    """One message in the conversation."""

    role: Role
    content: str


@dataclass(frozen=True)
class GenerationRequest:
    """A request for the model to produce an answer.

    Every parameter defaults to None so the provider falls back to configured
    settings. A caller overrides only what it genuinely needs to change.
    """

    messages: Sequence[ChatMessage]
    max_output_tokens: int | None = None
    temperature: float | None = None
    # Sequences that end generation early. Used to stop the model continuing
    # past the answer into invented follow-up questions.
    stop: Sequence[str] | None = None


@dataclass(frozen=True)
class GenerationChunk:
    """One streamed fragment of a response."""

    text: str
    # True on the final chunk, which carries no new text.
    done: bool = False


@dataclass(frozen=True)
class GenerationResult:
    """A complete response."""

    text: str
    model: str
    # None when the server does not report usage. Never invented.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    # Set when the server stopped for a reason worth surfacing, such as
    # reaching the output token limit, which means the answer is truncated.
    finish_reason: str | None = None

    @property
    def was_truncated(self) -> bool:
        """True when generation stopped at the token limit rather than finishing.

        A truncated answer must not be presented as complete, because a cut-off
        list of requirements reads as an exhaustive one.
        """
        return self.finish_reason == "length"


class HealthState(StrEnum):
    """Whether the model service can serve requests."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class LLMHealth:
    """Result of a provider health check."""

    state: HealthState
    detail: str = ""
    latency_ms: float | None = None
    models: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.state is HealthState.HEALTHY


# --------------------------------------------------------------------------
# Errors
#
# The application must fail closed. When the model cannot be reached, the
# correct behaviour is to tell the user the assistant is unavailable, never to
# answer from model memory or from a cached guess.
# --------------------------------------------------------------------------


class LLMError(Exception):
    """Base class for every failure raised by a provider."""


class LLMUnavailable(LLMError):
    """The model service could not be reached, or refused the request.

    Covers connection failures, timeouts, and server errors that survived the
    configured retries.
    """


class LLMTimeout(LLMUnavailable):
    """The model service did not respond within the configured timeout."""


class LLMBadResponse(LLMError):
    """The service responded, but not in the expected shape.

    Treated as a failure rather than parsed leniently. A response that does not
    match the contract may be a proxy error page, and rendering that to a user
    as an answer would be worse than reporting unavailability.
    """


class LLMRequestTooLarge(LLMError):
    """The assembled prompt exceeds the configured context window.

    Raised before contacting the service. The caller is expected to drop
    evidence passages and retry, rather than let the server truncate silently
    from whichever end it prefers.
    """


@runtime_checkable
class LLMProvider(Protocol):
    """What the application requires of a language model service."""

    @property
    def model_name(self) -> str:
        """The model identifier this provider will use."""
        ...

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Produce a complete answer.

        Raises :class:`LLMUnavailable` when the service cannot be reached, and
        :class:`LLMRequestTooLarge` when the prompt does not fit the context
        window.
        """
        ...

    def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        """Produce an answer incrementally.

        Implementations must not swallow a mid-stream failure. A stream that
        stops early has to raise, so the interface can tell the user the answer
        is incomplete instead of presenting a truncated one as finished.
        """
        ...

    async def health(self) -> LLMHealth:
        """Report whether the service is reachable. Never raises."""
        ...

    def estimate_tokens(self, text: str) -> int:
        """Approximate the token count of ``text``.

        Used to keep the assembled prompt inside the context window. An
        approximation is acceptable, but it must never underestimate badly
        enough to let an oversized prompt through.
        """
        ...
