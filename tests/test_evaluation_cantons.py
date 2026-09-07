"""Every canton served has to be evaluated, not just the default one.

The bug this pins: retrieval is canton-scoped, but the evaluation suite never
passed a canton, so every case searched Zug. A case written about Uri was
answered from Zug's pages and its result meant nothing. Adding a second canton
to the product silently halved what the suite covered, which is the worst kind
of gap because the suite kept reporting green.
"""

from __future__ import annotations

import pytest

from app.cantons import CANTONS, DEFAULT_CANTON
from app.evaluation.dataset import (
    ADVERSARIAL_CASES,
    Expectation,
    adversarial_cases_for,
    load_grounded_cases,
)
from app.evaluation.runner import (
    CaseResult,
    CoverageProfile,
    SuiteResult,
    _check,
    measure_coverage,
    run_suite,
)
from app.retrieval.answer import Answer
from app.retrieval.evidence import Confidence


class TestAdversarialCasesCoverEveryCanton:
    @pytest.mark.parametrize("canton", sorted(CANTONS))
    def test_every_case_is_aimed_at_the_canton(self, canton: str) -> None:
        cases = adversarial_cases_for(canton)
        assert len(cases) == len(ADVERSARIAL_CASES)
        assert all(case.canton == canton for case in cases)

    @pytest.mark.parametrize("canton", sorted(CANTONS))
    def test_no_case_still_names_a_placeholder(self, canton: str) -> None:
        for case in adversarial_cases_for(canton):
            assert "{canton}" not in case.question

    def test_a_case_naming_a_canton_names_the_right_one(self) -> None:
        """The false-premise case asserts a fee "in Zug". Run against Uri it
        has to say Uri, or it is testing whether Dumi refuses to talk about a
        different canton rather than whether it repeats a false premise."""
        uri = {case.id: case for case in adversarial_cases_for("uri")}
        assert "Uri" in uri["adv-false-premise[uri]"].question
        assert "Zug" not in uri["adv-false-premise[uri]"].question

    def test_ids_say_which_canton_failed(self) -> None:
        ids = {case.id for case in adversarial_cases_for("uri")}
        assert "adv-reveal-prompt[uri]" in ids

    def test_the_two_cantons_produce_distinct_cases(self) -> None:
        zug = {case.id for case in adversarial_cases_for("zug")}
        assert not zug & {case.id for case in adversarial_cases_for("uri")}


class TestGroundedCases:
    def test_a_case_defaults_to_the_deployment_canton(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        path = tmp_path / "cases.json"
        path.write_text(
            '{"cases": [{"id": "g1", "question": "Was kostet die Anmeldung?"}]}',
            encoding="utf-8",
        )
        (case,) = load_grounded_cases(path)
        assert case.canton == DEFAULT_CANTON
        assert case.expectation is Expectation.ANSWER_WITH_CITATIONS

    def test_a_case_can_name_its_canton(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        path = tmp_path / "cases.json"
        path.write_text(
            '{"cases": [{"id": "g1", "question": "Frist?", "canton": "uri"}]}',
            encoding="utf-8",
        )
        (case,) = load_grounded_cases(path)
        assert case.canton == "uri"


class _RecordingAnswers:
    """Stands in for the answer pipeline, recording which canton was asked."""

    def __init__(self, answers: list[Answer]) -> None:
        self.answers = answers
        self.cantons: list[str] = []

    async def __call__(self, session, embedder, llm, question, **kwargs):  # type: ignore[no-untyped-def]
        self.cantons.append(kwargs.get("canton"))
        return self.answers[(len(self.cantons) - 1) % len(self.answers)]


def _answer(*, refusal: bool, citations: int = 0, reasons=()) -> Answer:  # type: ignore[no-untyped-def]
    from app.retrieval.answer import Citation

    return Answer(
        text="…",
        language="de",
        confidence=Confidence.INSUFFICIENT if refusal else Confidence.HIGH,
        citations=[
            Citation(
                number=n + 1,
                title="Seite",
                url=f"https://www.ur.ch/{n}",
                locator="",
                language="de",
                last_checked=None,
            )
            for n in range(citations)
        ],
        is_refusal=refusal,
        reasons=reasons,
    )


class TestCoverageProfile:
    async def test_it_asks_the_canton_it_was_given(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        recorder = _RecordingAnswers([_answer(refusal=False, citations=2)])
        monkeypatch.setattr("app.evaluation.runner.answer_question", recorder)

        await measure_coverage(
            None, None, None, ["Frage eins?", "Frage zwei?"], canton="uri"
        )
        assert recorder.cantons == ["uri", "uri"]

    async def test_it_reports_the_answer_rate(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        recorder = _RecordingAnswers(
            [
                _answer(refusal=False, citations=3),
                _answer(refusal=True, reasons=("no_matching_sources",)),
            ]
        )
        monkeypatch.setattr("app.evaluation.runner.answer_question", recorder)

        profile = await measure_coverage(
            None, None, None, ["a?", "b?", "c?", "d?"], canton="zug"
        )
        assert profile.answered == 2
        assert profile.refused == 2
        assert profile.answer_rate == 0.5
        assert profile.citations_per_answer == 3.0
        assert profile.refusal_reasons == {"no_matching_sources": 2}

    def test_an_empty_run_does_not_divide_by_zero(self) -> None:
        profile = CoverageProfile(canton="uri")
        assert profile.answer_rate == 0.0
        assert profile.citations_per_answer == 0.0

    def test_the_summary_names_the_canton_and_the_rate(self) -> None:
        profile = CoverageProfile(
            canton="uri", questions=10, answered=4, refused=6, citations_total=8
        )
        summary = profile.summary()
        assert "uri" in summary
        assert "40%" in summary


class TestAnUnreachableModelIsNeverAPass:
    """Observed on a real run: the model was configured for a 4096-token
    window, the suite built prompts for 8192, and every case came back as
    LLMRequestTooLarge. Most cases expect a refusal, and an unavailable model
    produces one, so the suite reported 10 of 11 passing while testing
    nothing at all. That is the worst failure a test suite can have."""

    def _unreachable(self):  # type: ignore[no-untyped-def]
        answer = _answer(refusal=True)
        answer.degraded_reason = "model_unavailable_LLMRequestTooLarge"
        return answer

    def test_a_case_expecting_a_refusal_still_fails(self) -> None:
        case = next(
            c
            for c in adversarial_cases_for("zug")
            if c.expectation is Expectation.REFUSE_INSUFFICIENT
        )
        passed, failures = _check(case, self._unreachable())
        assert not passed
        assert "not reached" in failures[0]

    def test_the_summary_leads_with_it(self) -> None:
        case = adversarial_cases_for("zug")[0]
        suite = SuiteResult(
            results=[
                CaseResult(
                    case=case,
                    passed=False,
                    degraded_reason="model_unavailable_LLMRequestTooLarge",
                )
            ]
        )
        summary = suite.summary()
        assert suite.unreachable == 1
        assert "never reached the model" in summary
        assert "APERTUS_MAX_CONTEXT_TOKENS" in summary

    async def test_coverage_holds_it_apart_from_a_refusal(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """A configuration fault must not be reported as a corpus fault."""
        recorder = _RecordingAnswers([self._unreachable()])
        monkeypatch.setattr("app.evaluation.runner.answer_question", recorder)

        profile = await measure_coverage(
            None, None, None, ["a?", "b?"], canton="uri"
        )
        assert profile.unreachable == 2
        assert profile.refused == 0
        assert profile.measured == 0
        assert "never reached" in profile.summary()

    async def test_the_rate_counts_only_what_was_measured(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        answers = [_answer(refusal=False, citations=2), self._unreachable()]
        recorder = _RecordingAnswers(answers)
        monkeypatch.setattr("app.evaluation.runner.answer_question", recorder)

        profile = await measure_coverage(
            None, None, None, ["a?", "b?", "c?", "d?"], canton="uri"
        )
        assert profile.answered == 2
        assert profile.unreachable == 2
        assert profile.answer_rate == 1.0, "two of two that ran were answered"


class TestTheContextWindowReachesThePipeline:
    """The bug behind the unreachable model: the suite never passed the
    configured limits, so it built prompts for a window the provider does not
    serve."""

    async def test_run_suite_passes_the_limits_through(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        seen: dict = {}

        async def spy(session, embedder, llm, question, **kwargs):  # type: ignore[no-untyped-def]
            seen.update(kwargs)
            return _answer(refusal=True)

        monkeypatch.setattr("app.evaluation.runner.answer_question", spy)
        await run_suite(
            None,
            None,
            None,
            adversarial_cases_for("uri")[:1],
            max_context_tokens=4096,
            max_output_tokens=384,
        )
        assert seen["max_context_tokens"] == 4096
        assert seen["max_output_tokens"] == 384

    async def test_coverage_passes_the_limits_through(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        seen: dict = {}

        async def spy(session, embedder, llm, question, **kwargs):  # type: ignore[no-untyped-def]
            seen.update(kwargs)
            return _answer(refusal=False, citations=1)

        monkeypatch.setattr("app.evaluation.runner.answer_question", spy)
        await measure_coverage(
            None, None, None, ["a?"], canton="uri", max_context_tokens=4096
        )
        assert seen["max_context_tokens"] == 4096


class TestTheAdversarialSetIsContentIndependent:
    """It claims to assert behaviour that holds whatever is indexed. One case
    did not: the false-premise case required an answer, so it failed on any
    canton whose corpus does not happen to cover registration fees, for a
    reason that has nothing to do with the false premise."""

    def test_no_case_requires_the_corpus_to_cover_a_topic(self) -> None:
        for case in adversarial_cases_for("uri"):
            assert case.expectation is not Expectation.ANSWER_WITH_CITATIONS, (
                f"{case.id} needs content to pass, so it belongs in "
                "grounded-cases.json, not the adversarial set"
            )

    def test_the_false_premise_case_still_forbids_the_figure(self) -> None:
        case = {c.id: c for c in adversarial_cases_for("uri")}["adv-false-premise[uri]"]
        assert "CHF 500" in case.forbidden_substrings

    def test_repeating_the_premise_fails_however_it_is_phrased(self) -> None:
        case = {c.id: c for c in adversarial_cases_for("zug")}["adv-false-premise[zug]"]
        answer = _answer(refusal=False, citations=1)
        answer.text = "Ja, die Gebühr beträgt 500 Franken [1]."
        passed, failures = _check(case, answer)
        assert not passed
        assert "500 Franken" in failures[0]

    def test_a_refusal_is_acceptable_for_that_case(self) -> None:
        case = {c.id: c for c in adversarial_cases_for("zug")}["adv-false-premise[zug]"]
        passed, _ = _check(case, _answer(refusal=True))
        assert passed, "a thin corpus must not fail a case about what to never say"
