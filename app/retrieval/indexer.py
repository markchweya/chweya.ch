"""Populating the retrieval columns for stored chunks.

Runs after ingestion. Kept separate from the crawler because embedding is
expensive and restartable: a crawl should not fail because a model was
unavailable, and an embedding run should be resumable without re-fetching
anything.
"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models import Chunk, ContentStatus, DocumentVersion
from app.db.models.content import DEFAULT_TEXT_SEARCH_CONFIG, TEXT_SEARCH_CONFIG
from app.observability import get_logger
from app.retrieval.embeddings import EmbeddingProvider

logger = get_logger(__name__)


def text_search_config(language: str) -> str:
    """Return the PostgreSQL text search configuration for ``language``.

    Falls back to "simple", which does no stemming, rather than to English.
    Stemming German text with English rules produces tokens that match
    nothing, which is worse than not stemming at all.
    """
    return TEXT_SEARCH_CONFIG.get((language or "").lower()[:2], DEFAULT_TEXT_SEARCH_CONFIG)


def update_search_vectors(session: Session, *, version_id=None, batch_size: int = 500) -> int:
    """Populate ``search_vector`` for chunks that lack one.

    The update runs per language group, because each group needs a different
    text search configuration and PostgreSQL cannot select one per row inside
    a single statement without a CASE over every supported language.
    """
    languages = session.execute(
        select(Chunk.language)
        .where(Chunk.search_vector.is_(None))
        .group_by(Chunk.language)
    ).scalars().all()

    total = 0
    for language in languages:
        config = text_search_config(language)
        statement = (
            update(Chunk)
            .where(Chunk.search_vector.is_(None), Chunk.language == language)
            .values(search_vector=func.to_tsvector(config, Chunk.text))
        )
        if version_id is not None:
            statement = statement.where(Chunk.version_id == version_id)
        result = session.execute(statement)
        total += result.rowcount or 0
        logger.info("index.search_vectors", language=language, config=config, rows=result.rowcount)

    return total


def embed_pending_chunks(
    session: Session,
    provider: EmbeddingProvider,
    *,
    limit: int = 500,
    only_approved: bool = True,
) -> int:
    """Embed chunks that have no vector, or whose vector came from another model.

    Re-embedding on a model change is deliberate. Vectors from two models are
    not comparable, so a mixed table returns results ranked by which model
    happened to embed each chunk.

    ``only_approved`` keeps effort on content that can actually be retrieved.
    A chunk awaiting review is embedded once it is approved, not before.
    """
    query = (
        select(Chunk)
        .where(
            (Chunk.embedding.is_(None)) | (Chunk.embedding_model != provider.model_name)
        )
        .order_by(Chunk.created_at)
        .limit(limit)
    )
    if only_approved:
        query = query.join(DocumentVersion, DocumentVersion.id == Chunk.version_id).where(
            DocumentVersion.status == ContentStatus.APPROVED.value
        )

    chunks = list(session.execute(query).scalars())
    if not chunks:
        return 0

    vectors = provider.embed_documents([chunk.text for chunk in chunks])
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk.embedding = vector
        chunk.embedding_model = provider.model_name

    logger.info(
        "index.embedded",
        chunks=len(chunks),
        model=provider.model_name,
        semantic=provider.is_semantic,
    )
    return len(chunks)


def index_version(session: Session, version_id, provider: EmbeddingProvider) -> tuple[int, int]:
    """Populate both retrieval columns for one document version."""
    search = update_search_vectors(session, version_id=version_id)
    embedded = embed_pending_chunks(session, provider, only_approved=False)
    return search, embedded
