"""Embedding providers.

Model weights cannot be downloaded in the build environment: the network
policy permits PyPI but blocks huggingface.co. sentence-transformers is
installed and the real provider is exercised here against a stub model, which
covers its own logic (dimension checking, prefix selection) without weights.
Retrieval quality with a real model is a local verification step.
"""

from __future__ import annotations

import pytest

from app.config import Environment, Settings
from app.retrieval.embeddings import (
    HashingProvider,
    SentenceTransformerProvider,
    build_embedding_provider,
)


def settings_with(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "secret_key": "test-secret-key-of-adequate-length-000000",
        "database_url": "postgresql+psycopg://u:p@localhost:5432/d",
    }
    base.update(overrides)
    # _env_file=None so this does not inherit the developer's .env.
    # Without it a test's outcome depends on an untracked local file:
    # the production-refusal test passed or failed depending on whether
    # BOOTSTRAP_ADMIN_PASSWORD happened to be set on that machine.
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


class TestHashingProvider:
    def test_dimensions_are_respected(self) -> None:
        assert len(HashingProvider(256).embed_query("test")) == 256

    def test_output_is_deterministic(self) -> None:
        """Re-embedding must not change a stored vector."""
        a = HashingProvider(128).embed_query("Anmeldung bei der Einwohnerkontrolle")
        b = HashingProvider(128).embed_query("Anmeldung bei der Einwohnerkontrolle")
        assert a == b

    def test_vectors_are_normalised(self) -> None:
        """Retrieval compares directions, so magnitude must not vary."""
        vector = HashingProvider(128).embed_query("Gebuehren fuer die Anmeldung")
        magnitude = sum(v * v for v in vector) ** 0.5
        assert abs(magnitude - 1.0) < 1e-6

    def test_shared_vocabulary_scores_higher_than_unrelated_text(self) -> None:
        provider = HashingProvider(512)
        target = provider.embed_documents(["Die Anmeldung kostet CHF 20 pro Person"])[0]
        near = provider.embed_query("Was kostet die Anmeldung")
        far = provider.embed_query("Sperrgut Abholung Kubikmeter")
        assert sum(a * b for a, b in zip(target, near, strict=True)) > sum(
            a * b for a, b in zip(target, far, strict=True)
        )

    def test_umlauts_and_accents_survive_tokenisation(self) -> None:
        """A naive [a-z]+ pattern discards them, and most of the meaning."""
        provider = HashingProvider(256)
        assert provider.embed_query("Gebühren") != provider.embed_query("Gebhren")
        assert provider.embed_query("délai") != provider.embed_query("dlai")

    def test_empty_text_yields_a_zero_vector_without_raising(self) -> None:
        assert HashingProvider(64).embed_query("") == [0.0] * 64

    def test_it_declares_itself_non_semantic(self) -> None:
        provider = HashingProvider(128)
        assert provider.is_semantic is False
        # The name must make this visible when reading stored rows.
        assert "nonsemantic" in provider.model_name


class TestProviderSelection:
    def test_hashing_is_available_in_development(self) -> None:
        provider = build_embedding_provider(
            settings_with(embedding_model="hashing", environment=Environment.DEVELOPMENT)
        )
        assert not provider.is_semantic

    def test_hashing_is_refused_in_production(self) -> None:
        """A deployment answering from keyword overlap while appearing to do
        semantic search is worse than one that will not start."""
        with pytest.raises(ValueError, match="must not be used in production"):
            build_embedding_provider(
                settings_with(
                    embedding_model="hashing",
                    environment=Environment.PRODUCTION,
                    debug=False,
                    public_base_url="https://dumi.example.ch",
                    database_url="postgresql+psycopg://u:a-long-real-password@db:5432/d",
                    session_cookie_secure=True,
                    crawler_contact="ops@example.ch",
                    malware_scanner_command="clamdscan",
                )
            )


class StubModel:
    """Stands in for a loaded SentenceTransformer."""

    def __init__(self, dimensions: int) -> None:
        self._dimensions = dimensions
        self.encoded: list[str] = []

    def get_sentence_embedding_dimension(self) -> int:
        return self._dimensions

    def encode(self, text, **kwargs):  # type: ignore[no-untyped-def]
        items = text if isinstance(text, list) else [text]
        self.encoded.extend(items)
        vector = [0.0] * self._dimensions
        vector[0] = 1.0
        return [vector for _ in items] if isinstance(text, list) else vector


@pytest.fixture
def stub_transformer(monkeypatch):  # type: ignore[no-untyped-def]
    """Patch SentenceTransformer so no weights are downloaded."""
    created: dict[str, StubModel] = {}

    def make(name: str, dimensions: int = 384):  # type: ignore[no-untyped-def]
        model = StubModel(dimensions)
        created["model"] = model

        import app.retrieval.embeddings as module

        class Fake:
            def __init__(self, model_name: str) -> None:
                pass

            def __new__(cls, model_name: str):  # type: ignore[no-untyped-def]
                return model

        monkeypatch.setattr(
            module, "SentenceTransformerProvider", module.SentenceTransformerProvider
        )
        import sentence_transformers

        monkeypatch.setattr(sentence_transformers, "SentenceTransformer", Fake)
        return created

    return make


class TestSentenceTransformerProvider:
    def test_a_dimension_mismatch_is_refused_with_an_explanation(self, stub_transformer) -> None:  # type: ignore[no-untyped-def]
        """Otherwise it fails at write time with a confusing column error."""
        stub_transformer("any-model", dimensions=384)
        with pytest.raises(ValueError, match="produces 384"):
            SentenceTransformerProvider("any-model", dimensions=768)

    def test_e5_prefixes_are_applied(self, stub_transformer) -> None:  # type: ignore[no-untyped-def]
        """E5 models need asymmetric prefixes. Omitting them does not fail,
        it just returns worse results, which nobody notices until search
        quality gets blamed on the retriever."""
        created = stub_transformer("intfloat/multilingual-e5-base", dimensions=384)
        provider = SentenceTransformerProvider("intfloat/multilingual-e5-base", 384)
        provider.embed_documents(["Die Anmeldung kostet CHF 20"])
        provider.embed_query("Was kostet die Anmeldung")

        encoded = created["model"].encoded
        assert any(text.startswith("passage: ") for text in encoded)
        assert any(text.startswith("query: ") for text in encoded)

    def test_a_model_without_known_prefixes_gets_none(self, stub_transformer) -> None:  # type: ignore[no-untyped-def]
        created = stub_transformer("some/plain-model", dimensions=384)
        provider = SentenceTransformerProvider("some/plain-model", 384)
        provider.embed_query("test")
        assert created["model"].encoded == ["test"]

    def test_it_declares_itself_semantic(self, stub_transformer) -> None:  # type: ignore[no-untyped-def]
        stub_transformer("some/plain-model", dimensions=384)
        assert SentenceTransformerProvider("some/plain-model", 384).is_semantic
