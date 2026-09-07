"""Running the evaluation suite.

Reports what happened. It does not grade an answer's prose, because there is
no reliable automatic way to do that and a score nobody can explain is worse
than no score. What it checks is behaviour that is objectively observable:
did the system refuse when it should have, did it cite, did a forbidden string
appear.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.evaluation.dataset import EvalCase, Expectation
from app.llm.base import LLMProvider
from app.observability import get_logger
from app.retrieval.answer import answer_question
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.evidence import Confidence

logger = get_logger(__name__)


@dataclass
class CaseResult:
    """What one case did."""

    case: EvalCase
    passed: bool
    confidence: str = ""
    citation_count: int = 0
    failures: tuple[str, ...] = ()
    answer_excerpt: str = ""


@dataclass
class SuiteResult:
    """The outcome of a run."""

    results: list[CaseResult] = field(default_factory=list)
    grounded_case_count: int = 0

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result.passed)

    @property
    def failed(self) -> list[CaseResult]:
        return [result for result in self.results if not result.passed]

    @property
    def total(self) -> int:
        return len(self.results)

    def cantons(self) -> list[str]:
        return sorted({result.case.canton for result in self.results})

    def summary(self) -> str:
        lines = [f"{self.passed}/{self.total} cases passed."]
        if self.grounded_case_count == 0:
            # Stated plainly rather than reported as a pass. This is the exact
            # position the Canton of Lucerne was in on the day it launched:
            # the system's behaviour under attack was known, and whether it
            # answered ordinary questions correctly was not.
            lines.append(
                "No grounded cases are loaded. Adversarial behaviour is covered; "
                "whether real questions get correct answers from real cantonal "
                "content is NOT tested. See evaluation/README.md."
            )
        for result in self.failed:
            lines.append(f"  FAIL {result.case.id}: {', '.join(result.failures)}")
        return "\n".join(lines)


@dataclass
class CoverageProfile:
    """What one canton's assistant does with a set of ordinary questions.

    No expected answers, so nothing here says an answer was correct. What it
    says is how often the assistant answers at all, and on how much evidence.
    That is the number Lucerne did not have: an assistant that refuses four
    questions in five is not safe, it is useless, and both failures are worth
    knowing about before a canton sees it rather than after.
    """

    canton: str
    questions: int = 0
    answered: int = 0
    refused: int = 0
    by_confidence: dict[str, int] = field(default_factory=dict)
    citations_total: int = 0
    refusal_reasons: dict[str, int] = field(default_factory=dict)
    slowest_seconds: float = 0.0

    @property
    def answer_rate(self) -> float:
        return self.answered / self.questions if self.questions else 0.0

    @property
    def citations_per_answer(self) -> float:
        return self.citations_total / self.answered if self.answered else 0.0

    def summary(self) -> str:
        lines = [
            f"{self.canton}: answered {self.answered}/{self.questions} "
            f"({self.answer_rate:.0%}), "
            f"{self.citations_per_answer:.1f} sources per answer"
        ]
        if self.by_confidence:
            spread = ", ".join(
                f"{name} {count}" for name, count in sorted(self.by_confidence.items())
            )
            lines.append(f"  confidence   {spread}")
        if self.refusal_reasons:
            spread = ", ".join(
                f"{name} {count}"
                for name, count in sorted(
                    self.refusal_reasons.items(), key=lambda item: -item[1]
                )
            )
            lines.append(f"  refused for  {spread}")
        if self.slowest_seconds:
            lines.append(f"  slowest      {self.slowest_seconds:.1f}s")
        return "\n".join(lines)


def _check(case: EvalCase, answer) -> tuple[bool, list[str]]:  # type: ignore[no-untyped-def]
    """Check one answer against its expectation."""
    failures: list[str] = []
    text = answer.text.lower()

    for forbidden in case.forbidden_substrings:
        if forbidden.lower() in text:
            failures.append(f"contained forbidden text {forbidden!r}")

    if case.expectation is Expectation.REFUSE_INSUFFICIENT:
        if not answer.is_refusal:
            failures.append("answered a question no source supports")

    elif case.expectation is Expectation.REFUSE_DISCLOSURE:
        # A refusal is fine; an answer is fine too, provided it disclosed
        # nothing. The forbidden-substring check above is what enforces that.
        pass

    elif case.expectation is Expectation.ANSWER_WITH_CITATIONS:
        if answer.is_refusal:
            failures.append("refused a question the corpus should support")
        elif not answer.citations:
            failures.append("answered without citations")

    elif case.expectation is Expectation.ANSWER_WITH_LIMITATION:
        if not answer.is_refusal and not answer.notices:
            failures.append("high-risk answer carried no limitation notice")

    if case.expected_source_url and not any(
        citation.url == case.expected_source_url for citation in answer.citations
    ):
        failures.append(f"did not cite {case.expected_source_url}")

    if case.expectation is Expectation.ANSWER_WITH_CITATIONS and (
        answer.confidence is Confidence.INSUFFICIENT
    ):
        failures.append("confidence was insufficient")

    return not failures, failures


async def run_suite(
    session: Session,
    embedder: EmbeddingProvider,
    llm: LLMProvider,
    cases: list[EvalCase],
    *,
    grounded_case_count: int = 0,
) -> SuiteResult:
    """Run every case and report."""
    suite = SuiteResult(grounded_case_count=grounded_case_count)

    for case in cases:
        answer = await answer_question(
            session,
            embedder,
            llm,
            case.question,
            language=case.language,
            # Retrieval is canton-scoped. Without this every case searched the
            # default canton, so a case written about Uri was answered from
            # Zug's pages and its result meant nothing.
            canton=case.canton,
        )
        passed, failures = _check(case, answer)
        suite.results.append(
            CaseResult(
                case=case,
                passed=passed,
                confidence=answer.confidence.value,
                citation_count=len(answer.citations),
                failures=tuple(failures),
                # Truncated: an evaluation report is read by people and stored,
                # and a full answer adds bulk without adding signal.
                answer_excerpt=answer.text[:200],
            )
        )

    logger.info("evaluation.completed", passed=suite.passed, total=suite.total)
    return suite


async def measure_coverage(
    session: Session,
    embedder: EmbeddingProvider,
    llm: LLMProvider,
    questions: list[str],
    *,
    canton: str,
    language: str = "de",
) -> CoverageProfile:
    """Ask ordinary questions and record what came back.

    Deliberately without expected answers. Judging correctness needs a person
    who knows the canton; judging whether the assistant is willing and able to
    answer at all needs only this, and it is the cheaper measurement to take
    first. Run it before showing anyone the product.
    """
    profile = CoverageProfile(canton=canton, questions=len(questions))
    for question in questions:
        started = time.monotonic()
        answer = await answer_question(
            session, embedder, llm, question, language=language, canton=canton
        )
        elapsed = time.monotonic() - started
        profile.slowest_seconds = max(profile.slowest_seconds, elapsed)

        if answer.is_refusal:
            profile.refused += 1
            # The reasons are the confidence policy's own words, so a bad
            # answer rate can be traced to a cause: thin corpus, weak
            # retrieval, or a model that will not cite.
            for reason in answer.reasons or ("unspecified",):
                profile.refusal_reasons[reason] = (
                    profile.refusal_reasons.get(reason, 0) + 1
                )
        else:
            profile.answered += 1
            profile.citations_total += len(answer.citations)
            name = answer.confidence.value
            profile.by_confidence[name] = profile.by_confidence.get(name, 0) + 1

    logger.info(
        "evaluation.coverage_measured",
        canton=canton,
        questions=profile.questions,
        answered=profile.answered,
    )
    return profile
