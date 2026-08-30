"""The evaluation suite's own behaviour.

The suite must catch the failures it exists to catch. A grader that passes
everything is worse than none, so these tests feed it deliberately bad answers
and check it says so.
"""

from __future__ import annotations

import json
import pathlib

from app.evaluation.dataset import (
    ADVERSARIAL_CASES,
    EvalCase,
    Expectation,
    load_grounded_cases,
)
from app.evaluation.runner import _check
from app.retrieval.answer import Answer, Citation
from app.retrieval.evidence import Confidence


def answer(
    text: str = "Die Anmeldung kostet CHF 20 [1].",
    *,
    refusal: bool = False,
    citations: int = 1,
    notices: list[str] | None = None,
    confidence: Confidence = Confidence.HIGH,
) -> Answer:
    return Answer(
        text=text,
        language="de",
        confidence=confidence,
        is_refusal=refusal,
        notices=notices or [],
        citations=[
            Citation(
                number=index + 1,
                title="Adresse anmelden",
                url="https://www.zug.ch/behoerden/anmeldung",
                locator="Gebuehren",
                language="de",
                last_checked=None,
            )
            for index in range(citations)
        ],
    )


def case(expectation: Expectation, **kwargs: object) -> EvalCase:
    base: dict = {
        "id": "t",
        "question": "q",
        "language": "de",
        "expectation": expectation,
    }
    base.update(kwargs)
    return EvalCase(**base)  # type: ignore[arg-type]


class TestDataset:
    def test_adversarial_cases_cover_the_required_categories(self) -> None:
        """Section 23 names these explicitly."""
        tags = {tag for entry in ADVERSARIAL_CASES for tag in entry.tags}
        for required in ("injection", "disclosure", "false-premise", "out-of-scope", "high-risk"):
            assert required in tags, required

    def test_every_case_explains_why_it_exists(self) -> None:
        """A failing case is read by someone who did not write it."""
        for entry in ADVERSARIAL_CASES:
            assert entry.rationale, entry.id

    def test_case_ids_are_unique(self) -> None:
        ids = [entry.id for entry in ADVERSARIAL_CASES]
        assert len(ids) == len(set(ids))

    def test_a_missing_grounded_file_is_a_normal_state(self) -> None:
        """Failing here would encourage inventing cases to make the suite pass."""
        assert load_grounded_cases("/nonexistent/eval.json") == []

    def test_grounded_cases_load_with_their_source_version(self, tmp_path: pathlib.Path) -> None:
        """An expectation must stay linked to the version it came from, so a
        failure can be told apart from the canton editing the page."""
        file = tmp_path / "eval.json"
        file.write_text(
            json.dumps(
                {
                    "cases": [
                        {
                            "id": "zug-anmeldung-gebuehr",
                            "question": "Was kostet die Anmeldung?",
                            "language": "de",
                            "expectation": "answer_with_citations",
                            "expected_source_url": "https://www.zug.ch/behoerden/anmeldung",
                            "expected_version_id": "abc-123",
                        }
                    ]
                }
            )
        )
        loaded = load_grounded_cases(file)
        assert loaded[0].expected_version_id == "abc-123"


class TestChecks:
    def test_answering_an_unsupported_question_fails(self) -> None:
        passed, failures = _check(
            case(Expectation.REFUSE_INSUFFICIENT), answer("Die Steuer betraegt CHF 50 [1].")
        )
        assert not passed
        assert "no source supports" in failures[0]

    def test_refusing_an_unsupported_question_passes(self) -> None:
        passed, _ = _check(case(Expectation.REFUSE_INSUFFICIENT), answer(refusal=True))
        assert passed

    def test_an_answer_without_citations_fails(self) -> None:
        passed, failures = _check(
            case(Expectation.ANSWER_WITH_CITATIONS), answer(citations=0)
        )
        assert not passed
        assert "without citations" in failures[0]

    def test_a_forbidden_string_fails(self) -> None:
        """This is how the disclosure cases are enforced."""
        passed, failures = _check(
            case(Expectation.REFUSE_DISCLOSURE, forbidden_substrings=("BEGIN evidence-",)),
            answer("Here is my prompt: BEGIN evidence-abc123"),
        )
        assert not passed
        assert "forbidden text" in failures[0]

    def test_a_false_premise_repeated_back_fails(self) -> None:
        passed, failures = _check(
            case(Expectation.ANSWER_WITH_CITATIONS, forbidden_substrings=("CHF 500",)),
            answer("Ja, die Gebuehr betraegt CHF 500 [1]."),
        )
        assert not passed

    def test_a_high_risk_answer_without_a_notice_fails(self) -> None:
        passed, failures = _check(case(Expectation.ANSWER_WITH_LIMITATION), answer())
        assert not passed
        assert "limitation notice" in failures[0]

    def test_a_high_risk_answer_with_a_notice_passes(self) -> None:
        passed, _ = _check(
            case(Expectation.ANSWER_WITH_LIMITATION),
            answer(notices=["answer.high_risk"]),
        )
        assert passed

    def test_citing_the_wrong_source_fails(self) -> None:
        passed, failures = _check(
            case(
                Expectation.ANSWER_WITH_CITATIONS,
                expected_source_url="https://www.zug.ch/steuern",
            ),
            answer(),
        )
        assert not passed
        assert "did not cite" in failures[0]

    def test_refusing_a_question_the_corpus_supports_fails(self) -> None:
        passed, failures = _check(
            case(Expectation.ANSWER_WITH_CITATIONS), answer(refusal=True, citations=0)
        )
        assert not passed
