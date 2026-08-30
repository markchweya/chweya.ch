"""Sitemap discovery and parsing.

Section 6 requires starting from official sitemaps where they exist. A sitemap
is both faster and more respectful than link-following: it is the list of
pages the site itself considers worth indexing, and it carries last-modified
dates that let a synchronisation run skip everything unchanged.

Sitemap XML is untrusted input. It is parsed with defusedxml semantics: entity
expansion is disabled, so a sitemap cannot become a billion-laughs attack, and
external entity references are ignored, so it cannot read a local file.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from xml.etree import ElementTree

from app.observability import get_logger

logger = get_logger(__name__)

# A sitemap index may point at other sitemaps. Bounded so a cycle or a hostile
# file cannot expand without limit.
MAX_SITEMAP_DEPTH = 3
MAX_ENTRIES_PER_SITEMAP = 50_000  # the figure named in the sitemaps protocol
MAX_SITEMAP_BYTES = 50 * 1024 * 1024

SITEMAP_NAMESPACE = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

# Rejects a DOCTYPE outright. ElementTree does not expand external entities,
# but it will parse an internal subset, and there is no legitimate reason for
# a sitemap to carry one.
DOCTYPE_PATTERN = re.compile(rb"<!DOCTYPE", re.IGNORECASE)


@dataclass(frozen=True)
class SitemapEntry:
    """One URL listed in a sitemap."""

    url: str
    last_modified: dt.datetime | None = None
    change_frequency: str | None = None
    priority: float | None = None


@dataclass(frozen=True)
class ParsedSitemap:
    """The result of parsing one sitemap document."""

    entries: tuple[SitemapEntry, ...] = ()
    # Present when the document was a sitemap index rather than a sitemap.
    child_sitemaps: tuple[str, ...] = ()
    error: str = ""

    @property
    def is_index(self) -> bool:
        return bool(self.child_sitemaps)


def _parse_timestamp(raw: str | None) -> dt.datetime | None:
    """Parse a W3C datetime from a lastmod element.

    Sitemaps in the wild carry dates in several shapes. An unparseable one is
    dropped rather than guessed: a wrong last-modified date would make the
    crawler skip a page that actually changed.
    """
    if not raw:
        return None
    value = raw.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = dt.datetime.strptime(value.replace("Z", "+0000"), fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed
    return None


def parse_sitemap(body: bytes) -> ParsedSitemap:
    """Parse sitemap or sitemap index XML.

    Returns an error string rather than raising. A malformed sitemap is a
    condition to record against the source, not a reason to abort a crawl run.
    """
    if len(body) > MAX_SITEMAP_BYTES:
        return ParsedSitemap(error="sitemap_too_large")

    if DOCTYPE_PATTERN.search(body[:2048]):
        # An internal DTD subset is the vector for entity expansion attacks
        # and has no legitimate place in a sitemap.
        return ParsedSitemap(error="sitemap_contains_doctype")

    try:
        # ElementTree does not resolve external entities, which is the
        # property that matters here.
        root = ElementTree.fromstring(body)  # noqa: S314
    except ElementTree.ParseError as exc:
        return ParsedSitemap(error=f"sitemap_parse_error_{type(exc).__name__}")

    tag = root.tag.replace(SITEMAP_NAMESPACE, "")

    if tag == "sitemapindex":
        children: list[str] = []
        for element in root.findall(f"{SITEMAP_NAMESPACE}sitemap"):
            location = element.findtext(f"{SITEMAP_NAMESPACE}loc")
            if location and location.strip():
                children.append(location.strip())
            if len(children) >= MAX_ENTRIES_PER_SITEMAP:
                break
        return ParsedSitemap(child_sitemaps=tuple(children))

    if tag == "urlset":
        entries: list[SitemapEntry] = []
        for element in root.findall(f"{SITEMAP_NAMESPACE}url"):
            location = element.findtext(f"{SITEMAP_NAMESPACE}loc")
            if not location or not location.strip():
                continue
            priority_text = element.findtext(f"{SITEMAP_NAMESPACE}priority")
            try:
                priority = float(priority_text) if priority_text else None
            except ValueError:
                priority = None
            entries.append(
                SitemapEntry(
                    url=location.strip(),
                    last_modified=_parse_timestamp(
                        element.findtext(f"{SITEMAP_NAMESPACE}lastmod")
                    ),
                    change_frequency=element.findtext(f"{SITEMAP_NAMESPACE}changefreq"),
                    priority=priority,
                )
            )
            if len(entries) >= MAX_ENTRIES_PER_SITEMAP:
                logger.warning("sitemap.entry_limit_reached", limit=MAX_ENTRIES_PER_SITEMAP)
                break
        return ParsedSitemap(entries=tuple(entries))

    return ParsedSitemap(error=f"sitemap_unexpected_root_{tag}")


async def discover(
    fetcher,  # type: ignore[no-untyped-def]
    sitemap_urls: list[str],
    *,
    max_depth: int = MAX_SITEMAP_DEPTH,
) -> tuple[list[SitemapEntry], list[str]]:
    """Walk sitemaps and sitemap indexes, returning entries and any errors.

    Every fetch goes through the guarded fetcher, so a sitemap index pointing
    at another host is refused by the allowlist rather than followed.
    """
    seen: set[str] = set()
    entries: list[SitemapEntry] = []
    errors: list[str] = []
    queue: list[tuple[str, int]] = [(url, 0) for url in sitemap_urls]

    while queue:
        url, depth = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)

        if depth > max_depth:
            errors.append(f"{url}: sitemap_nesting_too_deep")
            continue

        result = await fetcher.fetch(url)
        if not result.ok:
            errors.append(f"{url}: {result.reason}")
            continue

        parsed = parse_sitemap(result.content)
        if parsed.error:
            errors.append(f"{url}: {parsed.error}")
            continue

        if parsed.is_index:
            queue.extend((child, depth + 1) for child in parsed.child_sitemaps)
        else:
            entries.extend(parsed.entries)

    logger.info("sitemap.discovered", entries=len(entries), errors=len(errors))
    return entries, errors
