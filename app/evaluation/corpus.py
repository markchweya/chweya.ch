"""What state the corpus is actually in.

The Canton of Lucerne switched off its assistant three days after launch. The
reason its finance department gave was not that the model was bad: the data
the system read was "insufficiently structured, not consistently current, and
inadequately maintained", so the answers could not be relied on. The bill was
CHF 240,740 of a CHF 677,000 contract.

Nothing in that sentence is about generation. It is a statement about a
corpus, and a corpus can be measured before anyone launches anything. That is
what this module does: it counts, per canton, the three things Lucerne was
faulted for, and it says plainly which of them Dumi would currently fail.

The report is deliberately unflattering. A number an operator can show a
canton is worth having only if it would also have shown the problem.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from app.cantons import CANTONS, get_canton
from app.db.models.content import (
    Chunk,
    ContentStatus,
    CrawledUrl,
    Document,
    DocumentVersion,
    ExtractionQuality,
    PublicationState,
    Source,
)
from app.retrieval.evidence import FRESHNESS_STALE_DAYS, FRESHNESS_WARNING_DAYS

# A source that has never been crawled, or whose last crawl failed, is the
# clearest form of "inadequately maintained": the index is silently missing
# whatever that source covers, and no answer will ever say so.
CRAWL_OVERDUE_DAYS = 30

# Below this, a canton's index is too thin for the refusal rate to mean
# anything. Reported rather than enforced.
THIN_CORPUS_CHUNKS = 200

# What share of retrievable text may be stale or badly extracted before the
# corresponding Lucerne charge is counted as failed.
MAX_STALE_SHARE = 0.20
MAX_POOR_EXTRACTION_SHARE = 0.10


@dataclass
class Charge:
    """One of the three faults Lucerne named, measured."""

    key: str
    question: str
    verdict: str          # "pass", "warn" or "fail"
    detail: str

    @property
    def failed(self) -> bool:
        return self.verdict == "fail"


@dataclass
class CantonHealth:
    """The corpus behind one canton's assistant."""

    canton: str
    sources: int = 0
    sources_paused: int = 0
    sources_never_crawled: int = 0
    sources_crawl_overdue: int = 0
    documents: int = 0
    answerable_documents: int = 0
    chunks: int = 0
    chunks_embedded: int = 0
    fresh_chunks: int = 0          # verified within the warning window
    ageing_chunks: int = 0         # past the warning window, inside a year
    stale_chunks: int = 0          # past a year, or never verified
    good_extraction: int = 0
    partial_extraction: int = 0
    poor_extraction: int = 0       # low or failed
    failing_urls: int = 0
    open_contradictions: int = 0
    languages: tuple[str, ...] = ()
    oldest_verification: dt.datetime | None = None
    charges: list[Charge] = field(default_factory=list)

    @property
    def unembedded_chunks(self) -> int:
        return self.chunks - self.chunks_embedded

    def _share(self, count: int) -> float:
        return count / self.chunks if self.chunks else 0.0

    @property
    def stale_share(self) -> float:
        return self._share(self.stale_chunks + self.ageing_chunks)

    @property
    def poor_extraction_share(self) -> float:
        return self._share(self.poor_extraction)

    @property
    def is_empty(self) -> bool:
        return self.chunks == 0

    @property
    def failed_charges(self) -> list[Charge]:
        return [charge for charge in self.charges if charge.failed]

    @property
    def ready(self) -> bool:
        """Whether this canton could face the questions Lucerne could not."""
        return not self.is_empty and not self.failed_charges


def _percent(part: int, whole: int) -> str:
    return f"{(100 * part / whole):.0f}%" if whole else "n/a"


def _judge(health: CantonHealth) -> list[Charge]:
    """Score the corpus against the three faults named in Lucerne."""
    charges: list[Charge] = []

    # 1. Structured. Lucerne's text was pulled out of documents badly enough
    # that answers built on it were wrong. Dumi already downgrades confidence
    # on poor extraction, so the question is how much of the corpus that is.
    if health.is_empty:
        structured = Charge(
            "structured", "Is the text well enough extracted to answer from?",
            "fail", "Nothing is indexed for this canton.",
        )
    elif health.poor_extraction_share > MAX_POOR_EXTRACTION_SHARE:
        structured = Charge(
            "structured", "Is the text well enough extracted to answer from?",
            "fail",
            f"{_percent(health.poor_extraction, health.chunks)} of passages came "
            f"from low or failed extraction "
            f"(limit {_percent(int(MAX_POOR_EXTRACTION_SHARE * 100), 100)}).",
        )
    elif health.partial_extraction:
        structured = Charge(
            "structured", "Is the text well enough extracted to answer from?",
            "warn",
            f"{health.partial_extraction} passages came from partial extraction. "
            "Answers using them are already downgraded to medium confidence.",
        )
    else:
        structured = Charge(
            "structured", "Is the text well enough extracted to answer from?",
            "pass", f"{health.chunks} passages, all cleanly extracted.",
        )
    charges.append(structured)

    # 2. Current. This is the one that reaches a resident as a wrong deadline.
    if health.is_empty:
        current = Charge(
            "current", "Is the content current?", "fail",
            "Nothing is indexed for this canton.",
        )
    elif health.stale_share > MAX_STALE_SHARE:
        current = Charge(
            "current", "Is the content current?", "fail",
            f"{_percent(health.stale_chunks + health.ageing_chunks, health.chunks)} of "
            f"passages have not been re-checked within {FRESHNESS_WARNING_DAYS} days, "
            f"{health.stale_chunks} of them not within a year.",
        )
    elif health.stale_chunks:
        current = Charge(
            "current", "Is the content current?", "warn",
            f"{health.stale_chunks} passages have not been verified within a year. "
            "Answers using them are held to low confidence.",
        )
    else:
        current = Charge(
            "current", "Is the content current?", "pass",
            f"Every passage was verified within {FRESHNESS_WARNING_DAYS} days.",
        )
    charges.append(current)

    # 3. Maintained. A source nobody re-crawls decays into the first two.
    maintenance_faults = []
    if health.sources_never_crawled:
        maintenance_faults.append(f"{health.sources_never_crawled} never crawled")
    if health.sources_crawl_overdue:
        maintenance_faults.append(
            f"{health.sources_crawl_overdue} not crawled in {CRAWL_OVERDUE_DAYS} days"
        )
    if health.unembedded_chunks:
        maintenance_faults.append(
            f"{health.unembedded_chunks} passages never embedded, so unreachable "
            "by meaning search"
        )
    if health.failing_urls:
        maintenance_faults.append(f"{health.failing_urls} URLs failing to fetch")
    if health.open_contradictions:
        maintenance_faults.append(
            f"{health.open_contradictions} unresolved contradiction findings"
        )

    if not health.sources:
        maintained = Charge(
            "maintained", "Is the corpus being kept up?", "fail",
            "No source is configured for this canton.",
        )
    elif health.sources_never_crawled or health.unembedded_chunks:
        maintained = Charge(
            "maintained", "Is the corpus being kept up?", "fail",
            "; ".join(maintenance_faults),
        )
    elif maintenance_faults:
        maintained = Charge(
            "maintained", "Is the corpus being kept up?", "warn",
            "; ".join(maintenance_faults),
        )
    else:
        maintained = Charge(
            "maintained", "Is the corpus being kept up?", "pass",
            f"{health.sources} sources, all crawled within {CRAWL_OVERDUE_DAYS} days.",
        )
    charges.append(maintained)
    return charges


def _age_cutoffs(now: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    return (
        now - dt.timedelta(days=FRESHNESS_WARNING_DAYS),
        now - dt.timedelta(days=FRESHNESS_STALE_DAYS),
    )


def canton_health(
    session: Session, canton: str, *, now: dt.datetime | None = None
) -> CantonHealth:
    """Measure the corpus behind one canton."""
    now = now or dt.datetime.now(dt.UTC)
    warning_cutoff, stale_cutoff = _age_cutoffs(now)
    health = CantonHealth(canton=canton)

    sources = session.execute(
        select(Source).where(Source.canton == canton)
    ).scalars().all()
    health.sources = len(sources)
    overdue_cutoff = now - dt.timedelta(days=CRAWL_OVERDUE_DAYS)
    for source in sources:
        if source.is_paused:
            health.sources_paused += 1
        succeeded = source.last_crawl_succeeded_at
        if succeeded is None:
            health.sources_never_crawled += 1
        elif _aware(succeeded) < overdue_cutoff:
            health.sources_crawl_overdue += 1

    source_ids = [source.id for source in sources]
    if not source_ids:
        health.charges = _judge(health)
        return health

    # Only content that could actually reach a resident is counted. Holding
    # back a draft is correct behaviour, not corpus decay, so counting it here
    # would make a well-run index look worse than a careless one.
    answerable = (
        select(Document.id)
        .join(DocumentVersion, DocumentVersion.id == Document.current_version_id)
        .where(
            Document.source_id.in_(source_ids),
            DocumentVersion.status == ContentStatus.APPROVED.value,
            Document.publication_state.in_(
                (PublicationState.OFFICIAL.value, PublicationState.SUPPLEMENTARY.value)
            ),
        )
    )
    health.documents = session.scalar(
        select(func.count()).select_from(Document).where(Document.source_id.in_(source_ids))
    ) or 0
    health.answerable_documents = session.scalar(
        select(func.count()).select_from(answerable.subquery())
    ) or 0

    versions = (
        select(DocumentVersion.id)
        .join(Document, Document.current_version_id == DocumentVersion.id)
        .where(
            Document.source_id.in_(source_ids),
            DocumentVersion.status == ContentStatus.APPROVED.value,
            Document.publication_state.in_(
                (PublicationState.OFFICIAL.value, PublicationState.SUPPLEMENTARY.value)
            ),
        )
        .subquery()
    )

    health.chunks = session.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.version_id.in_(select(versions.c.id)))
    ) or 0
    health.chunks_embedded = session.scalar(
        select(func.count())
        .select_from(Chunk)
        .where(Chunk.version_id.in_(select(versions.c.id)), Chunk.embedding.is_not(None))
    ) or 0

    # Freshness is a property of the version, counted in passages, because a
    # passage is the unit that actually lands in an answer.
    verified = func.coalesce(DocumentVersion.last_verified_at, DocumentVersion.retrieved_at)
    rows = session.execute(
        select(
            func.count(Chunk.id),
            func.sum(func.cast(verified >= warning_cutoff, Integer)),
            func.sum(
                func.cast(
                    (verified < warning_cutoff) & (verified >= stale_cutoff), Integer
                )
            ),
            func.min(verified),
        )
        .select_from(Chunk)
        .join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
        .where(Chunk.version_id.in_(select(versions.c.id)))
    ).one()
    total, fresh, ageing, oldest = rows
    health.fresh_chunks = int(fresh or 0)
    health.ageing_chunks = int(ageing or 0)
    # Anything neither fresh nor ageing is past a year or was never dated.
    health.stale_chunks = int(total or 0) - health.fresh_chunks - health.ageing_chunks
    health.oldest_verification = oldest

    quality = session.execute(
        select(DocumentVersion.extraction_quality, func.count(Chunk.id))
        .select_from(Chunk)
        .join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
        .where(Chunk.version_id.in_(select(versions.c.id)))
        .group_by(DocumentVersion.extraction_quality)
    ).all()
    for value, count in quality:
        if value == ExtractionQuality.GOOD.value:
            health.good_extraction += count
        elif value == ExtractionQuality.PARTIAL.value:
            health.partial_extraction += count
        else:
            health.poor_extraction += count

    health.languages = tuple(
        sorted(
            language
            for (language,) in session.execute(
                select(Chunk.language)
                .where(Chunk.version_id.in_(select(versions.c.id)))
                .group_by(Chunk.language)
            ).all()
            if language
        )
    )

    health.failing_urls = session.scalar(
        select(func.count())
        .select_from(CrawledUrl)
        .where(CrawledUrl.source_id.in_(source_ids), CrawledUrl.consecutive_failures > 0)
    ) or 0

    health.open_contradictions = _open_contradictions(session, source_ids)
    health.charges = _judge(health)
    return health


def _open_contradictions(session: Session, source_ids: list) -> int:
    """Unresolved contradiction findings over this canton's passages.

    Reuses the same query the confidence policy uses, so the number in the
    report is the number that will actually qualify an answer.

    Defensive: the review schema is the part most likely to be mid-migration,
    and a health report that crashes tells an operator less than one that
    reports what it could measure.
    """
    try:
        from app.ingest.contradictions import open_findings_for_chunks

        chunk_ids = list(
            session.scalars(
                select(Chunk.id)
                .join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
                .join(Document, Document.current_version_id == DocumentVersion.id)
                .where(Document.source_id.in_(source_ids))
            ).all()
        )
        return open_findings_for_chunks(session, chunk_ids)
    except Exception:  # noqa: BLE001 - a missing column must not break the report
        return 0


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def all_cantons_health(
    session: Session, *, now: dt.datetime | None = None
) -> list[CantonHealth]:
    """Measure every canton the deployment serves."""
    return [canton_health(session, slug, now=now) for slug in sorted(CANTONS)]


def format_report(reports: list[CantonHealth]) -> str:
    """A plain-text report, written to be pasted into an email to a canton."""
    lines: list[str] = []
    for health in reports:
        canton = get_canton(health.canton)
        lines.append(f"{canton.name} ({health.canton})")
        lines.append("-" * len(f"{canton.name} ({health.canton})"))

        if health.is_empty:
            lines.append("  Nothing indexed. No question about this canton can be answered.")
            lines.append("")
            continue

        lines.append(
            f"  Sources          {health.sources} "
            f"({health.sources_paused} paused, {health.sources_never_crawled} never crawled)"
        )
        lines.append(
            f"  Documents        {health.answerable_documents} answerable "
            f"of {health.documents} held"
        )
        lines.append(
            f"  Passages         {health.chunks} "
            f"({health.chunks_embedded} embedded, {health.unembedded_chunks} not)"
        )
        lines.append(
            f"  Freshness        {_percent(health.fresh_chunks, health.chunks)} within "
            f"{FRESHNESS_WARNING_DAYS}d, "
            f"{_percent(health.ageing_chunks, health.chunks)} ageing, "
            f"{_percent(health.stale_chunks, health.chunks)} over a year or undated"
        )
        lines.append(
            f"  Extraction       {_percent(health.good_extraction, health.chunks)} good, "
            f"{_percent(health.partial_extraction, health.chunks)} partial, "
            f"{_percent(health.poor_extraction, health.chunks)} poor"
        )
        lines.append(f"  Languages        {', '.join(health.languages) or 'none'}")
        if health.chunks < THIN_CORPUS_CHUNKS:
            lines.append(
                f"  Note             Under {THIN_CORPUS_CHUNKS} passages. Too thin for a "
                "refusal rate to mean much yet."
            )
        lines.append("")
        for charge in health.charges:
            mark = {"pass": "ok  ", "warn": "warn", "fail": "FAIL"}[charge.verdict]
            lines.append(f"  [{mark}] {charge.question}")
            lines.append(f"         {charge.detail}")
        lines.append("")

    failing = [health.canton for health in reports if not health.ready]
    if failing:
        lines.append(
            "Not ready to show a canton: " + ", ".join(failing) + "."
        )
    else:
        lines.append("Every canton passes the three faults Lucerne named.")
    return "\n".join(lines)
