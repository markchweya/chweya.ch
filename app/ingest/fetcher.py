"""The guarded HTTP fetcher.

Every outbound request the crawler makes goes through here. Nothing else in
the application opens a connection to a URL that came from a page, a sitemap
or an administrator form.

What this enforces:

* GET and HEAD only. The crawler never performs a state-changing request and
  never submits a form.
* The URL allowlist, before any DNS lookup.
* Address validation on the resolved addresses, and the connection is pinned
  to a validated address so the name cannot resolve to something else between
  the check and the connection.
* Redirects are followed manually, and every hop is revalidated through both
  gates. Following redirects automatically would let one allowed URL walk to
  an internal address in a single response.
* A response size cap enforced while streaming, so an endless body cannot
  exhaust memory.
* Conditional requests, so unchanged pages cost one round trip and no body.
* Content type taken from the response header and the leading bytes, never
  from the file extension.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import Settings, get_settings
from app.ingest.netguard import resolve_and_validate
from app.ingest.urls import evaluate
from app.observability import get_logger
from app.security.hashing import content_digest

logger = get_logger(__name__)

# Methods that cannot change state on the far side.
SAFE_METHODS = frozenset({"GET", "HEAD"})

# Leading bytes that identify a format regardless of what the extension or the
# Content-Type header claims. A PDF served as text/html is still a PDF, and a
# ZIP renamed to .pdf is still a ZIP.
MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"\x1f\x8b", "application/gzip"),
    (b"\xd0\xcf\x11\xe0", "application/x-ole-storage"),  # legacy .doc and .xls
)


@dataclass
class FetchResult:
    """The outcome of one fetch attempt.

    A refusal is a result, not an exception. The crawler records why each URL
    was skipped, and raising for the ordinary case of "not allowed" would make
    that bookkeeping harder rather than easier.
    """

    url: str
    ok: bool = False
    # Machine-readable, so blocked attempts can be counted by cause.
    reason: str = ""
    status_code: int | None = None
    content: bytes = b""
    content_type: str = ""
    detected_type: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    # Populated when the URL was reached through one or more redirects.
    redirect_chain: tuple[str, ...] = ()
    final_url: str = ""
    elapsed_ms: float = 0.0

    @property
    def not_modified(self) -> bool:
        """True when the server confirmed the cached copy is still current."""
        return self.status_code == 304

    @property
    def digest(self) -> str:
        """SHA-256 of the body, for change detection."""
        return content_digest(self.content)


class HostRateLimiter:
    """Per-host politeness delay.

    Crawling a cantonal website is not a load test. The delay is per host and
    applies across the whole process, so raising concurrency does not
    accidentally raise the request rate against one server.
    """

    def __init__(self, default_delay: float) -> None:
        self._default = default_delay
        self._last: dict[str, float] = {}
        self._delays: dict[str, float] = {}

    def set_delay(self, host: str, delay: float) -> None:
        """Record a Crawl-delay learned from robots.txt."""
        # The site's own request wins whenever it asks for more space than our
        # default. It is not allowed to ask for less.
        self._delays[host] = max(delay, self._default)

    def delay_for(self, host: str) -> float:
        return self._delays.get(host, self._default)

    def seconds_until_allowed(self, host: str) -> float:
        """Return how long to wait before the next request to ``host``."""
        last = self._last.get(host)
        if last is None:
            return 0.0
        waited = time.monotonic() - last
        return max(0.0, self.delay_for(host) - waited)

    def record_request(self, host: str) -> None:
        self._last[host] = time.monotonic()


def detect_type(body: bytes, declared: str) -> str:
    """Identify the content type from the leading bytes, falling back to the header.

    Extensions are ignored entirely. A URL ending in .pdf proves nothing, and
    trusting it is how a parser gets handed something it cannot safely read.
    """
    for signature, media_type in MAGIC_SIGNATURES:
        if body.startswith(signature):
            return media_type

    # Nothing recognisable. Trust the declared type, stripped of its charset.
    return declared.split(";", 1)[0].strip().lower()


class GuardedFetcher:
    """Fetches URLs under the allowlist, address and size guards."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
        resolver=None,  # type: ignore[no-untyped-def]
    ):
        self._settings = settings or get_settings()
        # Injectable so tests can drive resolution without real DNS, and so a
        # deployment could later substitute a resolver that pins to a
        # known-good set of addresses.
        self._resolver = resolver
        self._limiter = HostRateLimiter(self._settings.crawler_default_delay_seconds)
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(self._settings.crawler_request_timeout_seconds, connect=10.0),
            headers={
                "User-Agent": self._settings.user_agent,
                # Declares what the crawler can use. Asking for everything and
                # discarding most of it wastes the far side's bandwidth.
                "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.1",
                "Accept-Language": "de,fr;q=0.8,it;q=0.7,en;q=0.6",
            },
            # Redirects are followed manually so every hop is revalidated.
            follow_redirects=False,
        )

    @property
    def limiter(self) -> HostRateLimiter:
        return self._limiter

    async def aclose(self) -> None:
        await self._client.aclose()

    def _pinned_target(self, url: str, address: str) -> tuple[str, dict[str, str], dict[str, str]]:
        """Rewrite ``url`` to connect to ``address`` while preserving the name.

        Returns the rewritten URL, the headers that keep the request correct
        for the original host, and the transport extensions that keep TLS
        verification against the original name.

        This is what closes the rebinding window. Without it, the address is
        validated and then the name is resolved again when the socket opens,
        and the second answer can differ from the first.
        """
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = parts.port
        # An IPv6 literal has to be bracketed in a netloc.
        literal = f"[{address}]" if ":" in address else address
        netloc = f"{literal}:{port}" if port else literal
        pinned = urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))

        # Host tells the server which virtual host is wanted; SNI tells TLS
        # which certificate to present and which name to verify against.
        headers = {"Host": f"{host}:{port}" if port else host}
        extensions = {"sni_hostname": host}
        return pinned, headers, extensions

    async def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        etag: str | None = None,
        last_modified: str | None = None,
        _depth: int = 0,
        _chain: tuple[str, ...] = (),
    ) -> FetchResult:
        """Fetch one URL under every guard.

        ``etag`` and ``last_modified`` come from the previously stored version
        of this URL. When the server answers 304 the body is not transferred at
        all, which is the difference between a synchronisation run that costs
        a few megabytes and one that re-downloads the whole site.
        """
        settings = self._settings

        if method.upper() not in SAFE_METHODS:
            # Defensive: nothing in the codebase asks for another method, and
            # if something ever does it is a bug worth failing on.
            return FetchResult(url=url, reason="unsafe_method")

        decision = evaluate(url, settings.allowed_hosts)
        if not decision.allowed:
            # The path is logged as well as the host: a block on a redirect
            # target is otherwise undiagnosable, because the original URL
            # never shows what it redirected to. Crawl targets are public
            # pages, so the path carries nothing personal.
            logger.info(
                "crawl.blocked",
                reason=decision.reason,
                url_host=_host_of(url),
                url_path=urlsplit(url).path[:300],
            )
            return FetchResult(url=url, reason=decision.reason)

        target = decision.normalised
        parts = urlsplit(target)
        host = parts.hostname or ""
        port = parts.port or (443 if parts.scheme == "https" else 80)

        if self._resolver is not None:
            address_decision = resolve_and_validate(host, port, resolver=self._resolver)
        else:
            address_decision = resolve_and_validate(host, port)
        if not address_decision.allowed:
            logger.warning("crawl.blocked_address", reason=address_decision.reason, url_host=host)
            return FetchResult(url=target, reason=address_decision.reason)

        wait = self._limiter.seconds_until_allowed(host)
        if wait > 0:
            import asyncio

            await asyncio.sleep(wait)

        pinned_url, extra_headers, extensions = self._pinned_target(
            target, address_decision.addresses[0]
        )

        conditional: dict[str, str] = {}
        if etag:
            conditional["If-None-Match"] = etag
        if last_modified:
            conditional["If-Modified-Since"] = last_modified

        started = time.perf_counter()
        self._limiter.record_request(host)

        try:
            async with self._client.stream(
                method.upper(),
                pinned_url,
                headers={**extra_headers, **conditional},
                extensions=extensions,
            ) as response:
                elapsed = (time.perf_counter() - started) * 1000

                if response.status_code in (301, 302, 303, 307, 308):
                    return await self._follow_redirect(
                        response, target, _depth, _chain, etag, last_modified, elapsed
                    )

                if response.status_code == 304:
                    return FetchResult(
                        url=target,
                        ok=True,
                        reason="not_modified",
                        status_code=304,
                        headers=dict(response.headers),
                        redirect_chain=_chain,
                        final_url=target,
                        elapsed_ms=elapsed,
                    )

                if response.status_code >= 400:
                    return FetchResult(
                        url=target,
                        reason=f"http_{response.status_code}",
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        elapsed_ms=elapsed,
                    )

                # Refuse an oversized body before reading it, when the server
                # is honest enough to declare the length.
                declared_length = response.headers.get("Content-Length")
                if declared_length and declared_length.isdigit():
                    if int(declared_length) > settings.crawler_max_response_bytes:
                        return FetchResult(
                            url=target,
                            reason="response_too_large",
                            status_code=response.status_code,
                            elapsed_ms=elapsed,
                        )

                # And enforce the cap while streaming, because Content-Length
                # is a claim rather than a guarantee.
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > settings.crawler_max_response_bytes:
                        return FetchResult(
                            url=target,
                            reason="response_too_large",
                            status_code=response.status_code,
                            elapsed_ms=elapsed,
                        )
                    chunks.append(chunk)

                body = b"".join(chunks)
                declared_type = response.headers.get("Content-Type", "")

                return FetchResult(
                    url=target,
                    ok=True,
                    status_code=response.status_code,
                    content=body,
                    content_type=declared_type,
                    detected_type=detect_type(body, declared_type),
                    headers=dict(response.headers),
                    redirect_chain=_chain,
                    final_url=target,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                )

        except httpx.TimeoutException:
            return FetchResult(url=target, reason="timeout")
        except httpx.HTTPError as exc:
            # Type only. An httpx message can contain the full URL.
            return FetchResult(url=target, reason=f"transport_error_{type(exc).__name__}")

    async def _follow_redirect(
        self,
        response: httpx.Response,
        current: str,
        depth: int,
        chain: tuple[str, ...],
        etag: str | None,
        last_modified: str | None,
        elapsed: float,
    ) -> FetchResult:
        """Follow one redirect hop, revalidating the destination.

        Every hop goes back through fetch(), so the allowlist and the address
        checks apply again. A redirect is attacker-influenced input even when
        it comes from a server we trust, and following one blindly would let a
        single allowed URL reach an internal address.
        """
        if depth >= self._settings.crawler_max_redirects:
            return FetchResult(
                url=current,
                reason="too_many_redirects",
                status_code=response.status_code,
                redirect_chain=chain,
                elapsed_ms=elapsed,
            )

        location = response.headers.get("Location", "")
        if not location:
            return FetchResult(url=current, reason="redirect_without_location")

        from app.ingest.urls import normalise

        try:
            destination = normalise(location, base=current)
        except ValueError:
            return FetchResult(url=current, reason="malformed_redirect_target")

        # A redirect back to somewhere already visited is a loop.
        if destination in chain or destination == current:
            return FetchResult(url=current, reason="redirect_loop", redirect_chain=chain)

        logger.debug("crawl.redirect", depth=depth + 1, host=_host_of(destination))
        return await self.fetch(
            destination,
            etag=etag,
            last_modified=last_modified,
            _depth=depth + 1,
            _chain=(*chain, current),
        )


def _host_of(url: str) -> str:
    """Return the hostname of a URL, for logging.

    Only the host is logged, never the full URL. A path on a cantonal site can
    identify a very specific service, and an operational log should not
    accumulate a record of exactly what was fetched when.
    """
    try:
        return urlsplit(url).hostname or "(none)"
    except ValueError:
        return "(unparseable)"
