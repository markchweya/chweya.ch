"""Dumi: an unofficial AI information assistant for public Canton of Zug content.

This package is deliberately layered so that each concern can be tested and
reviewed on its own:

    app.config      Validated settings loaded from the environment.
    app.db          SQLAlchemy models, session handling, migrations support.
    app.security    Password hashing, startup safety checks, authorisation.
    app.llm         The LLMProvider protocol and the Apertus implementation.
    app.ingest      Crawler, extraction and cleaning (Phase 3).
    app.retrieval   Chunking, embeddings, hybrid search (Phase 4).
    app.api         HTTP routes.
    app.cli         Operator commands such as administrator bootstrap.

Nothing in this package may answer a canton-specific factual question from
model memory. Answers are grounded in retrieved official content or the system
reports insufficient evidence.
"""

__version__ = "0.1.0"
