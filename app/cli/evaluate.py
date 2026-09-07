"""Run the evaluation suite.

    python -m app.cli evaluate [--grounded path/to/cases.json] [--canton uri]
    python -m app.cli evaluate --coverage [--canton uri] [--questions path.json]

Two modes, and the difference matters.

The default mode runs the adversarial cases, which assert behaviour that must
hold whatever is indexed, plus any grounded cases an operator has written. It
gates a deployment: exit code 0 when every case passes, 1 otherwise.

``--coverage`` asks a set of ordinary resident questions and reports what came
back: how often the assistant answered, on how many sources, at what
confidence, and where the refusals came from. It asserts nothing, so it never
fails the build. It exists because the Canton of Lucerne launched an assistant
without that number and switched it off three days later.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys

from app.cantons import CANTONS, normalise_canton
from app.config import get_settings
from app.db.session import session_scope
from app.evaluation.dataset import adversarial_cases_for, load_grounded_cases
from app.evaluation.runner import measure_coverage, run_suite
from app.llm.apertus import ApertusProvider
from app.retrieval.embeddings import build_embedding_provider

DEFAULT_GROUNDED_PATH = "evaluation/grounded-cases.json"
DEFAULT_QUESTIONS_PATH = "evaluation/resident-questions.json"


def _option(argv: list[str], name: str) -> str | None:
    if name not in argv:
        return None
    index = argv.index(name)
    return argv[index + 1] if index + 1 < len(argv) else None


def _cantons(argv: list[str]) -> list[str] | None:
    """Which cantons to run against. Every configured one by default."""
    value = _option(argv, "--canton")
    if value is None:
        return sorted(CANTONS)
    slug = normalise_canton(value)
    if slug not in CANTONS:
        print(
            f"Unknown canton {value!r}. Known: {', '.join(sorted(CANTONS))}.",
            file=sys.stderr,
        )
        return None
    return [slug]


def _load_questions(path: str) -> tuple[list[str], str]:
    file = pathlib.Path(path)
    if not file.exists():
        return [], "de"
    raw = json.loads(file.read_text(encoding="utf-8"))
    return list(raw.get("questions", [])), raw.get("language", "de")


def _coverage(argv: list[str], cantons: list[str]) -> int:
    questions, language = _load_questions(
        _option(argv, "--questions") or DEFAULT_QUESTIONS_PATH
    )
    if not questions:
        print("No questions loaded. Nothing to measure.", file=sys.stderr)
        return 2

    settings = get_settings()
    embedder = build_embedding_provider(settings)
    provider = ApertusProvider(settings)

    async def run():  # type: ignore[no-untyped-def]
        try:
            profiles = []
            with session_scope() as session:
                for canton in cantons:
                    profiles.append(
                        await measure_coverage(
                            session,
                            embedder,
                            provider,
                            questions,
                            canton=canton,
                            language=language,
                            max_context_tokens=settings.apertus_max_context_tokens,
                            max_output_tokens=settings.apertus_max_output_tokens,
                        )
                    )
            return profiles
        finally:
            await provider.aclose()

    profiles = asyncio.run(run())
    print(f"{len(questions)} resident questions, language {language}.\n")
    for profile in profiles:
        print(profile.summary())
        print()

    print(
        "This says how often an answer was produced and how well evidenced it "
        "was.\nIt does NOT say whether any answer was correct. For that, write "
        "grounded\ncases from captured pages: see evaluation/README.md."
    )
    # Never fails the build: a low answer rate is a finding, not a regression.
    return 0


def main(argv: list[str]) -> int:
    """Run the suite. Returns a process exit code."""
    cantons = _cantons(argv)
    if cantons is None:
        return 2

    if "--coverage" in argv:
        return _coverage(argv, cantons)

    grounded_path = _option(argv, "--grounded") or DEFAULT_GROUNDED_PATH
    grounded = [
        case for case in load_grounded_cases(grounded_path) if case.canton in cantons
    ]
    cases = [case for canton in cantons for case in adversarial_cases_for(canton)]
    cases.extend(grounded)

    settings = get_settings()
    embedder = build_embedding_provider(settings)
    provider = ApertusProvider(settings)

    async def run():  # type: ignore[no-untyped-def]
        try:
            with session_scope() as session:
                return await run_suite(
                    session,
                    embedder,
                    provider,
                    cases,
                    grounded_case_count=len(grounded),
                    # The window the provider actually serves. Left at the
                    # library default, every prompt was built for 8192 tokens
                    # against a 4096-token model and each case came back as
                    # LLMRequestTooLarge.
                    max_context_tokens=settings.apertus_max_context_tokens,
                    max_output_tokens=settings.apertus_max_output_tokens,
                )
        finally:
            await provider.aclose()

    suite = asyncio.run(run())
    print(f"Cantons: {', '.join(cantons)}")
    print(suite.summary())

    if not embedder.is_semantic:
        print()
        print(
            "Note: the non-semantic embedding provider is in use, so retrieval "
            "matched on shared vocabulary rather than meaning. These results do "
            "not reflect production retrieval quality."
        )

    return 0 if not suite.failed else 1


__all__ = ["DEFAULT_GROUNDED_PATH", "DEFAULT_QUESTIONS_PATH", "main"]
