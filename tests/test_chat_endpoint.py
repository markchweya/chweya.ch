"""The public chat surface, end to end.

Runs against a real database seeded by a real crawl, with the language model
replaced by a stub. The stub is what makes it possible to assert on refusal
behaviour: a real model would sometimes comply and sometimes not, and a test
that passes intermittently is worse than no test.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.chat import get_embedding_provider, get_llm_provider
from app.config import Settings
from app.db.models import Source
from app.db.session import db_session
from app.ingest.crawler import Crawler
from app.ingest.fetcher import GuardedFetcher
from app.llm.base import GenerationResult, LLMUnavailable
from app.main import create_app
from app.retrieval.embeddings import HashingProvider
from app.retrieval.indexer import embed_pending_chunks, update_search_vectors

PAGE = b"""<html lang="de"><head><title>Adresse anmelden</title></head><body><main>
<h1>Adresse anmelden</h1>
<p>Sie muessen sich innert 14 Tagen nach dem Zuzug bei der Einwohnerkontrolle
Ihrer Gemeinde anmelden. Bringen Sie Ihre Identitaetskarte mit.</p>
<h2>Gebuehren</h2>
<p>Die Anmeldung kostet CHF 20.-- pro Person und ist vor Ort zu entrichten.</p>
</main></body></html>"""

SITEMAP = b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.zug.ch/behoerden/anmeldung</loc></url></urlset>"""


def site(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/robots.txt":
        return httpx.Response(200, content=b"User-agent: *\nSitemap: https://www.zug.ch/sitemap.xml\n")
    if path == "/sitemap.xml":
        return httpx.Response(200, content=SITEMAP, headers={"Content-Type": "application/xml"})
    return httpx.Response(200, content=PAGE, headers={"Content-Type": "text/html"})


def resolver(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("195.65.100.10", port))]


@dataclass
class StubLLM:
    """A language model that returns exactly what a test needs."""

    text: str = "Die Anmeldung kostet CHF 20.-- pro Person [1]."
    fail: bool = False
    truncated: bool = False
    calls: int = 0

    @property
    def model_name(self) -> str:
        return "stub"

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 3 + 1

    async def generate(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.fail:
            raise LLMUnavailable("stub is unavailable")
        return GenerationResult(
            text=self.text,
            model="stub",
            finish_reason="length" if self.truncated else "stop",
        )

    def stream(self, request):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def health(self):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


@pytest.fixture
async def seeded(db):  # type: ignore[no-untyped-def]
    """A database holding one crawled, indexed and approved page."""
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        secret_key="test-secret-key-of-adequate-length-000000",
        database_url="postgresql+psycopg://u:p@localhost:5432/d",
        crawler_allowed_hosts="www.zug.ch",
        crawler_contact="test@example.ch",
        crawler_default_delay_seconds=0.0,
        embedding_model="hashing",
    )
    source = Source(
        name="Behoerden", base_url="https://www.zug.ch/behoerden", default_language="de"
    )
    db.add(source)
    db.flush()

    client = httpx.AsyncClient(transport=httpx.MockTransport(site), follow_redirects=False)
    fetcher = GuardedFetcher(settings=settings, client=client, resolver=resolver)
    await Crawler(db, fetcher, settings=settings).run(source)
    await fetcher.aclose()

    update_search_vectors(db)
    embed_pending_chunks(db, HashingProvider(768))
    db.commit()
    return db


@pytest.fixture
def client(seeded, db):  # type: ignore[no-untyped-def]
    """A test client whose model and database are the ones this test controls."""
    app = create_app()
    stub = StubLLM()

    app.dependency_overrides[get_llm_provider] = lambda: stub
    app.dependency_overrides[get_embedding_provider] = lambda: HashingProvider(768)
    app.dependency_overrides[db_session] = lambda: db

    with TestClient(app) as test_client:
        test_client.stub = stub  # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()


class TestChatPage:
    def test_the_page_renders(self, client) -> None:  # type: ignore[no-untyped-def]
        assert client.get("/").status_code == 200

    def test_the_prototype_notice_is_present_and_not_dismissible(self, client) -> None:  # type: ignore[no-untyped-def]
        html = client.get("/").text
        assert "Inoffizieller KI-Prototyp" in html
        # No control that could hide it.
        assert "dismiss" not in html.lower()

    def test_the_notice_is_localised(self, client) -> None:  # type: ignore[no-untyped-def]
        # Substrings avoid apostrophes, which Jinja autoescaping renders as
        # &#39;. That escaping is correct and is asserted separately below.
        for header, expected in [
            ("de", "Inoffizieller KI-Prototyp"),
            ("en", "Unofficial AI prototype"),
            ("fr", "Prototype d"),
            ("it", "Prototipo di IA non ufficiale"),
        ]:
            html = client.get("/", headers={"Accept-Language": header}).text
            assert expected in html, header

    def test_template_output_is_autoescaped(self, client) -> None:  # type: ignore[no-untyped-def]
        """The interface renders text extracted from crawled pages and PDFs.

        Autoescaping is the layer that stops markup in that text executing, so
        it is pinned rather than assumed.
        """
        html = client.get("/", headers={"Accept-Language": "fr"}).text
        assert "&#39;" in html, "apostrophes must be escaped, not emitted raw"

    def test_a_question_containing_markup_is_escaped_in_the_transcript(self, client) -> None:  # type: ignore[no-untyped-def]
        hostile = '<img src=x onerror="alert(1)">'
        html = client.post("/ask", data={"question": hostile, "lang": "de"}).text

        # What matters is that the angle brackets and quotes are escaped, so
        # the browser sees text rather than an element. The substring
        # "onerror=" appearing as visible text is harmless; an unescaped "<img"
        # is not.
        assert "<img" not in html
        assert "&lt;img" in html
        assert 'onerror="alert(1)"' not in html

    def test_the_document_language_matches_the_content(self, client) -> None:  # type: ignore[no-untyped-def]
        """A German page announced with an English voice fails WCAG 3.1.1."""
        html = client.get("/", headers={"Accept-Language": "fr"}).text
        assert '<html lang="fr">' in html

    def test_no_spinner_or_typing_indicator_exists(self, client) -> None:  # type: ignore[no-untyped-def]
        """The mark is the only status indicator in the product."""
        html = client.get("/").text.lower()
        assert "spinner" not in html
        assert "typing" not in html
        assert 'class="dumi"' in client.get("/").text

    def test_the_form_works_without_javascript(self, client) -> None:  # type: ignore[no-untyped-def]
        html = client.get("/").text
        assert 'method="post"' in html
        assert 'action="/ask"' in html

    def test_the_question_field_has_a_real_label(self, client) -> None:  # type: ignore[no-untyped-def]
        """A placeholder is not a label: it vanishes on focus."""
        html = client.get("/").text
        assert 'for="question"' in html
        assert 'id="question"' in html

    def test_the_transcript_is_a_live_region(self, client) -> None:  # type: ignore[no-untyped-def]
        """Otherwise a streamed answer is never announced."""
        html = client.get("/").text
        assert 'aria-live="polite"' in html
        assert 'role="log"' in html

    def test_a_stop_control_exists(self, client) -> None:  # type: ignore[no-untyped-def]
        assert 'id="stop"' in client.get("/").text


class TestAnswering:
    def test_a_grounded_question_is_answered_with_citations(self, client) -> None:  # type: ignore[no-untyped-def]
        response = client.post(
            "/ask",
            json={"question": "Was kostet die Anmeldung?", "lang": "de"},
            headers={"Accept": "application/json"},
        )
        payload = response.json()
        assert response.status_code == 200
        assert not payload["is_refusal"]
        assert payload["citations"], "a factual answer must carry citations"
        assert payload["citations"][0]["url"].startswith("https://www.zug.ch/")

    def test_citations_carry_what_section_11_requires(self, client) -> None:  # type: ignore[no-untyped-def]
        payload = client.post(
            "/ask",
            json={"question": "Was kostet die Anmeldung?", "lang": "de"},
            headers={"Accept": "application/json"},
        ).json()
        citation = payload["citations"][0]
        assert citation["title"]
        assert citation["url"]
        assert citation["language"] == "de"
        assert citation["last_checked"]

    def test_a_citation_never_points_at_a_homepage(self, client) -> None:  # type: ignore[no-untyped-def]
        """Section 11: cite the service page, not the front door."""
        payload = client.post(
            "/ask",
            json={"question": "Was kostet die Anmeldung?", "lang": "de"},
            headers={"Accept": "application/json"},
        ).json()
        for citation in payload["citations"]:
            assert citation["url"].rstrip("/") != "https://www.zug.ch"

    def test_an_unsupported_question_is_refused_not_guessed(self, client) -> None:  # type: ignore[no-untyped-def]
        """The single most important behaviour in the product."""
        payload = client.post(
            "/ask",
            json={"question": "Wie hoch ist die Hundesteuer in Reykjavik?", "lang": "de"},
            headers={"Accept": "application/json"},
        ).json()
        assert payload["is_refusal"]
        assert payload["confidence"] == "insufficient"
        assert payload["citations"] == []
        assert client.stub.calls == 0, "the model must not be called with no evidence"

    def test_an_unavailable_model_says_so(self, client) -> None:  # type: ignore[no-untyped-def]
        """Fail closed: never answer from model memory."""
        client.stub.fail = True
        payload = client.post(
            "/ask",
            json={"question": "Was kostet die Anmeldung?", "lang": "de"},
            headers={"Accept": "application/json"},
        ).json()
        assert payload["is_refusal"]
        assert "nicht erreichbar" in payload["text"]

    def test_an_answer_with_no_citations_is_replaced(self, client) -> None:  # type: ignore[no-untyped-def]
        """The prompt required citations and evidence was supplied."""
        client.stub.text = "Die Anmeldung kostet zwanzig Franken."
        payload = client.post(
            "/ask",
            json={"question": "Was kostet die Anmeldung?", "lang": "de"},
            headers={"Accept": "application/json"},
        ).json()
        assert payload["is_refusal"]
        assert payload["citations"] == []

    def test_invented_citations_are_stripped(self, client) -> None:  # type: ignore[no-untyped-def]
        client.stub.text = "Die Anmeldung kostet CHF 20 [1]. Die Frist betraegt 30 Tage [9]."
        payload = client.post(
            "/ask",
            json={"question": "Was kostet die Anmeldung?", "lang": "de"},
            headers={"Accept": "application/json"},
        ).json()
        assert "[9]" not in payload["text"]
        assert "[1]" in payload["text"]

    def test_internal_policy_reasons_are_not_returned_to_the_client(self, client) -> None:  # type: ignore[no-untyped-def]
        """They name retrieval signals and would leak how scoring works."""
        payload = client.post(
            "/ask",
            json={"question": "Was kostet die Anmeldung?", "lang": "de"},
            headers={"Accept": "application/json"},
        ).json()
        assert "reasons" not in payload

    def test_the_html_surface_answers_the_same_way(self, client) -> None:  # type: ignore[no-untyped-def]
        """No path where one surface can answer what the other cannot."""
        response = client.post("/ask", data={"question": "Was kostet die Anmeldung?", "lang": "de"})
        assert response.status_code == 200
        assert "CHF 20" in response.text
        assert "Quellen" in response.text


class TestHighRiskHandling:
    def test_a_tax_question_carries_the_limitation_notice(self, client) -> None:  # type: ignore[no-untyped-def]
        payload = client.post(
            "/ask",
            json={"question": "Wann ist die Frist fuer die Steuererklaerung?", "lang": "de"},
            headers={"Accept": "application/json"},
        ).json()
        keys = [notice["key"] for notice in payload["notices"]]
        assert "answer.high_risk" in keys

    def test_an_emergency_question_surfaces_the_numbers_first(self, client) -> None:  # type: ignore[no-untyped-def]
        """Section 12 forbids delaying someone with procedural detail."""
        payload = client.post(
            "/ask",
            json={"question": "Ich brauche sofort die Polizei", "lang": "de"},
            headers={"Accept": "application/json"},
        ).json()
        notices = payload["notices"]
        assert notices, "an emergency question must carry a notice"
        assert notices[0]["key"] == "answer.emergency"
        assert "117" in notices[0]["text"]


class TestValidation:
    def test_an_empty_question_is_rejected_politely(self, client) -> None:  # type: ignore[no-untyped-def]
        payload = client.post(
            "/ask", json={"question": "   ", "lang": "de"}, headers={"Accept": "application/json"}
        ).json()
        assert payload["is_refusal"]

    def test_an_overlong_question_is_rejected(self, client) -> None:  # type: ignore[no-untyped-def]
        payload = client.post(
            "/ask",
            json={"question": "a" * 5000, "lang": "de"},
            headers={"Accept": "application/json"},
        ).json()
        assert payload["is_refusal"]
        assert client.stub.calls == 0

    def test_rate_limiting_returns_429_with_retry_after(self, client) -> None:  # type: ignore[no-untyped-def]
        last = None
        for _ in range(40):
            last = client.post(
                "/ask",
                json={"question": "Was kostet die Anmeldung?", "lang": "de"},
                headers={"Accept": "application/json"},
            )
            if last.status_code == 429:
                break
        assert last is not None and last.status_code == 429
        assert last.headers.get("Retry-After")


class TestFailureHandling:
    """What a resident sees when something inside the system breaks."""

    @pytest.fixture(autouse=True)
    def _fresh_rate_limit(self):  # type: ignore[no-untyped-def]
        """The limiter is process-wide, and the rate-limit test above spends
        the whole budget. These tests assert on failure handling, not on
        throttling, so they start with a clean window."""
        from app.api import chat

        chat._LIMITERS.clear()
        yield
        chat._LIMITERS.clear()

    def test_a_crash_returns_the_request_id_it_tells_you_to_quote(self, seeded, db) -> None:  # type: ignore[no-untyped-def]
        """The 500 body asks the user to quote the request id, so it must
        actually contain one. It used to contain an empty string, because the
        handler read a contextvar that the request middleware had already
        reset by the time the outermost error middleware ran."""
        app = create_app()

        def broken_session():
            raise RuntimeError("wired to fail for this test")

        app.dependency_overrides[db_session] = broken_session

        with TestClient(app, raise_server_exceptions=False) as test_client:
            response = test_client.post("/ask", data={"question": "Wie melde ich mich an?"})

        assert response.status_code == 500
        payload = response.json()
        assert payload["request_id"], "the body promises a request id and must carry one"
        assert payload["request_id"] == response.headers["X-Request-ID"]
        # And nothing internal leaks alongside it.
        assert "wired to fail" not in response.text

    def test_an_unavailable_embedding_model_degrades_to_keyword_search(self, seeded, db) -> None:  # type: ignore[no-untyped-def]
        """A model that cannot be loaded costs the semantic arm, never the
        request. The keyword arm still finds the page and the answer arrives,
        which is the difference between a quieter answer and a 500."""
        from app.retrieval.embeddings import UnavailableEmbeddings

        app = create_app()
        stub = StubLLM()
        app.dependency_overrides[get_llm_provider] = lambda: stub
        app.dependency_overrides[get_embedding_provider] = lambda: UnavailableEmbeddings(
            reason="ProxyError", dimensions=768
        )
        app.dependency_overrides[db_session] = lambda: db

        with TestClient(app) as test_client:
            response = test_client.post(
                "/ask",
                json={"question": "Was kostet die Anmeldung?", "lang": "de"},
                headers={"Accept": "application/json"},
            )

        assert response.status_code == 200
        payload = response.json()
        assert not payload["is_refusal"]
        assert "CHF 20.--" in payload["text"]


class TestProviderCache:
    """The embedding provider is built once per process, not once per request."""

    @pytest.fixture(autouse=True)
    def _clean_cache(self):  # type: ignore[no-untyped-def]
        from app.api import chat

        chat._provider_cache.clear()
        chat._provider_failures.clear()
        yield
        chat._provider_cache.clear()
        chat._provider_failures.clear()

    def test_a_working_provider_is_constructed_once(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from app.api import chat

        calls = {"n": 0}

        def build(settings):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            return HashingProvider(768)

        monkeypatch.setattr(chat, "build_embedding_provider", build)
        first = chat.get_embedding_provider()
        second = chat.get_embedding_provider()
        assert first is second
        assert calls["n"] == 1

    def test_a_load_failure_is_held_rather_than_retried_every_request(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """A blocked model download must not be paid for on every question.
        The failure is cached with a retry hold, so one slow timeout does not
        become a site-wide per-request latency."""
        from app.api import chat
        from app.retrieval.embeddings import UnavailableEmbeddings

        calls = {"n": 0}

        def build(settings):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            raise OSError("proxy refused the download")

        monkeypatch.setattr(chat, "build_embedding_provider", build)
        first = chat.get_embedding_provider()
        second = chat.get_embedding_provider()
        assert isinstance(first, UnavailableEmbeddings)
        assert second is first
        assert calls["n"] == 1

    def test_a_held_failure_is_retried_after_the_hold_expires(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """Cached failure must not mean disabled until restart."""
        from app.api import chat

        def build(settings):  # type: ignore[no-untyped-def]
            raise OSError("proxy refused the download")

        monkeypatch.setattr(chat, "build_embedding_provider", build)
        chat.get_embedding_provider()

        # Age the recorded failure past the hold, then make loading work.
        key = next(iter(chat._provider_failures))
        chat._provider_failures[key] -= chat.PROVIDER_RETRY_SECONDS + 1
        monkeypatch.setattr(chat, "build_embedding_provider", lambda s: HashingProvider(768))

        recovered = chat.get_embedding_provider()
        assert isinstance(recovered, HashingProvider)
