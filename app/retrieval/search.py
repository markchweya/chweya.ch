"""Hybrid retrieval.

Two arms, combined by reciprocal rank fusion:

* Semantic, over pgvector, which finds passages that mean the same thing in
  different words. That matters here because a resident asks "wie melde ich
  mich an" and the page says "Anmeldung bei der Einwohnerkontrolle".
* Keyword, over tsvector, which finds exact terms. That matters because
  administrative language is full of precise nouns, form numbers and legal
  references that a semantic model happily blurs into something similar and
  wrong.

Neither is sufficient alone. Semantic search alone returns a plausible page
about a different service; keyword search alone misses everything phrased
differently from the question.

Only approved content is ever returned. That is enforced in SQL rather than by
filtering afterwards, because a filter applied after ranking is a filter
somebody eventually forgets to apply.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Text, and_, case, func, or_, select, true
from sqlalchemy.dialects.postgresql import TSQUERY as TSVECTOR_QUERY
from sqlalchemy.orm import Session

from app.db.models import Chunk, ContentStatus, Document, DocumentVersion, Source
from app.db.models.content import PublicationState
from app.observability import get_logger
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.indexer import text_search_config

logger = get_logger(__name__)

# Publication states that may be returned to the public. Draft and internal
# documents never are, whatever their review status says. Section 16 requires
# that separation.
PUBLIC_STATES = (PublicationState.OFFICIAL.value, PublicationState.SUPPLEMENTARY.value)

# Maximum cosine distance for a semantic hit to count as relevant.
#
# This threshold is the difference between a system that says "I could not
# verify that" and one that never says it. Vector search returns its k nearest
# neighbours whatever the distance, so without a floor a question about dog
# tax in Reykjavik retrieves the closest Zug pages, the evidence set is
# non-empty, and the model is asked to answer from passages that have nothing
# to do with the question.
#
# 0.62 on normalised vectors corresponds to a cosine similarity of about 0.38.
# It is a starting value, not a tuned one: it needs calibrating against a real
# embedding model and real Zug content, which is recorded in the Phase 4
# report as an open task.
MAX_SEMANTIC_DISTANCE = 0.62

# Reciprocal rank fusion constant. 60 is the value from the original paper and
# is deliberately large: it flattens the difference between ranks 1 and 2 so
# that a passage found by both arms outranks one found first by only one.
RRF_K = 60


@dataclass
class RetrievedChunk:
    """One candidate passage with everything a citation needs.

    Carries its own provenance so an answer can be assembled without going
    back to the database per chunk.
    """

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    version_id: uuid.UUID
    text: str
    language: str
    section_path: tuple[str, ...]
    page_number: int | None
    anchor: str | None
    document_title: str
    document_url: str | None
    document_language: str
    department: str | None
    retrieved_at: object = None
    last_verified_at: object = None
    published_at: object = None
    extraction_quality: str = "good"
    injection_flagged: bool = False

    # Scoring. Kept separate so the confidence policy can see how a passage
    # was found, not only how highly it scored.
    semantic_rank: int | None = None
    # Cosine distance from the question. Kept so the confidence policy can see
    # how close the match actually was, not only where it ranked.
    semantic_distance: float | None = None
    keyword_rank: int | None = None
    fused_score: float = 0.0

    @property
    def found_by_both(self) -> bool:
        """True when both arms returned this passage.

        A strong signal: the wording matches and the meaning matches.
        """
        return self.semantic_rank is not None and self.keyword_rank is not None

    @property
    def citation_anchor(self) -> str:
        """A short human-readable locator within the document.

        The leading section is dropped when it repeats the document title,
        which it usually does: a page's h1 and its title element normally say
        the same thing, and a citation reading "Adresse anmelden — Adresse
        anmelden > Gebuehren" looks careless.
        """
        if self.page_number is not None:
            return f"page {self.page_number}"
        if not self.section_path:
            return ""

        path = list(self.section_path)
        title = (self.document_title or "").strip().lower()
        if path and title and path[0].strip().lower() == title:
            path = path[1:]
        return " > ".join(path)


@dataclass
class SearchResult:
    """The outcome of one retrieval."""

    chunks: list[RetrievedChunk] = field(default_factory=list)
    semantic_available: bool = True
    # Populated when the semantic arm could not run, so the caller can lower
    # confidence rather than silently answering from keyword matches alone.
    degraded_reason: str = ""


def _base_query(canton: str | None = None):  # type: ignore[no-untyped-def]
    """Chunks eligible for retrieval, joined to their document and version.

    The eligibility rules live here so both arms share exactly one definition
    of what may be returned.
    """
    return (
        select(
            Chunk.id,
            Chunk.document_id,
            Chunk.version_id,
            Chunk.text,
            Chunk.language,
            Chunk.section_path,
            Chunk.page_number,
            Chunk.anchor,
            Document.title,
            Document.url,
            Document.language.label("document_language"),
            Document.department,
            Document.published_at,
            DocumentVersion.retrieved_at,
            DocumentVersion.last_verified_at,
            DocumentVersion.extraction_quality,
            DocumentVersion.injection_flags,
        )
        .join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
        .join(Document, Document.id == Chunk.document_id)
        .outerjoin(Source, Source.id == Document.source_id)
        .where(
            # Only the canton being served. A document without a source, an
            # administrator upload, is visible in every canton.
            or_(Source.canton == canton, Document.source_id.is_(None))
            if canton
            else true(),
            # Only the version currently in force for its document.
            Document.current_version_id == DocumentVersion.id,
            DocumentVersion.status == ContentStatus.APPROVED.value,
            Document.publication_state.in_(PUBLIC_STATES),
        )
    )


def _row_to_chunk(row) -> RetrievedChunk:  # type: ignore[no-untyped-def]
    return RetrievedChunk(
        chunk_id=row.id,
        document_id=row.document_id,
        version_id=row.version_id,
        text=row.text,
        language=row.language,
        section_path=tuple(row.section_path or ()),
        page_number=row.page_number,
        anchor=row.anchor,
        document_title=row.title,
        document_url=row.url,
        document_language=row.document_language,
        department=row.department,
        retrieved_at=row.retrieved_at,
        last_verified_at=row.last_verified_at,
        published_at=row.published_at,
        extraction_quality=row.extraction_quality,
        injection_flagged=bool(row.injection_flags),
    )


def semantic_search(
    session: Session,
    provider: EmbeddingProvider,
    question: str,
    *,
    limit: int = 20,
    languages: tuple[str, ...] | None = None,
    canton: str | None = None,
    max_distance: float = MAX_SEMANTIC_DISTANCE,
) -> list[RetrievedChunk]:
    """Rank passages by embedding distance, discarding distant ones.

    The distance filter is what makes insufficient-evidence reachable. Without
    it the arm always returns its k nearest neighbours, so no question ever
    produces an empty evidence set.
    """
    vector = provider.embed_query(question)

    query = _base_query(canton).where(
        Chunk.embedding.is_not(None),
        # Only vectors from the current model. A chunk embedded by a previous
        # model is not comparable and would be ranked against a different
        # geometry.
        Chunk.embedding_model == provider.model_name,
    )
    if languages:
        query = query.where(Chunk.language.in_(languages))

    distance = Chunk.embedding.cosine_distance(vector)
    query = (
        query.add_columns(distance.label("distance"))
        .where(distance < max_distance)
        .order_by(distance)
        .limit(limit)
    )

    results: list[RetrievedChunk] = []
    for rank, row in enumerate(session.execute(query), start=1):
        chunk = _row_to_chunk(row)
        chunk.semantic_rank = rank
        chunk.semantic_distance = float(row.distance)
        results.append(chunk)
    return results


def keyword_search(
    session: Session,
    question: str,
    *,
    limit: int = 20,
    languages: tuple[str, ...] | None = None,
    canton: str | None = None,
) -> list[RetrievedChunk]:
    """Rank passages by full-text match.

    The query is parsed with websearch_to_tsquery, which accepts what a person
    actually types, including quoted phrases and "or", and never raises on
    punctuation. plainto_tsquery discards phrase structure, and to_tsquery
    raises on input a resident could plausibly type.

    Each language is matched with the configuration its column was indexed
    with. A chunk has exactly one language, so the rank is a CASE over that
    column and needs no grouping.
    """
    search_languages = languages or ("de", "en", "fr", "it")

    match_branches = []
    rank_branches = []
    for language in search_languages:
        tsquery = func.websearch_to_tsquery(text_search_config(language), question)
        match_branches.append(
            and_(Chunk.language == language, Chunk.search_vector.op("@@")(tsquery))
        )
        # ts_rank_cd rather than ts_rank: it accounts for how close the matched
        # terms are to each other, which separates a page mentioning
        # "Gebuehr" and "Anmeldung" in one sentence from one mentioning them
        # chapters apart.
        rank_branches.append(
            (Chunk.language == language, func.ts_rank_cd(Chunk.search_vector, tsquery))
        )

    if not match_branches:
        return []

    rank_expression = case(*rank_branches, else_=0.0)

    query = (
        _base_query(canton)
        .where(or_(*match_branches))
        .order_by(rank_expression.desc())
        .limit(limit)
    )

    results = _run_keyword_query(session, query)
    if results:
        return results

    # websearch_to_tsquery joins terms with AND, so a question carrying one
    # term the corpus does not use returns nothing at all. "Einwohnerkontrolle
    # Frist" finds no page when the page says Einwohnerkontrolle but not
    # Frist, even though it is the right page.
    #
    # Retry with OR only when the strict query found nothing. Running it always
    # would flood the arm with pages matching one common word, and fusion would
    # then rank those against genuine matches. As a fallback it costs one extra
    # query on the questions that would otherwise return nothing.
    return _run_keyword_query(
        session, _any_term_query(question, search_languages, limit, canton)
    )


def _run_keyword_query(session: Session, query) -> list[RetrievedChunk]:  # type: ignore[no-untyped-def]
    """Execute a keyword query and attach ranks."""
    results: list[RetrievedChunk] = []
    for rank, row in enumerate(session.execute(query), start=1):
        chunk = _row_to_chunk(row)
        chunk.keyword_rank = rank
        results.append(chunk)
    return results


def _any_term_query(question: str, languages: tuple[str, ...], limit: int, canton: str | None = None):  # type: ignore[no-untyped-def]
    """Build a query matching any term rather than all of them."""
    match_branches = []
    rank_branches = []
    for language in languages:
        config = text_search_config(language)
        # Replace the AND operators websearch_to_tsquery produced with OR.
        tsquery = func.replace(
            func.websearch_to_tsquery(config, question).cast(Text), " & ", " | "
        ).cast(TSVECTOR_QUERY)
        match_branches.append(
            and_(Chunk.language == language, Chunk.search_vector.op("@@")(tsquery))
        )
        rank_branches.append(
            (Chunk.language == language, func.ts_rank_cd(Chunk.search_vector, tsquery))
        )

    rank_expression = case(*rank_branches, else_=0.0)
    return (
        _base_query(canton)
        .where(or_(*match_branches))
        .order_by(rank_expression.desc())
        .limit(limit)
    )


def fuse(
    semantic: list[RetrievedChunk],
    keyword: list[RetrievedChunk],
    *,
    limit: int = 12,
) -> list[RetrievedChunk]:
    """Combine two ranked lists by reciprocal rank fusion.

    RRF rather than a weighted score sum, because the two arms produce scores
    on incomparable scales: a cosine distance and a ts_rank_cd value cannot be
    added without inventing a weighting that has no principled basis. RRF uses
    only the ranks, which are comparable by construction.
    """
    merged: dict[uuid.UUID, RetrievedChunk] = {}

    for chunk in semantic:
        merged[chunk.chunk_id] = chunk

    for chunk in keyword:
        existing = merged.get(chunk.chunk_id)
        if existing is None:
            merged[chunk.chunk_id] = chunk
        else:
            existing.keyword_rank = chunk.keyword_rank

    for chunk in merged.values():
        score = 0.0
        if chunk.semantic_rank is not None:
            score += 1.0 / (RRF_K + chunk.semantic_rank)
        if chunk.keyword_rank is not None:
            score += 1.0 / (RRF_K + chunk.keyword_rank)
        chunk.fused_score = score

    ordered = sorted(merged.values(), key=lambda c: c.fused_score, reverse=True)
    return ordered[:limit]


def search(
    session: Session,
    provider: EmbeddingProvider,
    question: str,
    *,
    limit: int = 12,
    per_arm: int = 20,
    languages: tuple[str, ...] | None = None,
    canton: str | None = None,
) -> SearchResult:
    """Run both arms and fuse the results.

    A semantic failure degrades to keyword-only rather than failing the
    request, but it is reported so the confidence policy can account for it.
    Answering from keyword matches alone while presenting the usual confidence
    would be the dishonest option.
    """
    result = SearchResult()

    try:
        semantic = semantic_search(
            session, provider, question, limit=per_arm, languages=languages, canton=canton
        )
    except Exception as exc:  # noqa: BLE001
        # Broad on purpose: a model that fails to load, or a vector dimension
        # mismatch, must not take down search entirely.
        logger.warning("search.semantic_failed", error=type(exc).__name__)
        semantic = []
        result.semantic_available = False
        result.degraded_reason = f"semantic_unavailable_{type(exc).__name__}"

    keyword = keyword_search(
        session, question, limit=per_arm, languages=languages, canton=canton
    )

    if not semantic and result.semantic_available:
        # No vectors matched. Usually means nothing has been embedded yet,
        # which is worth distinguishing from a model failure.
        result.semantic_available = bool(
            session.execute(
                select(func.count()).select_from(Chunk).where(Chunk.embedding.is_not(None))
            ).scalar_one()
        )
        if not result.semantic_available:
            result.degraded_reason = "no_embeddings_present"

    result.chunks = fuse(semantic, keyword, limit=limit)
    logger.info(
        "search.completed",
        semantic_hits=len(semantic),
        keyword_hits=len(keyword),
        fused=len(result.chunks),
        degraded=result.degraded_reason or "no",
    )
    return result
