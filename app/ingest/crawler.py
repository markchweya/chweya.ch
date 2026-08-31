"""Crawl orchestration.

Ties the guarded fetcher, robots handling, sitemap discovery, extraction,
injection scanning and chunking together, and persists the result.

The ordering of the guards is deliberate and is the part worth reviewing:

1. The source must not be paused.
2. The URL must pass the allowlist. No DNS lookup happens before this.
3. robots.txt must permit it. Checked before fetching, so a disallowed URL is
   never requested.
4. The resolved address must be public, and the connection is pinned to it.

Only then is anything fetched. Every refusal is counted by reason, so the
administration dashboard can show why URLs were skipped without storing a list
of every URL that was.

A new DocumentVersion is created only when the content hash changes. An
unchanged page costs one conditional request and no body, which is the
difference between a nightly synchronisation that is feasible and one that is
not.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, deque
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import (
    AuditAction,
    AuditOutcome,
    Chunk,
    ContentStatus,
    CrawledUrl,
    CrawlRun,
    CrawlRunState,
    Document,
    DocumentVersion,
    Source,
)
from app.db.models.content import ExtractionQuality, PublicationState, SourceKind
from app.ingest.chunking import chunk_page, chunk_pdf
from app.ingest.extract_html import extract_html, extract_links
from app.ingest.extract_pdf import extract_pdf
from app.ingest.fetcher import GuardedFetcher
from app.ingest.injection import scan as scan_for_injection
from app.ingest.robots import RobotsCache
from app.ingest.sitemap import discover as discover_sitemaps
from app.ingest.urls import evaluate
from app.observability import get_logger
from app.security.audit import record

logger = get_logger(__name__)

# Response types this pipeline knows how to extract. Anything else is recorded
# against the URL and skipped, rather than handed to a parser that cannot read
# it.
HANDLED_TYPES = {
    "text/html": "html",
    "application/xhtml+xml": "html",
    "application/pdf": "pdf",
    "text/plain": "text",
    "text/markdown": "text",
}

# Bumped when extraction changes what existing pages yield. The change
# detector compares this alongside the content digest, so a crawl after an
# extractor improvement re-processes every page even though the bytes are
# unchanged. Version 2: tables are extracted as rows.
EXTRACTION_VERSION = 2


@dataclass
class CrawlOutcome:
    """What one run did. Mirrors the counters stored on CrawlRun."""

    discovered: int = 0
    fetched: int = 0
    unchanged: int = 0
    failed: int = 0
    blocked: int = 0
    documents_created: int = 0
    versions_created: int = 0
    blocked_reasons: Counter[str] = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Crawler:
    """Runs one crawl of one source."""

    def __init__(
        self,
        session: Session,
        fetcher: GuardedFetcher,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._fetcher = fetcher
        self._settings = settings or get_settings()
        self._robots = RobotsCache(fetcher, self._settings.user_agent)

    # ----------------------------------------------------------- discovery

    async def discover_urls(
        self, source: Source
    ) -> tuple[list[str], list[str], Counter[str]]:
        """Return the URLs to consider, discovery errors, and exclusion counts.

        Sitemaps first, because they are the list the site itself considers
        worth indexing and they carry last-modified dates. Link following is a
        fallback for areas no sitemap covers.

        The exclusion counter matters for the dashboard. A sitemap entry
        dropped here never reaches crawl_url, so without counting it the
        administration view would show a URL simply vanishing between the
        sitemap and the crawl.
        """
        policy = await self._robots.policy_for(source.base_url)
        errors: list[str] = []

        sitemap_urls = list(policy.sitemaps)
        if not sitemap_urls:
            # The conventional location, tried only when robots.txt named none.
            from urllib.parse import urlsplit

            parts = urlsplit(source.base_url)
            sitemap_urls = [f"{parts.scheme}://{parts.netloc}/sitemap.xml"]

        entries, sitemap_errors = await discover_sitemaps(self._fetcher, sitemap_urls)
        errors.extend(sitemap_errors)

        urls: list[str] = []
        seen: set[str] = set()
        excluded: Counter[str] = Counter()
        for entry in entries:
            decision = evaluate(entry.url, self._settings.allowed_hosts)
            if not decision.allowed:
                excluded[decision.reason] += 1
                continue
            if not decision.normalised.startswith(source.base_url.rstrip("/")):
                # Inside the allowlist but outside this source's area.
                excluded["outside_source_area"] += 1
                continue
            if decision.normalised not in seen:
                seen.add(decision.normalised)
                urls.append(decision.normalised)

        if not urls:
            # No usable sitemap. The source's own page seeds the crawl and
            # the frontier in run() walks outward from there, following links
            # within the source's area until the page budget is spent.
            urls = [source.base_url]

        return urls, errors, excluded

    def _links_in_scope(self, html: str, base: str, source: Source) -> list[str]:
        """The links on a fetched page that this source may crawl.

        Every candidate goes through the allowlist, and links outside the
        source's base path are dropped even when the host is allowed, so
        adding a source does not quietly widen the crawl to the whole domain.
        """
        prefix = source.base_url.rstrip("/")
        found: list[str] = []
        seen: set[str] = set()
        for link in extract_links(html, base):
            decision = evaluate(link, self._settings.allowed_hosts)
            if not decision.allowed:
                continue
            if not decision.normalised.startswith(prefix):
                continue
            if decision.normalised not in seen:
                seen.add(decision.normalised)
                found.append(decision.normalised)
        return found

    # -------------------------------------------------------------- fetch

    def _url_record(self, url: str, source: Source) -> CrawledUrl:
        """Return the CrawledUrl row for ``url``, creating it if new."""
        record_row = self._session.execute(
            select(CrawledUrl).where(CrawledUrl.url == url)
        ).scalar_one_or_none()
        if record_row is None:
            record_row = CrawledUrl(url=url, source_id=source.id, first_seen_at=_utcnow())
            self._session.add(record_row)
            self._session.flush()
        return record_row

    async def crawl_url(self, url: str, source: Source, outcome: CrawlOutcome) -> list[str]:
        """Fetch, extract and persist one URL.

        Returns the in-scope links found on a fetched HTML page, so the run
        loop can extend its frontier. Every other outcome returns no links.
        """
        row = self._url_record(url, source)

        if row.is_excluded:
            outcome.blocked += 1
            outcome.blocked_reasons["administrator_excluded"] += 1
            return []

        allowed, reason = await self._robots.allows(url)
        if not allowed:
            outcome.blocked += 1
            outcome.blocked_reasons[reason] += 1
            row.last_failure_reason = reason
            return []

        # Respect a Crawl-delay the site published.
        policy = await self._robots.policy_for(url)
        if policy.crawl_delay_seconds:
            from urllib.parse import urlsplit

            host = urlsplit(url).hostname or ""
            self._fetcher.limiter.set_delay(host, policy.crawl_delay_seconds)

        result = await self._fetcher.fetch(
            url, etag=row.etag, last_modified=row.last_modified_header
        )
        row.last_fetched_at = _utcnow()

        if result.not_modified:
            # A 304 carries no body, so it also carries no links. The page's
            # children are reached through the sitemap or through other pages
            # this run does fetch.
            outcome.unchanged += 1
            row.last_failure_reason = ""
            row.consecutive_failures = 0
            self._touch_current_version(row)
            return []

        if not result.ok:
            # An allowlist or address refusal is a block; anything else is a
            # failure. The distinction matters, because blocks are policy
            # working as intended and failures are problems.
            if result.reason.startswith("http_") or result.reason in {"timeout", "response_too_large"}:
                outcome.failed += 1
            else:
                outcome.blocked += 1
                outcome.blocked_reasons[result.reason] += 1
            row.last_status_code = result.status_code
            row.last_failure_reason = result.reason
            row.consecutive_failures += 1
            return []

        outcome.fetched += 1
        row.last_status_code = result.status_code
        row.last_failure_reason = ""
        row.consecutive_failures = 0
        row.etag = result.headers.get("etag") or result.headers.get("ETag")
        row.last_modified_header = result.headers.get("last-modified") or result.headers.get(
            "Last-Modified"
        )

        handler = HANDLED_TYPES.get(result.detected_type)
        if handler is None:
            row.last_failure_reason = f"unhandled_type_{result.detected_type or 'unknown'}"
            outcome.blocked += 1
            outcome.blocked_reasons[row.last_failure_reason] += 1
            return []

        # Links come from every fetched HTML body, changed or not: an
        # unchanged hub page still leads to pages that did change.
        links: list[str] = []
        if handler == "html":
            html = result.content.decode("utf-8", errors="replace")
            links = self._links_in_scope(html, url, source)

        # Unchanged content still costs a body when the server sends no
        # validators, so the hash is the second line of defence. The stored
        # value carries the extraction version: unchanged bytes still need
        # re-processing when the extractor learned to read something new.
        digest = f"{result.digest}:v{EXTRACTION_VERSION}"
        if row.content_hash == digest:
            outcome.unchanged += 1
            self._touch_current_version(row)
            return links

        row.content_hash = digest
        row.last_changed_at = _utcnow()

        self._persist(result, row, source, handler, outcome)
        return links

    def _touch_current_version(self, row: CrawledUrl) -> None:
        """Record that the stored version was re-confirmed as current."""
        document = self._session.execute(
            select(Document).where(Document.crawled_url_id == row.id)
        ).scalar_one_or_none()
        if document is None or document.current_version_id is None:
            return
        version = self._session.get(DocumentVersion, document.current_version_id)
        if version is not None:
            version.last_verified_at = _utcnow()

    # ------------------------------------------------------------ persist

    def _persist(
        self,
        result,  # type: ignore[no-untyped-def]
        row: CrawledUrl,
        source: Source,
        handler: str,
        outcome: CrawlOutcome,
    ) -> None:
        """Extract the fetched content and store a new version with its chunks."""
        if handler == "pdf":
            extracted = extract_pdf(result.content, filename=result.url)
            title = extracted.title
            text = extracted.text
            quality = extracted.quality
            notes = list(extracted.notes)
            page_count = extracted.page_count
            language = source.default_language
            breadcrumbs: list[str] = []
            chunks = chunk_pdf(extracted, language=language)
            kind = SourceKind.CRAWLED_DOCUMENT
        else:
            html = result.content.decode("utf-8", errors="replace")
            page = extract_html(html, url=result.url)
            title = page.title
            text = page.text
            quality = (
                ExtractionQuality.GOOD if page.is_usable else ExtractionQuality.LOW
            )
            notes = [page.quality_note] if page.quality_note else []
            page_count = None
            language = page.language or source.default_language
            breadcrumbs = list(page.breadcrumbs)
            chunks = chunk_page(page, language=language)
            kind = SourceKind.CRAWLED_PAGE

        document = self._session.execute(
            select(Document).where(Document.crawled_url_id == row.id)
        ).scalar_one_or_none()
        if document is None:
            document = Document(
                source_id=source.id,
                crawled_url_id=row.id,
                kind=kind.value,
                url=row.url,
                title=title,
                media_type=result.detected_type,
                language=language,
                publication_state=PublicationState.OFFICIAL.value,
                breadcrumbs=breadcrumbs,
                department=source.department,
            )
            self._session.add(document)
            self._session.flush()
            outcome.documents_created += 1
        else:
            # Metadata can change without the body changing enough to matter.
            document.title = title or document.title
            document.language = language
            document.breadcrumbs = breadcrumbs or document.breadcrumbs

        next_number = (
            self._session.execute(
                select(func.coalesce(func.max(DocumentVersion.version_number), 0)).where(
                    DocumentVersion.document_id == document.id
                )
            ).scalar_one()
            + 1
        )

        # Everything retrieved is untrusted, including pages the canton
        # publishes. A page carrying instruction-shaped text is indexed but
        # flagged, because canton pages do legitimately contain instructions.
        injection = scan_for_injection(text)
        if injection.is_suspicious:
            logger.warning(
                "ingest.injection_flagged",
                categories=",".join(injection.categories),
                url_host=row.url.split("/")[2] if "//" in row.url else "(none)",
            )

        # Retain only the headers that matter for caching and provenance.
        # Cookies and authentication headers have no business being stored.
        useful_headers = {
            key: value
            for key, value in result.headers.items()
            if key.lower()
            in {"content-type", "etag", "last-modified", "content-length", "date"}
        }

        version = DocumentVersion(
            document_id=document.id,
            version_number=next_number,
            content_hash=result.digest,
            # Crawled canton pages are approved on ingest. Uploads and any
            # version carrying injection flags go to review instead.
            status=(
                ContentStatus.AWAITING_REVIEW.value
                if injection.is_suspicious or quality in (ExtractionQuality.LOW, ExtractionQuality.FAILED)
                else ContentStatus.APPROVED.value
            ),
            extracted_text=text,
            extraction_quality=quality.value,
            extraction_notes="; ".join(notes),
            byte_size=len(result.content),
            page_count=page_count,
            http_metadata=useful_headers,
            retrieved_at=_utcnow(),
            last_verified_at=_utcnow(),
            injection_flags=[
                {"category": f.category, "excerpt": f.excerpt} for f in injection.findings
            ],
        )
        self._session.add(version)
        self._session.flush()
        outcome.versions_created += 1

        for chunk in chunks:
            self._session.add(
                Chunk(
                    version_id=version.id,
                    document_id=document.id,
                    ordinal=chunk.ordinal,
                    text=chunk.text,
                    token_estimate=chunk.token_estimate,
                    language=chunk.language,
                    section_path=list(chunk.section_path),
                    page_number=chunk.page_number,
                    anchor=chunk.anchor,
                )
            )

        # Mark the previous version superseded rather than deleting it, so a
        # citation issued against it stays explicable.
        if document.current_version_id is not None:
            previous = self._session.get(DocumentVersion, document.current_version_id)
            if previous is not None and previous.status == ContentStatus.APPROVED.value:
                previous.status = ContentStatus.SUPERSEDED.value

        if version.status == ContentStatus.APPROVED.value:
            document.current_version_id = version.id

    # ---------------------------------------------------------------- run

    async def run(
        self,
        source: Source,
        *,
        triggered_by_id=None,
        scheduled: bool = False,
        commit_start: bool = False,
    ) -> CrawlRun:
        """Crawl one source and return the completed run record.

        ``commit_start`` commits the RUNNING row before crawling begins. The
        background runner needs that: without it, no other session can see
        that a crawl is underway, so the sources page shows nothing and a
        second process could start a duplicate run. Callers that manage
        their own transaction leave it off.
        """
        run = CrawlRun(
            source_id=source.id,
            state=CrawlRunState.RUNNING.value,
            triggered_by_id=triggered_by_id,
            is_scheduled=scheduled,
            started_at=_utcnow(),
        )
        self._session.add(run)
        self._session.flush()

        record(
            self._session,
            action=AuditAction.CRAWL_STARTED,
            actor_label="scheduler" if scheduled else f"user:{triggered_by_id or 'unknown'}",
            object_type="source",
            object_id=str(source.id),
            detail={"source_name": source.name, "scheduled": scheduled},
        )
        if commit_start:
            self._session.commit()

        outcome = CrawlOutcome()
        source.last_crawl_started_at = _utcnow()

        if source.is_paused:
            run.state = CrawlRunState.CANCELLED.value
            run.error_summary = "source is paused"
            run.finished_at = _utcnow()
            return run

        try:
            urls, errors, excluded = await self.discover_urls(source)
            outcome.errors.extend(errors)
            # Counted so the dashboard can explain the gap between what a
            # sitemap listed and what was actually crawled.
            outcome.blocked += sum(excluded.values())
            outcome.blocked_reasons.update(excluded)

            # Breadth-first from the sitemap entries, with every fetched
            # page's in-scope links joining the frontier. This is what makes
            # a source cover its whole area rather than only what the
            # sitemap lists, and the page budget is what keeps one source
            # from crawling forever.
            frontier = deque(urls)
            queued = set(urls)
            crawled = 0
            while frontier and crawled < self._settings.crawler_max_pages_per_run:
                url = frontier.popleft()
                crawled += 1
                for link in await self.crawl_url(url, source, outcome):
                    if link not in queued:
                        queued.add(link)
                        frontier.append(link)
            outcome.discovered = len(queued)

            run.state = CrawlRunState.COMPLETED.value
            source.last_crawl_succeeded_at = _utcnow()
        except Exception as exc:
            # Broad on purpose: a run has to record its own failure in the
            # database rather than propagate and leave the row saying RUNNING
            # forever. The traceback goes to the log, not to the record.
            logger.exception("crawl.run_failed", source_id=str(source.id))
            run.state = CrawlRunState.FAILED.value
            outcome.errors.append(f"run_failed: {type(exc).__name__}")

        run.finished_at = _utcnow()
        run.urls_discovered = outcome.discovered
        run.urls_fetched = outcome.fetched
        run.urls_unchanged = outcome.unchanged
        run.urls_failed = outcome.failed
        run.urls_blocked = outcome.blocked
        run.documents_created = outcome.documents_created
        run.versions_created = outcome.versions_created
        run.blocked_reasons = dict(outcome.blocked_reasons)
        run.error_summary = "\n".join(outcome.errors[:50])

        record(
            self._session,
            action=AuditAction.CRAWL_FINISHED,
            outcome=(
                AuditOutcome.SUCCESS
                if run.state == CrawlRunState.COMPLETED.value
                else AuditOutcome.FAILURE
            ),
            actor_label="scheduler" if scheduled else f"user:{triggered_by_id or 'unknown'}",
            object_type="crawl_run",
            object_id=str(run.id),
            detail={
                "fetched": outcome.fetched,
                "unchanged": outcome.unchanged,
                "failed": outcome.failed,
                "blocked": outcome.blocked,
                "versions_created": outcome.versions_created,
            },
        )

        return run
