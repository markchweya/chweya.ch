"""Run the evaluation suite.

    python -m app.cli evaluate [--grounded path/to/cases.json]

Exit code 0 when every case passes, 1 otherwise, so it can gate a deployment
or an index promotion.
"""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.db.session import session_scope
from app.evaluation.dataset import ADVERSARIAL_CASES, load_grounded_cases
from app.evaluation.runner import run_suite
from app.llm.apertus import ApertusProvider
from app.retrieval.embeddings import build_embedding_provider

DEFAULT_GROUNDED_PATH = "evaluation/grounded-cases.json"


def main(argv: list[str]) -> int:
    """Run the suite. Returns a process exit code."""
    grounded_path = DEFAULT_GROUNDED_PATH
    if "--grounded" in argv:
        index = argv.index("--grounded")
        if index + 1 < len(argv):
            grounded_path = argv[index + 1]

    grounded = load_grounded_cases(grounded_path)
    cases = [*ADVERSARIAL_CASES, *grounded]

    settings = get_settings()
    embedder = build_embedding_provider(settings)
    provider = ApertusProvider(settings)

    async def run():  # type: ignore[no-untyped-def]
        try:
            with session_scope() as session:
                return await run_suite(
                    session, embedder, provider, cases, grounded_case_count=len(grounded)
                )
        finally:
            await provider.aclose()

    suite = asyncio.run(run())
    print(suite.summary())

    if not embedder.is_semantic:
        print()
        print(
            "Note: the non-semantic embedding provider is in use, so retrieval "
            "matched on shared vocabulary rather than meaning. These results do "
            "not reflect production retrieval quality."
        )

    return 0 if not suite.failed else 1
