"""robots.txt obedience and sitemap parsing.

The behaviour that matters most is what happens when robots.txt cannot be
read. Treating an unreadable robots.txt as permission is how a crawler ends up
somewhere it was told to stay out of.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.ingest.robots import RobotsCache, parse_robots
from app.ingest.sitemap import discover, parse_sitemap

AGENT = "DumiBot/0.1"


@dataclass
class FakeResult:
    ok: bool = False
    status_code: int | None = None
    content: bytes = b""
    reason: str = ""


class FakeFetcher:
    """Serves canned responses keyed by URL."""

    def __init__(self, responses: dict[str, FakeResult]) -> None:
        self._responses = responses
        self.requested: list[str] = []

    async def fetch(self, url: str, **kwargs: object) -> FakeResult:
        self.requested.append(url)
        return self._responses.get(url, FakeResult(reason="not_found", status_code=404))


ROBOTS = b"""
User-agent: *
Disallow: /intern/
Disallow: /suche
Crawl-delay: 2

Sitemap: https://www.zug.ch/sitemap.xml
Sitemap: https://www.zug.ch/sitemap-news.xml
"""


class TestRobotsParsing:
    def test_disallowed_paths_are_refused(self) -> None:
        policy = parse_robots(ROBOTS.decode(), "www.zug.ch", AGENT)
        assert not policy.allows("https://www.zug.ch/intern/notizen", AGENT)
        assert not policy.allows("https://www.zug.ch/suche?q=x", AGENT)

    def test_allowed_paths_pass(self) -> None:
        policy = parse_robots(ROBOTS.decode(), "www.zug.ch", AGENT)
        assert policy.allows("https://www.zug.ch/behoerden/einwohnerkontrolle", AGENT)

    def test_crawl_delay_is_read(self) -> None:
        policy = parse_robots(ROBOTS.decode(), "www.zug.ch", AGENT)
        assert policy.crawl_delay_seconds == 2.0

    def test_sitemaps_are_collected(self) -> None:
        policy = parse_robots(ROBOTS.decode(), "www.zug.ch", AGENT)
        assert policy.sitemaps == (
            "https://www.zug.ch/sitemap.xml",
            "https://www.zug.ch/sitemap-news.xml",
        )

    def test_sitemap_only_robots_still_yields_sitemaps(self) -> None:
        """RobotFileParser.site_maps() returns None when no group was parsed."""
        policy = parse_robots("Sitemap: https://www.zug.ch/s.xml\n", "www.zug.ch", AGENT)
        assert policy.sitemaps == ("https://www.zug.ch/s.xml",)


class TestRobotsFailureBehaviour:
    async def test_404_allows_everything(self) -> None:
        """No published rules means nothing is disallowed."""
        fetcher = FakeFetcher(
            {"https://www.zug.ch/robots.txt": FakeResult(ok=False, status_code=404)}
        )
        cache = RobotsCache(fetcher, AGENT)
        allowed, reason = await cache.allows("https://www.zug.ch/anything")
        assert allowed, reason

    async def test_server_error_disallows_everything(self) -> None:
        """We do not know the rules, so we do not assume permission."""
        fetcher = FakeFetcher(
            {"https://www.zug.ch/robots.txt": FakeResult(ok=False, status_code=503)}
        )
        cache = RobotsCache(fetcher, AGENT)
        allowed, reason = await cache.allows("https://www.zug.ch/anything")
        assert not allowed
        assert reason == "robots_unreadable"

    async def test_timeout_disallows_everything(self) -> None:
        fetcher = FakeFetcher(
            {"https://www.zug.ch/robots.txt": FakeResult(ok=False, reason="timeout")}
        )
        cache = RobotsCache(fetcher, AGENT)
        allowed, _ = await cache.allows("https://www.zug.ch/anything")
        assert not allowed

    async def test_forbidden_robots_disallows_everything(self) -> None:
        """A restricted robots.txt is a signal to stay out, not to guess."""
        fetcher = FakeFetcher(
            {"https://www.zug.ch/robots.txt": FakeResult(ok=False, status_code=403)}
        )
        cache = RobotsCache(fetcher, AGENT)
        allowed, _ = await cache.allows("https://www.zug.ch/anything")
        assert not allowed

    async def test_robots_is_fetched_once_per_host(self) -> None:
        fetcher = FakeFetcher(
            {
                "https://www.zug.ch/robots.txt": FakeResult(
                    ok=True, status_code=200, content=ROBOTS
                )
            }
        )
        cache = RobotsCache(fetcher, AGENT)
        for path in ("/a", "/b", "/c"):
            await cache.allows(f"https://www.zug.ch{path}")
        assert fetcher.requested.count("https://www.zug.ch/robots.txt") == 1

    async def test_disallowed_path_is_refused_through_the_cache(self) -> None:
        fetcher = FakeFetcher(
            {
                "https://www.zug.ch/robots.txt": FakeResult(
                    ok=True, status_code=200, content=ROBOTS
                )
            }
        )
        cache = RobotsCache(fetcher, AGENT)
        allowed, reason = await cache.allows("https://www.zug.ch/intern/x")
        assert not allowed
        assert reason == "robots_disallowed"


URLSET = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.zug.ch/a</loc>
    <lastmod>2026-01-15T10:30:00Z</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
  <url><loc>https://www.zug.ch/b</loc><lastmod>2026-02-01</lastmod></url>
  <url><loc>https://www.zug.ch/c</loc></url>
</urlset>"""

INDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.zug.ch/sitemap-1.xml</loc></sitemap>
  <sitemap><loc>https://www.zug.ch/sitemap-2.xml</loc></sitemap>
</sitemapindex>"""


class TestSitemapParsing:
    def test_entries_are_extracted(self) -> None:
        parsed = parse_sitemap(URLSET)
        assert [e.url for e in parsed.entries] == [
            "https://www.zug.ch/a",
            "https://www.zug.ch/b",
            "https://www.zug.ch/c",
        ]

    def test_timestamps_are_parsed_in_several_shapes(self) -> None:
        parsed = parse_sitemap(URLSET)
        assert parsed.entries[0].last_modified is not None
        assert parsed.entries[0].last_modified.year == 2026
        assert parsed.entries[1].last_modified is not None
        assert parsed.entries[2].last_modified is None

    def test_an_index_yields_children_not_entries(self) -> None:
        parsed = parse_sitemap(INDEX)
        assert parsed.is_index
        assert len(parsed.child_sitemaps) == 2
        assert parsed.entries == ()

    def test_a_doctype_is_refused(self) -> None:
        """An internal DTD subset is the entity-expansion vector."""
        hostile = (
            b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]>'
            b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
        )
        assert parse_sitemap(hostile).error == "sitemap_contains_doctype"

    def test_malformed_xml_is_reported_not_raised(self) -> None:
        parsed = parse_sitemap(b"<urlset><url><loc>broken")
        assert parsed.error.startswith("sitemap_parse_error")

    def test_an_unexpected_root_is_reported(self) -> None:
        assert parse_sitemap(b"<html><body/></html>").error.startswith(
            "sitemap_unexpected_root"
        )

    def test_an_oversized_sitemap_is_refused(self) -> None:
        assert parse_sitemap(b"x" * (60 * 1024 * 1024)).error == "sitemap_too_large"


class TestSitemapDiscovery:
    async def test_an_index_is_walked_to_its_entries(self) -> None:
        fetcher = FakeFetcher(
            {
                "https://www.zug.ch/sitemap.xml": FakeResult(ok=True, content=INDEX),
                "https://www.zug.ch/sitemap-1.xml": FakeResult(ok=True, content=URLSET),
                "https://www.zug.ch/sitemap-2.xml": FakeResult(ok=True, content=URLSET),
            }
        )
        entries, errors = await discover(fetcher, ["https://www.zug.ch/sitemap.xml"])
        assert len(entries) == 6
        assert errors == []

    async def test_a_failed_child_is_recorded_and_the_rest_continue(self) -> None:
        fetcher = FakeFetcher(
            {
                "https://www.zug.ch/sitemap.xml": FakeResult(ok=True, content=INDEX),
                "https://www.zug.ch/sitemap-1.xml": FakeResult(ok=True, content=URLSET),
                "https://www.zug.ch/sitemap-2.xml": FakeResult(ok=False, reason="http_500"),
            }
        )
        entries, errors = await discover(fetcher, ["https://www.zug.ch/sitemap.xml"])
        assert len(entries) == 3
        assert any("http_500" in e for e in errors)

    async def test_a_cycle_terminates(self) -> None:
        """A sitemap index pointing at itself must not loop forever."""
        self_referential = (
            b'<?xml version="1.0"?>'
            b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b"<sitemap><loc>https://www.zug.ch/sitemap.xml</loc></sitemap>"
            b"</sitemapindex>"
        )
        fetcher = FakeFetcher(
            {"https://www.zug.ch/sitemap.xml": FakeResult(ok=True, content=self_referential)}
        )
        entries, _ = await discover(fetcher, ["https://www.zug.ch/sitemap.xml"])
        assert entries == []
        assert fetcher.requested.count("https://www.zug.ch/sitemap.xml") == 1
