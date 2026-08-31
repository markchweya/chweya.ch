"""Producing an answer, end to end.

Search, assess the evidence, build the prompt, call Apertus, then check what
came back before showing it to anyone.

The check after generation is not decoration. Everything before it constrains
the model; none of it guarantees the model complied. So the answer is verified
against the evidence that was actually supplied:

* A citation naming a passage that was not provided is removed. The model
  inventing [7] when six passages were given is exactly the failure citations
  exist to prevent.
* An answer with no citations at all, where the policy required them, is
  replaced with the insufficient-evidence response rather than shown.

Neither check makes the answer correct. Both stop a specific way of being
confidently wrong from reaching a resident.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.i18n import DEFAULT_LANGUAGE, normalise_language, t
from app.ingest.contradictions import open_findings_for_chunks
from app.llm.base import (
    ChatMessage,
    GenerationRequest,
    LLMError,
    LLMProvider,
    Role,
)
from app.observability import get_logger
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.evidence import Confidence, EvidenceAssessment, RiskTopic, assess
from app.retrieval.prompt import BuiltPrompt, build_prompt, should_call_model
from app.retrieval.search import search

logger = get_logger(__name__)

# Matches the bracketed citation markers the system prompt asks for.
CITATION_PATTERN = re.compile(r"\[(\d{1,2})\]")

# Markdown markers a model emits despite being told to write plain text. The
# interface renders answers as text, which is right for content a model wrote,
# so **bold** would reach a resident as literal asterisks. Only the markers
# are removed; every word stays exactly as generated.
_MD_HEADING = re.compile(r"^#{1,6}[ \t]+", re.MULTILINE)
_MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_MD_BOLD_UNDERSCORE = re.compile(r"__([^_]+)__")
_MD_BULLET = re.compile(r"^[ \t]*\*[ \t]+", re.MULTILINE)
_MD_EMPHASIS = re.compile(r"(?<![\w*])\*([^\s*][^*\n]*?)\*(?![\w*])")
_MD_CODE = re.compile(r"`+")

MAX_QUESTION_CHARACTERS = 1000

# Added to the configured output limit when reserving prompt space, covering
# the per-message overhead the provider counts and the roughness of the
# character-based token estimate. The reserve must always exceed what the
# provider adds to the prompt before its size check, or an answer fails
# before generation even starts.
ANSWER_RESERVE_MARGIN = 128


@dataclass
class Citation:
    """One source shown beneath an answer.

    Carries everything section 11 requires: title, official URL, the section
    or page within it, the source language, and when it was last checked.
    """

    number: int
    title: str
    url: str | None
    locator: str
    language: str
    last_checked: dt.datetime | None
    department: str | None = None
    # The language the answer was written in, so the interface can mark a
    # source that is in a different one. Section 3 requires that disclosure:
    # citing a German page under a French answer is fine, pretending the
    # source is French is not.
    answer_language: str = DEFAULT_LANGUAGE

    @property
    def is_cross_language(self) -> bool:
        """Whether this source is in a language other than the answer's."""
        return bool(self.language) and self.language != self.answer_language


@dataclass
class Answer:
    """A complete response, ready to render."""

    text: str
    language: str
    confidence: Confidence
    citations: list[Citation] = field(default_factory=list)
    risk_topics: tuple[RiskTopic, ...] = ()
    reasons: tuple[str, ...] = ()
    # Notices the interface must show, as message keys.
    notices: list[str] = field(default_factory=list)
    # True when the response is the fixed refusal rather than generated text.
    is_refusal: bool = False
    degraded_reason: str = ""

    @property
    def has_citations(self) -> bool:
        return bool(self.citations)


# Messages that are social, not factual. A greeting needs no evidence and
# answering it through document retrieval produces a refusal that reads
# broken. The whole message must match: "hey, what does a passport cost"
# carries a question and goes to retrieval like any other.
#
# The replies are fixed interface strings, never model output. Letting the
# model chat freely here would reopen exactly the door the fail-closed
# design exists to keep shut.
_GREETING_PATTERN = re.compile(
    r"^(?:"
    r"hi+|hey+|hello+|hallo+|hoi|hey there|good (?:morning|afternoon|evening)|"
    r"sal(?:ü|u|i)|servus|moin|gr(?:ü|ue)ezi(?: mitenand)?|"
    r"guten (?:tag|morgen|abend)|"
    r"bonjour|bonsoir|salut|coucou|"
    r"buongiorno|buonasera|buondì|buondi|ciao"
    r")(?:[\s,]+dumi)?$"
)
_THANKS_PATTERN = re.compile(
    r"^(?:"
    r"thanks+|thank you(?: very much)?|thx|"
    r"danke(?:sch(?:ö|oe)n| vielmal|)|vielen dank|merci(?: beaucoup| vilmal|)|"
    r"grazie(?: mille|)"
    r")(?:[\s,]+dumi)?$"
)

# Questions about the assistant itself. "Who are you" is not a question about
# the Canton of Zug, so the evidence requirement does not apply; the honest
# answer is the fixed self-description, which also says plainly what this is
# and is not.
_ABOUT_PATTERN = re.compile(
    r"^(?:"
    r"who are you|what are you|who is dumi|what is dumi|"
    r"what can you (?:do|help(?: me)? with)|what do you do|"
    r"how (?:can|do) you help(?: me)?|help(?: me)?|"
    r"wer bist du|was bist du|wer ist dumi|was ist dumi|"
    r"was kannst du(?: tun| alles)?|was machst du|"
    r"wo(?:bei|mit) kannst du(?: mir)? helfen|wie kannst du(?: mir)? helfen|"
    r"hilfe|hilf mir|"
    r"qui es[- ]tu|qui (?:ê|e)tes[- ]vous|t'es qui|que fais[- ]tu|"
    r"que peux[- ]tu faire|que pouvez[- ]vous faire|"
    r"comment peux[- ]tu m'aider|comment pouvez[- ]vous m'aider|"
    r"(?:à|a) quoi sers[- ]tu|aide(?:[- ]moi)?|"
    r"chi sei|cosa sei|chi (?:è|e) dumi|cos(?:'|a )(?:è|e) dumi|"
    r"cosa (?:puoi|sai) fare|come puoi aiutarmi|in cosa puoi aiutarmi|"
    r"aiuto|aiutami"
    r")(?:[\s,]+dumi)?$"
)


def small_talk_key(question: str) -> str | None:
    """Return the message key for a purely social message, or None.

    Deliberately narrow: only a message that is nothing but a greeting or a
    thank-you qualifies. Anything carrying content words is a question and
    must face the evidence requirement.
    """
    bare = re.sub(r"[!?.…🙂😊👋🙏]+", " ", question.lower()).strip()
    bare = re.sub(r"\s+", " ", bare)
    if _GREETING_PATTERN.fullmatch(bare):
        return "answer.greeting"
    if _THANKS_PATTERN.fullmatch(bare):
        return "answer.thanks"
    if _ABOUT_PATTERN.fullmatch(bare):
        return "answer.about"
    return None


def detect_language(question: str, fallback: str = DEFAULT_LANGUAGE) -> str:
    """Guess the language of a question.

    Uses langdetect when available. Short questions are unreliable to detect,
    and guessing wrong means answering a German speaker in Italian, so
    anything under 20 characters keeps the fallback, which is the language the
    person selected in the interface.
    """
    stripped = question.strip()
    if len(stripped) < 20:
        return fallback

    try:
        from langdetect import DetectorFactory, detect

        # Without a fixed seed langdetect returns different answers for the
        # same input, which would make an answer's language non-reproducible.
        DetectorFactory.seed = 0
        return normalise_language(detect(stripped))
    except Exception:  # noqa: BLE001 - detection failure must never break a question
        return fallback


def _build_citations(prompt: BuiltPrompt, answer_language: str) -> list[Citation]:
    """Turn the passages actually sent into citation records."""
    citations: list[Citation] = []
    for number, chunk in enumerate(prompt.cited_chunks, start=1):
        citations.append(
            Citation(
                number=number,
                title=chunk.document_title or (chunk.document_url or "Untitled"),
                url=chunk.document_url,
                locator=chunk.citation_anchor,
                language=chunk.language,
                last_checked=(
                    chunk.last_verified_at
                    if isinstance(chunk.last_verified_at, dt.datetime)
                    else (
                        chunk.retrieved_at
                        if isinstance(chunk.retrieved_at, dt.datetime)
                        else None
                    )
                ),
                department=chunk.department,
                answer_language=answer_language,
            )
        )
    return citations


def strip_markup(text: str) -> str:
    """Remove Markdown formatting markers from a generated answer.

    The prompt forbids them; this handles the ones that arrive anyway.
    Bullet asterisks become plain hyphens so a list stays a list. Leftover
    unpaired double asterisks are dropped rather than shown.
    """
    text = _MD_HEADING.sub("", text)
    text = _MD_BOLD.sub(r"\1", text)
    text = _MD_BOLD_UNDERSCORE.sub(r"\1", text)
    text = _MD_BULLET.sub("- ", text)
    text = _MD_EMPHASIS.sub(r"\1", text)
    text = _MD_CODE.sub("", text)
    return text.replace("**", "")


# What the prompt tells the model to reply when the passages do not answer
# the question. A model left to write its own "I could not find this" prose
# produces meta-text with pasted links and no citations, which the citation
# check then throws away. The sentinel routes that case to the fixed refusal,
# which is honest and arrives with the retrieved pages attached.
NO_ANSWER_SENTINEL = "NO_ANSWER"


def is_no_answer(text: str) -> bool:
    """Whether a generated response declares the evidence insufficient.

    The instruction says to reply with the sentinel alone; a small model
    wraps it in prose anyway ("Therefore, the answer is NO_ANSWER."). Any
    occurrence counts. A response carrying the sentinel is a declaration of
    insufficiency and must never reach the screen as an answer.
    """
    return NO_ANSWER_SENTINEL in text.upper()


# Sent back to the model, once, when it answered without citing. A small
# quantised model ignores the citation instruction often enough that giving
# up on the first miss throws away real answers; one corrective turn recovers
# most of them, and a second failure falls through to the honest refusal.
_CITATION_CORRECTION = (
    "Your answer was rejected because it contains no bracketed passage "
    "numbers. Write the answer again, and put the number of the supporting "
    "passage, like [1], after every factual statement. If the passages do "
    "not answer the question, reply with exactly NO_ANSWER."
)


def needs_citation_retry(text: str, prepared: PreparedAnswer) -> bool:
    """Whether a response should be regenerated with the correction turn."""
    cleaned = strip_markup(text)
    if is_no_answer(cleaned):
        return False
    _, kept, _ = validate_citations(cleaned, len(prepared.prompt.cited_chunks))
    return not kept


def correction_request(prepared: PreparedAnswer, first_text: str) -> GenerationRequest:
    """The retry conversation: the original prompt, the model's uncited
    answer, and the correction."""
    original = prepared.prompt.request
    return GenerationRequest(
        messages=[
            *original.messages,
            ChatMessage(role=Role.ASSISTANT, content=first_text),
            ChatMessage(role=Role.USER, content=_CITATION_CORRECTION),
        ],
        max_output_tokens=original.max_output_tokens,
        temperature=original.temperature,
        stop=original.stop,
    )


def validate_citations(text: str, available: int) -> tuple[str, list[int], list[int]]:
    """Remove citation markers that name passages which were not supplied.

    Returns the cleaned text, the numbers that were kept, and the numbers that
    were invented. A model citing [7] when six passages were provided is the
    precise failure that citations exist to prevent, so the marker is stripped
    rather than rendered as a broken link.
    """
    kept: list[int] = []
    invented: list[int] = []

    def replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if 1 <= number <= available:
            if number not in kept:
                kept.append(number)
            return match.group(0)
        if number not in invented:
            invented.append(number)
        return ""

    cleaned = CITATION_PATTERN.sub(replace, text)
    # Tidy the spacing a removed marker leaves behind.
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = re.sub(r" +([.,;:])", r"\1", cleaned)
    return cleaned.strip(), kept, invented


# A line holding nothing but citation markers, the way a small model sometimes
# signs off: "[1] [2] [3] [4]". By the time layout runs the markers have been
# counted, and a row of bare numbers on screen tells the reader nothing the
# sources block does not.
_MARKER_ONLY_LINE = re.compile(r"^[ \t]*(?:\[\d{1,2}\][ \t.,;]*)+$\n?", re.MULTILINE)


def tidy_layout(text: str) -> str:
    """Drop marker-only lines and collapse runs of blank lines."""
    text = _MARKER_ONLY_LINE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _notices_for(assessment: EvidenceAssessment) -> list[str]:
    """Message keys the interface must display alongside the answer."""
    notices: list[str] = []
    if assessment.has_emergency_topic:
        # First, always. Section 12 forbids delaying someone who may be in
        # an emergency with procedural detail.
        notices.append("answer.emergency")
    if assessment.risk_topics:
        notices.append("answer.high_risk")
    if "sources_inconsistent" in assessment.reasons:
        # Section 9: the inconsistency between official sources is disclosed
        # to the person, not silently absorbed into a lower confidence.
        notices.append("answer.sources_inconsistent")
    # Medium and low confidence used to add a "confirm this with the cited
    # office" banner above every such answer. Removed: the sources block
    # carries the links to check against, the confidence still reaches the
    # interface as data, and a caution stapled to most answers teaches people
    # to read none of them. Emergency and high-risk notices stay.
    return notices



@dataclass
class PreparedAnswer:
    """Everything the generation step needs, once retrieval has run.

    Split out so the streamed and unstreamed paths share every safety check:
    the social replies, the evidence requirement, the prompt construction and
    the citation validation are one code path with two delivery modes.
    """

    prompt: BuiltPrompt
    assessment: EvidenceAssessment
    answer_language: str
    degraded_reason: str


def _unavailable(answer_language: str, exc: LLMError) -> Answer:
    """The honest response when the model cannot answer.

    Fail closed. An unavailable model produces a fixed message, never an
    answer from model memory or a cached guess.
    """
    logger.warning("answer.model_unavailable", error=type(exc).__name__)
    return Answer(
        text=t("answer.unavailable", answer_language),
        language=answer_language,
        confidence=Confidence.INSUFFICIENT,
        is_refusal=True,
        degraded_reason=f"model_unavailable_{type(exc).__name__}",
    )


def prepare_answer(
    session: Session,
    embedder: EmbeddingProvider,
    question: str,
    *,
    language: str | None = None,
    max_context_tokens: int = 8192,
    max_output_tokens: int = 512,
    estimate_tokens=None,  # type: ignore[no-untyped-def]
) -> Answer | PreparedAnswer:
    """Run everything that happens before the model: validation, social
    replies, retrieval, the confidence policy and prompt assembly.

    Returns a finished :class:`Answer` when no generation should happen, or a
    :class:`PreparedAnswer` when it should.
    """
    question = question.strip()
    answer_language = normalise_language(language) if language else detect_language(question)

    if not question:
        return Answer(
            text=t("error.question_empty", answer_language),
            language=answer_language,
            confidence=Confidence.INSUFFICIENT,
            is_refusal=True,
        )
    if len(question) > MAX_QUESTION_CHARACTERS:
        return Answer(
            text=t("error.question_too_long", answer_language),
            language=answer_language,
            confidence=Confidence.INSUFFICIENT,
            is_refusal=True,
        )

    # A greeting or a thank-you gets a greeting back, before retrieval runs.
    # There is no factual claim in "hello", so the evidence requirement does
    # not apply, and refusing it for lack of sources reads as a malfunction.
    # The reply is a fixed localised string; the model is not consulted.
    social = small_talk_key(question)
    if social is not None:
        return Answer(
            text=t(social, answer_language),
            language=answer_language,
            confidence=Confidence.HIGH,
        )

    result = search(session, embedder, question)

    # Section 9: an answer drawing on a passage with an unresolved
    # contradiction finding must say the official sources appear inconsistent
    # and lower its confidence. The count comes from the review queue, so the
    # moment a reviewer resolves the finding the qualification disappears.
    contradicted = open_findings_for_chunks(
        session, [chunk.chunk_id for chunk in result.chunks]
    )
    assessment = assess(
        result,
        question,
        answer_language=answer_language,
        open_contradictions=contradicted,
    )

    if not should_call_model(assessment):
        # Fixed text, not generated. Asking a model to explain that it has no
        # information invites it to produce something anyway.
        logger.info("answer.insufficient_evidence", reasons=",".join(assessment.reasons))
        return Answer(
            text=t("answer.insufficient_evidence", answer_language),
            language=answer_language,
            confidence=Confidence.INSUFFICIENT,
            risk_topics=assessment.risk_topics,
            reasons=assessment.reasons,
            notices=_notices_for(assessment),
            is_refusal=True,
            degraded_reason=result.degraded_reason,
        )

    prompt = build_prompt(
        question,
        assessment,
        answer_language=answer_language,
        max_context_tokens=max_context_tokens,
        answer_reserve_tokens=max_output_tokens + ANSWER_RESERVE_MARGIN,
        estimate_tokens=estimate_tokens,
    )
    return PreparedAnswer(
        prompt=prompt,
        assessment=assessment,
        answer_language=answer_language,
        degraded_reason=result.degraded_reason,
    )


def finalise_answer(text: str, was_truncated: bool, prepared: PreparedAnswer) -> Answer:
    """Validate a generated response and shape it into an answer.

    Identical for streamed and unstreamed generation: the text is checked
    against the passages that were actually supplied, invented citation
    markers are stripped, and a response that cited nothing is refused.
    """
    prompt = prepared.prompt
    assessment = prepared.assessment
    answer_language = prepared.answer_language

    cleaned, kept, invented = validate_citations(
        strip_markup(text), len(prompt.cited_chunks)
    )
    cleaned = tidy_layout(cleaned)

    if invented:
        logger.warning(
            "answer.invented_citations",
            invented=",".join(str(n) for n in invented),
            supplied=len(prompt.cited_chunks),
        )

    all_citations = _build_citations(prompt, answer_language)

    if is_no_answer(cleaned):
        # The model followed the instruction for passages that do not answer
        # the question. The person sees the fixed refusal, in their language,
        # with the retrieved pages attached so the nearest official material
        # is one click away.
        logger.info("answer.model_reported_no_answer")
        return Answer(
            text=t("answer.insufficient_evidence", answer_language),
            language=answer_language,
            confidence=Confidence.INSUFFICIENT,
            citations=all_citations,
            risk_topics=assessment.risk_topics,
            reasons=(*assessment.reasons, "model_reported_no_answer"),
            notices=_notices_for(assessment),
            is_refusal=True,
        )

    if not kept:
        # The model answered without citing anything, so its text cannot be
        # shown as sourced and is withheld. What replaces it must be honest:
        # evidence was found, the failure is in tying the answer to it. The
        # message says exactly that, and the retrieved pages are listed so the
        # person can read them directly instead of being told nothing exists.
        logger.warning("answer.no_citations_produced")
        return Answer(
            text=t("answer.uncited", answer_language),
            language=answer_language,
            confidence=Confidence.INSUFFICIENT,
            citations=all_citations,
            risk_topics=assessment.risk_topics,
            reasons=(*assessment.reasons, "model_answered_without_citations"),
            notices=_notices_for(assessment),
            is_refusal=True,
        )
    # Show only the sources the answer actually used.
    used = [citation for citation in all_citations if citation.number in kept]

    if was_truncated:
        # A cut-off list of requirements reads as an exhaustive one.
        cleaned += "\n\n" + t("answer.qualified", answer_language)

    return Answer(
        text=cleaned,
        language=answer_language,
        confidence=assessment.confidence,
        citations=used,
        risk_topics=assessment.risk_topics,
        reasons=assessment.reasons,
        notices=_notices_for(assessment),
        degraded_reason=prepared.degraded_reason,
    )


async def answer_question(
    session: Session,
    embedder: EmbeddingProvider,
    llm: LLMProvider,
    question: str,
    *,
    language: str | None = None,
    max_context_tokens: int = 8192,
    max_output_tokens: int = 512,
) -> Answer:
    """Answer one question, or explain honestly why it cannot be answered."""
    prepared = prepare_answer(
        session,
        embedder,
        question,
        language=language,
        max_context_tokens=max_context_tokens,
        max_output_tokens=max_output_tokens,
        estimate_tokens=llm.estimate_tokens,
    )
    if isinstance(prepared, Answer):
        return prepared

    try:
        generated = await llm.generate(prepared.prompt.request)
    except LLMError as exc:
        return _unavailable(prepared.answer_language, exc)

    text, was_truncated = generated.text, generated.was_truncated
    if needs_citation_retry(text, prepared):
        logger.info("answer.citation_retry")
        try:
            second = await llm.generate(correction_request(prepared, text))
            text, was_truncated = second.text, second.was_truncated
        except LLMError:
            # The first response exists; finalise it and let the uncited
            # fallback handle it rather than reporting the model unavailable.
            pass

    return finalise_answer(text, was_truncated, prepared)


async def stream_answer(
    session: Session,
    embedder: EmbeddingProvider,
    llm: LLMProvider,
    question: str,
    *,
    language: str | None = None,
    max_context_tokens: int = 8192,
    max_output_tokens: int = 512,
):  # type: ignore[no-untyped-def]  # AsyncIterator[tuple[str, str | Answer]]
    """Answer one question incrementally.

    Yields ("delta", text) while the model writes, then exactly one
    ("answer", Answer) carrying the validated final response. The final
    answer's text is authoritative: citation markers the model invented are
    stripped only there, so the interface must replace the streamed text with
    it rather than keep what it accumulated.

    A stream that fails midway ends with the unavailable answer, never with
    the partial text standing as if finished.
    """
    prepared = prepare_answer(
        session,
        embedder,
        question,
        language=language,
        max_context_tokens=max_context_tokens,
        max_output_tokens=max_output_tokens,
        estimate_tokens=llm.estimate_tokens,
    )
    if isinstance(prepared, Answer):
        yield ("answer", prepared)
        return

    # The word NO_ANSWER must never reach the screen, whether the model
    # replies with the sentinel alone or wraps it in prose partway through.
    # Deltas are held while the reply could still be the bare sentinel, and a
    # rolling window watches for it appearing later; from the moment it
    # shows, the stream goes quiet and the final event carries the refusal.
    accumulated: list[str] = []
    held: list[str] = []
    window = ""
    gate_open = False
    suppress = False
    try:
        async for chunk in llm.stream(prepared.prompt.request):
            if chunk.done:
                break
            if not chunk.text:
                continue
            accumulated.append(chunk.text)
            if suppress:
                continue
            # Long enough to catch the sentinel split across chunks.
            window = (window + chunk.text.upper())[-64:]
            if NO_ANSWER_SENTINEL in window:
                suppress = True
                held.clear()
                continue
            if not gate_open:
                head = strip_markup("".join(accumulated)).lstrip().upper()
                if NO_ANSWER_SENTINEL.startswith(head):
                    held.append(chunk.text)
                    continue
                gate_open = True
                for text in held:
                    yield ("delta", text)
                held.clear()
            yield ("delta", chunk.text)
    except LLMError as exc:
        yield ("answer", _unavailable(prepared.answer_language, exc))
        return

    text = "".join(accumulated)
    if needs_citation_retry(text, prepared):
        # The retry is generated whole rather than streamed: the person is
        # already reading the first attempt, and the final event replaces it
        # either way.
        logger.info("answer.citation_retry")
        try:
            second = await llm.generate(correction_request(prepared, text))
            text = second.text
        except LLMError:
            pass

    # The wire protocol does not carry a finish reason for streams, so
    # truncation cannot be detected here; the output-token limit is the
    # provider's to enforce and the qualification note is only added on the
    # unstreamed path.
    yield ("answer", finalise_answer(text, False, prepared))
