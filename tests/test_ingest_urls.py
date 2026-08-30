"""URL normalisation and allowlist decisions.

The allowlist is the first of the two gates that keep the crawler inside
public Canton of Zug content. Its failure modes are the classic ones, so they
are tested explicitly rather than assumed.
"""

from __future__ import annotations

import pytest

from app.ingest.urls import evaluate, host_matches_allowlist, normalise

ZUG = ("www.zug.ch", "zug.ch")


class TestNormalise:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # Scheme and host are case-insensitive; path is not.
            ("HTTPS://WWW.ZUG.CH/Einwohner", "https://www.zug.ch/Einwohner"),
            # Default ports carry no meaning.
            ("https://www.zug.ch:443/a", "https://www.zug.ch/a"),
            ("http://www.zug.ch:80/a", "http://www.zug.ch/a"),
            # A non-default port does.
            ("https://www.zug.ch:8443/a", "https://www.zug.ch:8443/a"),
            # Fragments never reach the server.
            ("https://www.zug.ch/a#section-2", "https://www.zug.ch/a"),
            # An empty path is the root.
            ("https://www.zug.ch", "https://www.zug.ch/"),
            # Repeated slashes are collapsed by servers.
            ("https://www.zug.ch//a///b", "https://www.zug.ch/a/b"),
            # Query order does not change the resource.
            ("https://www.zug.ch/a?b=2&a=1", "https://www.zug.ch/a?a=1&b=2"),
            # Tracking parameters are removed.
            ("https://www.zug.ch/a?utm_source=x&id=7", "https://www.zug.ch/a?id=7"),
            ("https://www.zug.ch/a?gclid=x", "https://www.zug.ch/a"),
        ],
    )
    def test_normalisation(self, raw: str, expected: str) -> None:
        assert normalise(raw) == expected

    def test_path_case_is_preserved(self) -> None:
        """Paths are case-sensitive on many servers; lower-casing would 404."""
        assert normalise("https://www.zug.ch/Steuern/Formulare") == (
            "https://www.zug.ch/Steuern/Formulare"
        )

    def test_relative_urls_resolve_against_the_base(self) -> None:
        assert normalise("../steuern", base="https://www.zug.ch/a/b/c") == (
            "https://www.zug.ch/a/steuern"
        )

    def test_meaningful_query_parameters_survive(self) -> None:
        """Stripping a parameter the site uses would cite the wrong page."""
        assert "id=4711" in normalise("https://www.zug.ch/dienst?id=4711")


class TestAllowlistMatching:
    def test_exact_and_subdomain_match(self) -> None:
        assert host_matches_allowlist("zug.ch", ZUG)
        assert host_matches_allowlist("www.zug.ch", ZUG)
        assert host_matches_allowlist("steuern.zug.ch", ZUG)

    def test_suffix_confusion_is_rejected(self) -> None:
        """The classic allowlist failure: endswith without a label boundary."""
        assert not host_matches_allowlist("evil-zug.ch", ZUG)
        assert not host_matches_allowlist("notzug.ch", ZUG)
        assert not host_matches_allowlist("xzug.ch", ZUG)

    def test_prefix_confusion_is_rejected(self) -> None:
        assert not host_matches_allowlist("zug.ch.attacker.example", ZUG)
        assert not host_matches_allowlist("zug.ch.evil.com", ZUG)

    def test_trailing_dot_is_handled(self) -> None:
        """zug.ch. is the same name as zug.ch and must not slip past."""
        assert host_matches_allowlist("www.zug.ch.", ZUG)

    def test_case_is_ignored(self) -> None:
        assert host_matches_allowlist("WWW.ZUG.CH", ZUG)


class TestEvaluate:
    def test_a_normal_page_is_allowed(self) -> None:
        decision = evaluate("https://www.zug.ch/behoerden/einwohnerkontrolle", ZUG)
        assert decision.allowed
        assert decision.normalised.startswith("https://www.zug.ch/")

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://www.zug.ch/x",
            "gopher://www.zug.ch/x",
            "data:text/html,<script>alert(1)</script>",
            "javascript:alert(1)",
        ],
    )
    def test_non_http_schemes_are_refused(self, url: str) -> None:
        decision = evaluate(url, ZUG)
        assert not decision.allowed
        assert decision.reason in {"scheme_not_allowed", "no_hostname", "malformed_url"}

    def test_off_allowlist_hosts_are_refused(self) -> None:
        assert evaluate("https://example.com/x", ZUG).reason == "host_not_on_allowlist"

    def test_credentials_in_url_are_refused(self) -> None:
        decision = evaluate("https://user:pass@www.zug.ch/x", ZUG)
        assert not decision.allowed
        assert decision.reason == "credentials_in_url"

    @pytest.mark.parametrize(
        "path",
        [
            "/suche?q=steuern",
            "/search?q=tax",
            "/recherche?q=impot",
            "/kalender/2026/01",
            "/login",
            "/admin/settings",
            "/intern/notizen",
            # CMS view endpoints seen on zg.ch, which duplicate pages the
            # crawler already has and burn page budget for nothing.
            "/behoerden/baudirektion/@@megaphone_news",
            "/behoerden/thema/@@book_reader_view",
            "/behoerden/thema/feedback_view",
            "/behoerden/adresse/addressblock_detail_view",
            "/behoerden/thema/export_pdf",
            "/de/aforms-formular/libraryId/SKA/formId/KONTAKT",
        ],
    )
    def test_excluded_paths_are_refused(self, path: str) -> None:
        """Search pages, calendars, authenticated areas and CMS view
        endpoints are out of scope."""
        decision = evaluate(f"https://www.zug.ch{path}", ZUG)
        assert not decision.allowed
        assert decision.reason == "excluded_path"

    def test_content_pages_near_the_view_patterns_stay_allowed(self) -> None:
        """The view filter must not swallow real pages: an ordinary section
        page, a page whose name merely contains "view", and a PDF that is
        not the export endpoint all stay crawlable."""
        for path in (
            "/behoerden/baudirektion/direktionssekretariat/einleitung",
            "/themen/interview-mit-der-vorsteherin",
            "/dokumente/ferienkalender.pdf",
        ):
            assert evaluate(f"https://www.zug.ch{path}", ZUG).allowed, path

    def test_deep_paths_are_refused(self) -> None:
        deep = "https://www.zug.ch/" + "/".join(str(i) for i in range(40))
        assert evaluate(deep, ZUG).reason == "path_too_deep"

    def test_pagination_matrix_is_refused(self) -> None:
        """Two pagination parameters multiply into thousands of near-duplicates."""
        decision = evaluate("https://www.zug.ch/liste?page=3&offset=60", ZUG)
        assert not decision.allowed
        assert decision.reason == "pagination_matrix"

    def test_single_pagination_parameter_is_fine(self) -> None:
        assert evaluate("https://www.zug.ch/liste?page=3", ZUG).allowed

    def test_overlong_urls_are_refused(self) -> None:
        assert not evaluate("https://www.zug.ch/" + "a" * 3000, ZUG).allowed

    def test_empty_input_is_refused(self) -> None:
        assert not evaluate("", ZUG).allowed
