"""Apertus provider behaviour, verified against a mocked transport.

No Apertus endpoint is reachable from the build environment, so these tests
pin the wire contract rather than call a live model. The developer confirms the
real endpoint locally with ``python -m app.cli check-config`` and the readiness
endpoint; see docs/apertus.md.

What matters here is failure behaviour. The system must fail closed, so every
way the model service can let us down has to produce an exception the chat
layer can turn into an honest "unavailable" message, never a silent empty
answer.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.llm.apertus import ApertusProvider
from app.llm.base import (
    ChatMessage,
    GenerationRequest,
    HealthState,
    LLMBadResponse,
    LLMRequestTooLarge,
    LLMTimeout,
    LLMUnavailable,
    Role,
)


def make_settings(**overrides: object) -> Settings:
    """Build settings without reading the developer's .env."""
    base: dict[str, object] = {
        "secret_key": "test-secret-key-of-adequate-length-000000",
        "database_url": "postgresql+psycopg://u:p@localhost:5432/d",
        "apertus_base_url": "http://apertus.test/v1",
        "apertus_model": "apertus-8b",
        "apertus_max_retries": 0,
        "apertus_max_context_tokens": 4096,
        "apertus_max_output_tokens": 256,
    }
    base.update(overrides)
    # _env_file=None so this does not inherit the developer's .env.
    # Without it a test's outcome depends on an untracked local file:
    # the production-refusal test passed or failed depending on whether
    # BOOTSTRAP_ADMIN_PASSWORD happened to be set on that machine.
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def provider_with(handler, **overrides: object) -> ApertusProvider:
    """Build a provider whose HTTP calls are served by ``handler``."""
    settings = make_settings(**overrides)
    client = httpx.AsyncClient(
        base_url=settings.apertus_base_url,
        transport=httpx.MockTransport(handler),
    )
    return ApertusProvider(settings=settings, client=client)


SIMPLE_REQUEST = GenerationRequest(
    messages=[
        ChatMessage(role=Role.SYSTEM, content="You answer only from the evidence given."),
        ChatMessage(role=Role.USER, content="Where do I register an address in Baar?"),
    ]
)


class TestGenerate:
    async def test_returns_text_and_usage(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/chat/completions")
            return httpx.Response(
                200,
                json={
                    "model": "apertus-8b",
                    "choices": [
                        {"message": {"content": "Register at the Einwohnerkontrolle."},
                         "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 40, "completion_tokens": 9},
                },
            )

        result = await provider_with(handler).generate(SIMPLE_REQUEST)
        assert result.text == "Register at the Einwohnerkontrolle."
        assert result.prompt_tokens == 40
        assert result.was_truncated is False

    async def test_reports_truncation(self) -> None:
        """A cut-off answer must be flagged, not presented as complete."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "model": "apertus-8b",
                    "choices": [
                        {"message": {"content": "You need: a passport, a rental"},
                         "finish_reason": "length"}
                    ],
                },
            )

        result = await provider_with(handler).generate(SIMPLE_REQUEST)
        assert result.was_truncated is True

    async def test_usage_is_never_invented(self) -> None:
        """When the server reports no usage, the fields stay None."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
            )

        result = await provider_with(handler).generate(SIMPLE_REQUEST)
        assert result.prompt_tokens is None
        assert result.completion_tokens is None


class TestFailsClosed:
    async def test_connection_error_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        with pytest.raises(LLMUnavailable):
            await provider_with(handler).generate(SIMPLE_REQUEST)

    async def test_timeout_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow")

        with pytest.raises(LLMTimeout):
            await provider_with(handler).generate(SIMPLE_REQUEST)

    async def test_server_error_raises_after_retries(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(503)

        with pytest.raises(LLMUnavailable):
            await provider_with(handler, apertus_max_retries=2).generate(SIMPLE_REQUEST)
        assert calls["n"] == 3, "should attempt once plus two retries"

    async def test_client_error_is_not_retried(self) -> None:
        """A 400 will be refused identically next time, so retrying only adds delay."""
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(400)

        with pytest.raises(LLMUnavailable):
            await provider_with(handler, apertus_max_retries=3).generate(SIMPLE_REQUEST)
        assert calls["n"] == 1

    async def test_unparseable_body_raises_rather_than_returning_empty(self) -> None:
        """A proxy error page must not be rendered to a user as an answer."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>502 Bad Gateway</html>")

        with pytest.raises(LLMBadResponse):
            await provider_with(handler).generate(SIMPLE_REQUEST)

    async def test_error_messages_do_not_leak_the_response_body(self) -> None:
        """A misconfigured proxy can echo headers; they must not reach the message."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="Authorization: Bearer super-secret-token")

        with pytest.raises(LLMUnavailable) as caught:
            await provider_with(handler).generate(SIMPLE_REQUEST)
        assert "super-secret-token" not in str(caught.value)


class TestContextBudget:
    async def test_oversized_prompt_is_refused_before_any_request(self) -> None:
        """The guard must fire locally, not rely on the server truncating."""
        called = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            called["n"] += 1
            return httpx.Response(200, json={"choices": []})

        huge = GenerationRequest(
            messages=[ChatMessage(role=Role.USER, content="x" * 100_000)]
        )
        with pytest.raises(LLMRequestTooLarge):
            await provider_with(handler, apertus_max_context_tokens=2048).generate(huge)
        assert called["n"] == 0, "no request should reach the network"

    def test_token_estimate_does_not_underestimate(self) -> None:
        """Erring high costs an evidence passage; erring low loses the system prompt."""
        provider = provider_with(lambda r: httpx.Response(200, json={}))
        text = "Einwohnerkontrolle " * 100
        # A conservative real-world floor is roughly one token per four
        # characters. The estimate must be at least that.
        assert provider.estimate_tokens(text) >= len(text) / 4


class TestStreaming:
    async def test_yields_chunks_then_done(self) -> None:
        body = (
            'data: {"choices":[{"delta":{"content":"You "}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"have 14 days."}}]}\n\n'
            "data: [DONE]\n\n"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=body)

        chunks = [c async for c in provider_with(handler).stream(SIMPLE_REQUEST)]
        assert "".join(c.text for c in chunks) == "You have 14 days."
        assert chunks[-1].done is True

    async def test_midstream_corruption_raises(self) -> None:
        """A stream that stops early must not look like a finished answer."""
        body = 'data: {"choices":[{"delta":{"content":"You "}}]}\n\ndata: {oops\n\n'

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=body)

        with pytest.raises(LLMBadResponse):
            _ = [c async for c in provider_with(handler).stream(SIMPLE_REQUEST)]


class TestHealth:
    async def test_healthy_when_model_is_served(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "apertus-8b"}]})

        health = await provider_with(handler).health()
        assert health.state is HealthState.HEALTHY
        assert health.ok

    async def test_degraded_when_configured_model_is_absent(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "some-other-model"}]})

        health = await provider_with(handler).health()
        assert health.state is HealthState.DEGRADED
        assert "APERTUS_MODEL" in health.detail

    async def test_unavailable_never_raises(self) -> None:
        """Readiness checks must report down, not fail with an exception."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        health = await provider_with(handler).health()
        assert health.state is HealthState.UNAVAILABLE
        assert not health.ok
