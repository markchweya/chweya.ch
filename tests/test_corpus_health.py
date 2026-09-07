"""Measuring the corpus before anyone else does.

The Canton of Lucerne switched its assistant off three days after launch. Its
finance department's reason was about the corpus, not the model: the content
was "insufficiently structured, not consistently current, and inadequately
maintained". Those three faults are countable, and counting them before a
launch is cheaper than discovering them during one.

These tests build corpora that fail each fault in turn and check the report
says so. A health report that only ever reports health is worth nothing.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app.db.models.content import (
    Chunk,
    ContentStatus,
    Document,
    DocumentVersion,
    ExtractionQuality,
    PublicationState,
    Source,
    SourceKind,
)
from app.evaluation.corpus import (
    CRAWL_OVERDUE_DAYS,
    all_cantons_health,
    canton_health,
    format_report,
)

NOW = dt.datetime(2026, 9, 7, 12, 0, tzinfo=dt.UTC)


def _source(session, canton: str, *, crawled_days_ago: int | None = 1) -> Source:
    source = Source(
        name=f"{canton} portal",
        canton=canton,
        base_url=f"https://www.{canton}.example",
        default_language="de",
        last_crawl_succeeded_at=(
            None if crawled_days_ago is None else NOW - dt.timedelta(days=crawled_days_ago)
        ),
    )
    session.add(source)
    session.flush()
    return source


def _page(
    session,
    source: Source,
    *,
    verified_days_ago: int = 1,
    quality: str = ExtractionQuality.GOOD.value,
    status: str = ContentStatus.APPROVED.value,
    publication: str = PublicationState.OFFICIAL.value,
    chunks: int = 1,
    embedded: bool = True,
) -> Document:
    document = Document(
        source_id=source.id,
        kind=SourceKind.CRAWLED_PAGE.value,
        url=f"https://www.{source.canton}.example/{uuid.uuid4().hex[:8]}",
        title="Anmeldung",
        language="de",
        publication_state=publication,
    )
    session.add(document)
    session.flush()

    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        content_hash=uuid.uuid4().hex,
        status=status,
        extracted_text="Die Anmeldung erfolgt bei der Einwohnerkontrolle.",
        extraction_quality=quality,
        retrieved_at=NOW - dt.timedelta(days=verified_days_ago),
        last_verified_at=NOW - dt.timedelta(days=verified_days_ago),
    )
    session.add(version)
    session.flush()

    for ordinal in range(chunks):
        session.add(
            Chunk(
                version_id=version.id,
                document_id=document.id,
                ordinal=ordinal,
                text="Die Anmeldung erfolgt bei der Einwohnerkontrolle.",
                language="de",
                embedding=[0.0] * 768 if embedded else None,
            )
        )

    document.current_version_id = version.id
    session.flush()
    return document


class TestAHealthyCorpus:
    @pytest.fixture
    def health(self, db):  # type: ignore[no-untyped-def]
        source = _source(db, "zug")
        for _ in range(3):
            _page(db, source, chunks=100)
        return canton_health(db, "zug", now=NOW)

    def test_every_charge_passes(self, health) -> None:  # type: ignore[no-untyped-def]
        assert [charge.verdict for charge in health.charges] == ["pass", "pass", "pass"]
        assert health.ready

    def test_it_counts_what_can_actually_be_answered_from(self, health) -> None:  # type: ignore[no-untyped-def]
        assert health.answerable_documents == 3
        assert health.chunks == 300
        assert health.chunks_embedded == 300


class TestTheThreeFaults:
    def test_stale_content_fails_the_currency_charge(self, db) -> None:  # type: ignore[no-untyped-def]
        source = _source(db, "zug")
        _page(db, source, chunks=10, verified_days_ago=2)
        _page(db, source, chunks=90, verified_days_ago=500)

        health = canton_health(db, "zug", now=NOW)
        current = next(c for c in health.charges if c.key == "current")
        assert current.verdict == "fail"
        assert health.stale_chunks == 90
        assert not health.ready

    def test_bad_extraction_fails_the_structure_charge(self, db) -> None:  # type: ignore[no-untyped-def]
        """Lucerne's exact fault: text pulled out of documents badly enough
        that answers built on it could not be relied on."""
        source = _source(db, "zug")
        _page(db, source, chunks=50)
        _page(db, source, chunks=50, quality=ExtractionQuality.LOW.value)

        health = canton_health(db, "zug", now=NOW)
        structured = next(c for c in health.charges if c.key == "structured")
        assert structured.verdict == "fail"
        assert health.poor_extraction == 50

    def test_an_uncrawled_source_fails_the_maintenance_charge(self, db) -> None:  # type: ignore[no-untyped-def]
        source = _source(db, "zug", crawled_days_ago=None)
        _page(db, source, chunks=100)

        health = canton_health(db, "zug", now=NOW)
        maintained = next(c for c in health.charges if c.key == "maintained")
        assert maintained.verdict == "fail"
        assert health.sources_never_crawled == 1

    def test_an_overdue_crawl_is_a_warning_not_a_failure(self, db) -> None:  # type: ignore[no-untyped-def]
        source = _source(db, "zug", crawled_days_ago=CRAWL_OVERDUE_DAYS + 5)
        _page(db, source, chunks=100)

        health = canton_health(db, "zug", now=NOW)
        maintained = next(c for c in health.charges if c.key == "maintained")
        assert maintained.verdict == "warn"
        assert health.ready, "a late crawl is worth saying, not worth blocking on"

    def test_unembedded_passages_fail_maintenance(self, db) -> None:  # type: ignore[no-untyped-def]
        """They are invisible to meaning search, so the index silently covers
        less than its page count suggests."""
        source = _source(db, "zug")
        _page(db, source, chunks=100, embedded=False)

        health = canton_health(db, "zug", now=NOW)
        assert health.unembedded_chunks == 100
        assert not health.ready


class TestWhatCounts:
    def test_a_draft_is_not_counted_against_the_corpus(self, db) -> None:  # type: ignore[no-untyped-def]
        """Holding a draft back is correct behaviour. Counting it as decay
        would make a careful operator look worse than a careless one."""
        source = _source(db, "zug")
        _page(db, source, chunks=100)
        _page(
            db,
            source,
            chunks=100,
            verified_days_ago=900,
            publication=PublicationState.DRAFT.value,
        )

        health = canton_health(db, "zug", now=NOW)
        assert health.chunks == 100
        assert health.stale_chunks == 0
        assert health.ready

    def test_unapproved_content_is_not_counted(self, db) -> None:  # type: ignore[no-untyped-def]
        source = _source(db, "zug")
        _page(db, source, chunks=100)
        _page(
            db,
            source,
            chunks=100,
            quality=ExtractionQuality.FAILED.value,
            status=ContentStatus.AWAITING_REVIEW.value,
        )

        health = canton_health(db, "zug", now=NOW)
        assert health.chunks == 100
        assert health.poor_extraction == 0


class TestEachCantonIsMeasuredSeparately:
    def test_one_healthy_canton_does_not_cover_for_an_empty_one(self, db) -> None:  # type: ignore[no-untyped-def]
        """The failure this prevents: showing Uri to the Canton of Uri when
        only Zug has been crawled."""
        zug = _source(db, "zug")
        _page(db, zug, chunks=100)

        reports = all_cantons_health(db, now=NOW)
        by_canton = {health.canton: health for health in reports}

        assert by_canton["zug"].ready
        assert by_canton["uri"].is_empty
        assert not by_canton["uri"].ready

    def test_an_empty_canton_says_so_in_the_report(self, db) -> None:  # type: ignore[no-untyped-def]
        report = format_report(all_cantons_health(db, now=NOW))
        assert "Nothing indexed" in report
        assert "Not ready to show a canton" in report

    def test_the_report_names_the_failing_canton(self, db) -> None:  # type: ignore[no-untyped-def]
        zug = _source(db, "zug")
        _page(db, zug, chunks=100)
        report = format_report(all_cantons_health(db, now=NOW))
        assert "uri" in report.split("Not ready to show a canton:")[1]
