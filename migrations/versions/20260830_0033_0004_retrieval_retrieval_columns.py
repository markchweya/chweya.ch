"""Retrieval columns: embeddings, full-text search vector and their indexes.

Adds the two arms of hybrid search to the chunks table, plus the indexes that
make them usable at scale.

Revision ID: b281fe1fef00
Revises: 0003_content
Created: 2026-08-30 00:33:04.286068+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_retrieval"
down_revision: str | None = "0003_content"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _require_pgvector() -> None:
    """Ensure the vector extension is available.

    CREATE EXTENSION requires superuser, and the application role is
    deliberately not one. So the migration creates the extension when it can
    and otherwise fails with the exact command an operator needs to run,
    rather than with a bare permission error that says nothing about the fix.
    """
    connection = op.get_bind()
    installed = connection.execute(
        sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    ).scalar()
    if installed:
        return

    try:
        connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception as exc:  # noqa: BLE001 - re-raised with an actionable message
        raise RuntimeError(
            "The pgvector extension is not installed and this role cannot create it.\n"
            "Ask a database superuser to run, once per database:\n"
            "    CREATE EXTENSION vector;\n"
            "The Docker image pgvector/pgvector:pg16 ships the extension; on a\n"
            "Debian host install postgresql-16-pgvector first.\n"
            f"Underlying error: {type(exc).__name__}"
        ) from exc


def upgrade() -> None:
    _require_pgvector()
    op.add_column(
        "chunks", sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=True)
    )
    op.add_column("chunks", sa.Column("embedding_model", sa.String(length=200), nullable=True))
    op.add_column("chunks", sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True))
    op.create_index(
        "ix_chunks_search_vector", "chunks", ["search_vector"], unique=False, postgresql_using="gin"
    )
    # HNSW for approximate nearest neighbour search. Autogenerate cannot infer
    # this: it is an index method pgvector adds, with its own operator class.
    #
    # vector_cosine_ops because embeddings are stored normalised, so cosine
    # distance is the right measure. Using L2 against normalised vectors gives
    # the same ranking but a distance whose scale is harder to reason about
    # when setting a relevance floor.
    #
    # HNSW rather than IVFFlat: IVFFlat needs training data present before the
    # index is built and degrades badly when the table grows past what it was
    # trained on. HNSW costs more to build and does not have that failure mode.
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.drop_index("ix_chunks_search_vector", table_name="chunks", postgresql_using="gin")
    op.drop_column("chunks", "search_vector")
    op.drop_column("chunks", "embedding_model")
    op.drop_column("chunks", "embedding")
