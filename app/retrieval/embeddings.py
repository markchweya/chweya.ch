"""Embedding providers.

Retrieval needs vectors for German, English, French and Italian, and section
10 of the brief requires a self-hosted capability: no externally hosted
embedding service. So there is one interface and two implementations.

``SentenceTransformerProvider`` is the real one. It loads a multilingual model
locally and produces semantic embeddings.

``HashingProvider`` is not semantic. It maps token hashes into a fixed vector
space, so two passages sharing words are close and two passages saying the
same thing in different words are not. It exists so the retrieval SQL, the
schema and the tests can run without a 2 GB model download, and it refuses to
be selected in production. Shipping it silently would mean a deployment that
looks like it works while answering from keyword overlap alone.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import ClassVar, Protocol, runtime_checkable

from app.config import Environment, Settings, get_settings
from app.observability import get_logger

logger = get_logger(__name__)

# Splits on anything that is not a word character. Keeps German umlauts and
# French accents, which a naive [a-z]+ pattern would discard, taking most of
# the meaning of the text with them.
TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """What retrieval requires of an embedding model."""

    @property
    def dimensions(self) -> int:
        """The length of the vectors this provider produces."""
        ...

    @property
    def model_name(self) -> str:
        """Identifier recorded alongside stored vectors.

        Stored so a later model change can be detected. Vectors from two
        different models are not comparable, and mixing them silently degrades
        every result.
        """
        ...

    @property
    def is_semantic(self) -> bool:
        """False for providers that only approximate similarity."""
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed passages for storage."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a question for search.

        Separate from embed_documents because several multilingual models are
        trained with asymmetric prefixes, where a query and a passage must be
        encoded differently to be comparable.
        """
        ...


def _normalise(vector: list[float]) -> list[float]:
    """Scale a vector to unit length.

    Retrieval uses cosine distance, and normalising once at write time means
    the database compares directions rather than magnitudes.
    """
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0.0:
        return vector
    return [value / magnitude for value in vector]


class HashingProvider:
    """A deterministic, non-semantic embedding provider.

    For tests and for running the system without a model download. Two
    passages sharing vocabulary land close together; two passages expressing
    the same idea in different words do not. That is adequate for exercising
    the retrieval SQL and useless as a search quality baseline, which is why
    :func:`build_embedding_provider` refuses it in production.
    """

    def __init__(self, dimensions: int = 768) -> None:
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def model_name(self) -> str:
        # The name says what it is, so a stored vector cannot be mistaken for
        # a semantic one when reviewing the database.
        return f"hashing-nonsemantic-{self._dimensions}"

    @property
    def is_semantic(self) -> bool:
        return False

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        tokens = TOKEN_PATTERN.findall(text.lower())
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            # The sign bit spreads tokens across the space instead of making
            # every component positive, which would make all vectors similar.
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign

        return _normalise(vector)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class SentenceTransformerProvider:
    """Local multilingual embeddings via sentence-transformers.

    The model is loaded once and reused. Loading takes seconds and several
    hundred megabytes, so a provider instance is process-wide.

    E5 and BGE family models are trained with asymmetric prefixes: a passage
    must be encoded as "passage: ..." and a question as "query: ...". Omitting
    them does not fail, it just returns noticeably worse results, which is the
    kind of degradation nobody notices until search quality is blamed on the
    retriever.
    """

    # Prefixes by model family. Matched on a substring of the model name.
    PREFIXES: ClassVar[dict[str, tuple[str, str]]] = {
        "e5": ("query: ", "passage: "),
        "bge": ("Represent this sentence for searching relevant passages: ", ""),
    }

    def __init__(self, model_name: str, dimensions: int, batch_size: int = 16) -> None:
        from sentence_transformers import SentenceTransformer

        self._model_name = model_name
        self._batch_size = batch_size
        logger.info("embeddings.loading", model=model_name)
        self._model = SentenceTransformer(model_name)

        actual = int(self._model.get_sentence_embedding_dimension() or 0)
        if actual and actual != dimensions:
            # A mismatch means the stored vectors and the column width
            # disagree, which fails at write time with a confusing error.
            # Better to say so here.
            raise ValueError(
                f"EMBEDDING_DIMENSIONS is {dimensions} but {model_name} produces {actual}. "
                "Update the setting and re-run the embedding migration."
            )
        self._dimensions = actual or dimensions

        self._query_prefix, self._passage_prefix = "", ""
        lowered = model_name.lower()
        for family, (query_prefix, passage_prefix) in self.PREFIXES.items():
            if family in lowered:
                self._query_prefix, self._passage_prefix = query_prefix, passage_prefix
                break

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def is_semantic(self) -> bool:
        return True

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        prefixed = [self._passage_prefix + text for text in texts]
        vectors = self._model.encode(
            prefixed,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [list(map(float, vector)) for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        vector = self._model.encode(
            self._query_prefix + text,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return list(map(float, vector))


class UnavailableEmbeddings:
    """Stands in when the configured embedding model could not be loaded.

    Loading a sentence-transformers model can mean downloading it, and a host
    with a cold cache behind a restricted network cannot. That is a normal
    condition for the kind of deployment this system is written for, so it
    must cost the semantic arm of retrieval, never the whole request.

    Both embed methods raise. Retrieval already treats a provider that fails
    at query time as a degraded search and continues with the keyword arm, so
    a model that failed to load takes exactly the same path as a model that
    failed to answer.
    """

    def __init__(self, reason: str, dimensions: int) -> None:
        self._reason = reason
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def model_name(self) -> str:
        return "unavailable"

    @property
    def is_semantic(self) -> bool:
        return False

    def _refuse(self) -> RuntimeError:
        return RuntimeError(f"embedding model unavailable: {self._reason}")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise self._refuse()

    def embed_query(self, text: str) -> list[float]:
        raise self._refuse()


def build_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """Return the configured provider.

    Setting EMBEDDING_MODEL to "hashing" selects the non-semantic provider.
    That is refused in production, because a deployment answering from keyword
    overlap while appearing to do semantic search is worse than one that will
    not start.
    """
    settings = settings or get_settings()

    if settings.embedding_model.strip().lower() in {"hashing", "none", "test"}:
        if settings.environment is Environment.PRODUCTION:
            raise ValueError(
                "EMBEDDING_MODEL is set to the non-semantic hashing provider, which "
                "must not be used in production. Set it to a multilingual "
                "sentence-transformers model."
            )
        logger.warning(
            "embeddings.non_semantic_provider",
            note="Retrieval will match on shared vocabulary only, not on meaning.",
        )
        return HashingProvider(dimensions=settings.embedding_dimensions)

    return SentenceTransformerProvider(
        model_name=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        batch_size=settings.embedding_batch_size,
    )
