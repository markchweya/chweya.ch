"""The guarded fetcher.

Redirect handling carries most of the risk here. A redirect is
attacker-influenced input even when it arrives from a server we trust, so
every hop is revalidated rather than followed.
"""

from __future__ import annotations

import socket

import httpx

from app.config import Settings
from app.ingest.fetcher import GuardedFetcher, HostRateLimiter, detect_type


def make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "secret_key": "test-secret-key-of-adequate-length-000000",
        "database_url": "postgresql+psycopg://u:p@localhost:5432/d",
        "crawler_allowed_hosts": "www.zug.ch,zug.ch",
        "crawler_contact": "test@example.ch",
        "crawler_default_delay_seconds": 0.0,
        "crawler_max_redirects": 3,
        "crawler_max_response_bytes": 4096,
    }
    base.update(overrides)
    # _env_file=None so this does not inherit the developer's .env.
    # Without it a test's outcome depends on an untracked local file:
    # the production-refusal test passed or failed depending on whether
    # BOOTSTRAP_ADMIN_PASSWORD happened to be set on that machine.
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def public_resolver(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
    """Resolve every name to a public address."""
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("195.65.100.10", port))]


def internal_resolver(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
    """Resolve every name to loopback, as a rebinding attempt would."""
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", port))]


def fetcher_with(handler, *, resolver=public_resolver, **overrides):  # type: ignore[no-untyped-def]
    settings = make_settings(**overrides)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    return GuardedFetcher(settings=settings, client=client, resolver=resolver)


class TestGuards:
    async def test_a_normal_page_is_fetched(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>ok</html>", headers={"Content-Type": "text/html"})

        result = await fetcher_with(handler).fetch("https://www.zug.ch/dienste")
        assert result.ok
        assert result.detected_type == "text/html"

    async def test_off_allowlist_host_is_refused_without_a_request(self) -> None:
        called = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            called["n"] += 1
            return httpx.Response(200)

        result = await fetcher_with(handler).fetch("https://example.com/x")
        assert not result.ok
        assert result.reason == "host_not_on_allowlist"
        assert called["n"] == 0, "no socket should be opened for a refused host"

    async def test_a_name_resolving_to_loopback_is_refused(self) -> None:
        """The allowlist passes; the address check is what stops it."""
        called = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            called["n"] += 1
            return httpx.Response(200)

        result = await fetcher_with(handler, resolver=internal_resolver).fetch(
            "https://www.zug.ch/x"
        )
        assert not result.ok
        assert result.reason == "loopback_address"
        assert called["n"] == 0

    async def test_state_changing_methods_are_refused(self) -> None:
        """The crawler never submits a form or changes anything."""
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            result = await fetcher_with(lambda r: httpx.Response(200)).fetch(
                "https://www.zug.ch/x", method=method
            )
            assert result.reason == "unsafe_method", method

    async def test_connection_is_pinned_to_the_validated_address(self) -> None:
        """The request goes to the IP, with Host and SNI preserving the name.

        This is what closes the rebinding window: without it the name is
        resolved again when the socket opens, and the second answer can differ
        from the first.
        """
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url_host"] = request.url.host
            seen["host_header"] = request.headers.get("Host")
            seen["sni"] = request.extensions.get("sni_hostname")
            return httpx.Response(200, text="ok")

        await fetcher_with(handler).fetch("https://www.zug.ch/x")
        assert seen["url_host"] == "195.65.100.10", "connects to the validated address"
        assert seen["host_header"] == "www.zug.ch", "server still sees the right virtual host"
        assert seen["sni"] == "www.zug.ch", "TLS still verifies against the real name"


class TestRedirects:
    async def test_a_redirect_within_the_allowlist_is_followed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.headers.get("Host") == "www.zug.ch" and request.url.path == "/old":
                return httpx.Response(301, headers={"Location": "https://www.zug.ch/new"})
            return httpx.Response(200, text="arrived")

        result = await fetcher_with(handler).fetch("https://www.zug.ch/old")
        assert result.ok
        assert result.final_url.endswith("/new")
        assert result.redirect_chain

    async def test_a_redirect_off_the_allowlist_is_refused(self) -> None:
        """One allowed URL must not be able to walk anywhere it likes."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "https://evil.example/x"})

        result = await fetcher_with(handler).fetch("https://www.zug.ch/redirect")
        assert not result.ok
        assert result.reason == "host_not_on_allowlist"

    async def test_a_redirect_to_a_private_address_is_refused(self) -> None:
        """The destination is on the allowlist by name but not by address."""
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(302, headers={"Location": "https://internal.zug.ch/secrets"})

        def mixed(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            address = "127.0.0.1" if host.startswith("internal") else "195.65.100.10"
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]

        result = await fetcher_with(handler, resolver=mixed).fetch("https://www.zug.ch/go")
        assert not result.ok
        assert result.reason == "loopback_address"
        assert calls["n"] == 1, "the second hop must not open a connection"

    async def test_a_redirect_to_a_non_http_scheme_is_refused(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "file:///etc/passwd"})

        result = await fetcher_with(handler).fetch("https://www.zug.ch/go")
        assert not result.ok
        assert result.reason in {"scheme_not_allowed", "no_hostname"}

    async def test_redirect_chains_are_bounded(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            n = int(request.url.path.rsplit("/", 1)[-1] or 0)
            return httpx.Response(302, headers={"Location": f"https://www.zug.ch/hop/{n + 1}"})

        result = await fetcher_with(handler, crawler_max_redirects=3).fetch(
            "https://www.zug.ch/hop/0"
        )
        assert result.reason == "too_many_redirects"

    async def test_a_redirect_loop_is_detected(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            target = "/b" if path == "/a" else "/a"
            return httpx.Response(302, headers={"Location": f"https://www.zug.ch{target}"})

        result = await fetcher_with(handler).fetch("https://www.zug.ch/a")
        assert result.reason in {"redirect_loop", "too_many_redirects"}


class TestResponseHandling:
    async def test_conditional_request_headers_are_sent(self) -> None:
        seen: dict[str, str | None] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["etag"] = request.headers.get("If-None-Match")
            seen["modified"] = request.headers.get("If-Modified-Since")
            return httpx.Response(304)

        result = await fetcher_with(handler).fetch(
            "https://www.zug.ch/x", etag='"abc"', last_modified="Wed, 01 Jan 2025 00:00:00 GMT"
        )
        assert seen["etag"] == '"abc"'
        assert seen["modified"] == "Wed, 01 Jan 2025 00:00:00 GMT"
        assert result.not_modified
        assert result.ok, "304 is a successful outcome: the cached copy is current"

    async def test_declared_oversize_is_refused_before_reading(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"Content-Length": "999999"}, content=b"x")

        result = await fetcher_with(handler, crawler_max_response_bytes=4096).fetch(
            "https://www.zug.ch/big"
        )
        assert result.reason == "response_too_large"

    async def test_undeclared_oversize_is_caught_while_streaming(self) -> None:
        """Content-Length is a claim, not a guarantee."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * 20_000)

        result = await fetcher_with(handler, crawler_max_response_bytes=4096).fetch(
            "https://www.zug.ch/big"
        )
        assert result.reason == "response_too_large"

    async def test_http_errors_are_reported_not_raised(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        result = await fetcher_with(handler).fetch("https://www.zug.ch/missing")
        assert not result.ok
        assert result.reason == "http_404"
        assert result.status_code == 404


class TestTypeDetection:
    def test_magic_bytes_beat_a_lying_header(self) -> None:
        """A PDF served as text/html is still a PDF."""
        assert detect_type(b"%PDF-1.7\n...", "text/html") == "application/pdf"

    def test_magic_bytes_beat_the_extension(self) -> None:
        """A ZIP named .pdf must not reach the PDF parser."""
        assert detect_type(b"PK\x03\x04rest", "application/pdf") == "application/zip"

    def test_declared_type_is_used_when_nothing_is_recognised(self) -> None:
        assert detect_type(b"<html>", "text/html; charset=utf-8") == "text/html"


class TestRateLimiter:
    def test_first_request_to_a_host_is_immediate(self) -> None:
        limiter = HostRateLimiter(1.0)
        assert limiter.seconds_until_allowed("www.zug.ch") == 0.0

    def test_a_delay_applies_after_a_request(self) -> None:
        limiter = HostRateLimiter(1.0)
        limiter.record_request("www.zug.ch")
        assert 0.0 < limiter.seconds_until_allowed("www.zug.ch") <= 1.0

    def test_hosts_are_tracked_separately(self) -> None:
        limiter = HostRateLimiter(1.0)
        limiter.record_request("www.zug.ch")
        assert limiter.seconds_until_allowed("other.zug.ch") == 0.0

    def test_robots_crawl_delay_can_only_slow_us_down(self) -> None:
        """A site may ask for more space. It may not ask for less."""
        limiter = HostRateLimiter(1.0)
        limiter.set_delay("www.zug.ch", 5.0)
        assert limiter.delay_for("www.zug.ch") == 5.0
        limiter.set_delay("www.zug.ch", 0.1)
        assert limiter.delay_for("www.zug.ch") == 1.0
