"""Apertus provider, speaking the OpenAI-compatible chat completions API.

Apertus is the Swiss open language model. It is normally served through vLLM
or Ollama, and both expose an OpenAI-compatible ``/v1/chat/completions``
endpoint. Targeting that wire format rather than a particular serving
framework means the developer's desktop setup and a Swiss-hosted production
deployment use the same code path with a different base URL.

Nothing about Swiss hosting is implied by this module. Where the endpoint runs
is a deployment decision; see docs/deployment.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Sequence

import httpx

from app.config import Settings, get_settings
from app.llm.base import (
    ChatMessage,
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    HealthState,
    LLMBadResponse,
    LLMHealth,
    LLMRequestTooLarge,
    LLMTimeout,
    LLMUnavailable,
)

logger = logging.getLogger(__name__)

# Server errors and rate limiting are worth retrying. A 4xx other than 429 is
# a request the server will refuse identically next time, so retrying it only
# adds latency before the same failure.
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})

# Rough characters-per-token ratio used by estimate_tokens. Deliberately
# pessimistic: German compounds and French accented text tokenise worse than
# English, and an underestimate would let an oversized prompt through, which is
# the failure this guard exists to prevent.
CHARS_PER_TOKEN = 3.0


class ApertusProvider:
    """Talks to an Apertus deployment over the OpenAI-compatible API.

    One instance is intended per process. It owns an httpx client with
    connection pooling, so it must be closed on shutdown; see
    :meth:`aclose`.
    """

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self._settings = settings or get_settings()
        # Injectable so tests can supply a transport without patching globals.
        self._client = client or httpx.AsyncClient(
            base_url=self._settings.apertus_base_url,
            timeout=httpx.Timeout(
                self._settings.apertus_timeout_seconds,
                connect=self._settings.apertus_connect_timeout_seconds,
            ),
            headers=self._auth_headers(),
            # The model server is trusted infrastructure, but a redirect chain
            # would still be an unexpected way to reach a different host.
            follow_redirects=False,
        )

    def _auth_headers(self) -> dict[str, str]:
        """Return request headers, including the bearer token when configured."""
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        key = self._settings.apertus_api_key
        if key is not None and key.get_secret_value():
            headers["Authorization"] = f"Bearer {key.get_secret_value()}"
        return headers

    @property
    def model_name(self) -> str:
        return self._settings.apertus_model

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ------------------------------------------------------------------ util

    def estimate_tokens(self, text: str) -> int:
        """Approximate a token count without loading a tokeniser.

        Rounds up, and uses a low characters-per-token ratio, so the estimate
        errs towards saying a prompt is too large. Being wrong in that
        direction costs a dropped evidence passage. Being wrong in the other
        direction means the server truncates the prompt from an end we do not
        control, which can silently remove the system instruction.
        """
        return int(len(text) / CHARS_PER_TOKEN) + 1

    def _assert_fits_context(self, messages: Sequence[ChatMessage], max_output: int) -> None:
        """Raise if the prompt plus the reserved output does not fit."""
        prompt_tokens = sum(self.estimate_tokens(m.content) for m in messages)
        # Four tokens per message covers the role and separator overhead that
        # chat formats add around each turn.
        prompt_tokens += 4 * len(messages)
        budget = self._settings.apertus_max_context_tokens
        if prompt_tokens + max_output > budget:
            raise LLMRequestTooLarge(
                f"Prompt is about {prompt_tokens} tokens and {max_output} are reserved for the "
                f"answer, which exceeds the {budget} token context window. "
                "Drop evidence passages and retry."
            )

    def _payload(self, request: GenerationRequest, *, stream: bool) -> dict[str, object]:
        """Build the chat completions request body."""
        settings = self._settings
        max_output = request.max_output_tokens or settings.apertus_max_output_tokens
        self._assert_fits_context(request.messages, max_output)

        payload: dict[str, object] = {
            "model": settings.apertus_model,
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
            "max_tokens": max_output,
            "temperature": (
                request.temperature if request.temperature is not None else settings.apertus_temperature
            ),
            "stream": stream,
        }
        if request.stop:
            payload["stop"] = list(request.stop)
        return payload

    async def _post_with_retries(self, payload: dict[str, object]) -> httpx.Response:
        """POST the payload, retrying transient failures with backoff."""
        attempts = self._settings.apertus_max_retries + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                response = await self._client.post("/chat/completions", json=payload)
            except httpx.TimeoutException as exc:
                last_error = LLMTimeout(
                    f"Apertus did not respond within {self._settings.apertus_timeout_seconds}s"
                )
                logger.warning("apertus.timeout attempt=%d/%d", attempt + 1, attempts)
                _ = exc
            except httpx.HTTPError as exc:
                # The message deliberately omits the exception text, which can
                # contain the full URL including any query credentials.
                last_error = LLMUnavailable(f"Could not reach Apertus: {type(exc).__name__}")
                logger.warning("apertus.connect_error attempt=%d/%d", attempt + 1, attempts)
            else:
                if response.status_code < 400:
                    return response
                if response.status_code not in RETRYABLE_STATUS:
                    # A permanent refusal. The body is not included, because a
                    # misconfigured proxy may return one containing headers.
                    raise LLMUnavailable(
                        f"Apertus refused the request with HTTP {response.status_code}"
                    )
                last_error = LLMUnavailable(f"Apertus returned HTTP {response.status_code}")
                logger.warning(
                    "apertus.retryable_status status=%d attempt=%d/%d",
                    response.status_code,
                    attempt + 1,
                    attempts,
                )

            if attempt < attempts - 1:
                # Exponential backoff. Short, because a user is waiting.
                await asyncio.sleep(0.5 * (2**attempt))

        assert last_error is not None  # noqa: S101 - unreachable unless attempts is zero
        raise last_error

    # -------------------------------------------------------------- generate

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Produce a complete answer in one call."""
        response = await self._post_with_retries(self._payload(request, stream=False))

        try:
            body = response.json()
            choice = body["choices"][0]
            text = choice["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            # A response that does not match the contract may be a proxy error
            # page. Rendering that to a user as an answer is worse than
            # reporting the service as unavailable.
            raise LLMBadResponse(
                f"Apertus returned a response that could not be parsed: {type(exc).__name__}"
            ) from exc

        usage = body.get("usage") or {}
        return GenerationResult(
            text=text or "",
            model=body.get("model", self.model_name),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            finish_reason=choice.get("finish_reason"),
        )

    # ---------------------------------------------------------------- stream

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        """Produce an answer incrementally as server-sent events.

        A mid-stream failure raises rather than ending the iterator quietly. A
        stream that stops early must not look like a finished answer.
        """
        payload = self._payload(request, stream=True)

        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as response:
                if response.status_code >= 400:
                    raise LLMUnavailable(
                        f"Apertus refused the streaming request with HTTP {response.status_code}"
                    )

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        yield GenerationChunk(text="", done=True)
                        return
                    try:
                        event = json.loads(data)
                        delta = event["choices"][0].get("delta", {})
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                        raise LLMBadResponse(
                            f"Apertus sent an unparseable stream event: {type(exc).__name__}"
                        ) from exc

                    piece = delta.get("content")
                    if piece:
                        yield GenerationChunk(text=piece)

        except httpx.TimeoutException as exc:
            raise LLMTimeout(
                f"Apertus stream timed out after {self._settings.apertus_timeout_seconds}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(
                f"Apertus stream failed: {type(exc).__name__}"
            ) from exc

    # ---------------------------------------------------------------- health

    async def health(self) -> LLMHealth:
        """Report reachability. Never raises.

        Called by the readiness endpoint and by the administration dashboard,
        neither of which should fail because the model service is down. Down is
        the answer they are asking for.
        """
        started = time.perf_counter()
        try:
            response = await self._client.get(
                "/models", timeout=self._settings.apertus_health_timeout_seconds
            )
        except httpx.TimeoutException:
            return LLMHealth(
                state=HealthState.UNAVAILABLE,
                detail=f"No response within {self._settings.apertus_health_timeout_seconds}s",
            )
        except httpx.HTTPError as exc:
            return LLMHealth(
                state=HealthState.UNAVAILABLE,
                detail=f"Could not connect: {type(exc).__name__}",
            )

        latency_ms = (time.perf_counter() - started) * 1000

        if response.status_code >= 400:
            return LLMHealth(
                state=HealthState.UNAVAILABLE,
                detail=f"HTTP {response.status_code} from the model service",
                latency_ms=latency_ms,
            )

        try:
            names = tuple(str(item["id"]) for item in response.json().get("data", []))
        except (json.JSONDecodeError, KeyError, TypeError):
            return LLMHealth(
                state=HealthState.DEGRADED,
                detail="Reachable, but the model list could not be parsed",
                latency_ms=latency_ms,
            )

        if names and self.model_name not in names:
            # Reachable but not serving what we are configured to ask for.
            # Degraded rather than unavailable: an operator may have loaded the
            # model under a different identifier.
            return LLMHealth(
                state=HealthState.DEGRADED,
                detail=(
                    f"Reachable, but the configured model {self.model_name!r} is not in the "
                    f"served list. Check APERTUS_MODEL."
                ),
                latency_ms=latency_ms,
                models=names,
            )

        return LLMHealth(
            state=HealthState.HEALTHY,
            detail=f"Serving {self.model_name}",
            latency_ms=latency_ms,
            models=names,
        )
