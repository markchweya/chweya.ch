"""Evidence assembly and the confidence policy.

Section 11 forbids letting the model invent its own confidence. So confidence
is computed here, from properties of the retrieved evidence, before the model
sees anything. The model is told what it may claim; it does not decide.

The four states and what each one means for the person asking:

``high``        Answer normally, with citations.
``medium``      Answer, with a short qualification naming what is uncertain.
``low``         Give only what is directly supported and point at the office.
``insufficient`` Do not answer. Say it could not be verified and offer the
                office or the official search.

The last one is the important one. A system that answers everything is a
system that is confidently wrong about deadlines and fees, and a resident who
misses a fourteen-day registration deadline because of a plausible sentence is
worse off than one who was told to check.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from enum import StrEnum

from app.retrieval.search import RetrievedChunk, SearchResult

# A source not re-checked within this window is treated as possibly stale.
# Cantonal fees and deadlines change at the turn of a year, so a source last
# verified more than a quarter ago cannot be presented as certainly current.
FRESHNESS_WARNING_DAYS = 90
FRESHNESS_STALE_DAYS = 365

# Fusion scores below this are weak matches. Two arms each ranking a passage
# around 20th place produce roughly this, which is the level at which a
# passage is more likely to be topically adjacent than actually relevant.
WEAK_SCORE_THRESHOLD = 0.016

# How much evidence is worth sending to the model at all.
MIN_USABLE_CHUNKS = 1


class Confidence(StrEnum):
    """How far the evidence supports an answer."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"

    @property
    def may_answer(self) -> bool:
        """Whether a substantive answer is permitted at all."""
        return self is not Confidence.INSUFFICIENT


class RiskTopic(StrEnum):
    """High-risk areas from section 12, which carry stricter handling."""

    LEGAL = "legal"
    TAX = "tax"
    IMMIGRATION = "immigration"
    SOCIAL_BENEFITS = "social_benefits"
    HEALTH = "health"
    EMERGENCY = "emergency"
    CHILD_PROTECTION = "child_protection"
    DEADLINE = "deadline"
    PERMIT = "permit"
    FINANCIAL_OBLIGATION = "financial_obligation"


# Matched against the question in all four languages. Deliberately broad: a
# false positive adds a caution notice, a false negative removes one from a
# question that needed it.
RISK_PATTERNS: dict[RiskTopic, tuple[str, ...]] = {
    RiskTopic.EMERGENCY: (
        r"\bnotfall\b", r"\bnotruf\b", r"\bemergency\b", r"\burgence\b", r"\bemergenza\b",
        r"\bpolizei\b", r"\bpolice\b", r"\bpolizia\b", r"\bambulanz\b", r"\bambulance\b",
        r"\bfeuerwehr\b", r"\bpompier", r"\bvigili del fuoco\b", r"\bsuizid", r"\bsuicid",
        r"\bgewalt\b", r"\bviolence\b", r"\bviolenza\b", r"\bmissbrauch\b", r"\babuse\b",
    ),
    RiskTopic.CHILD_PROTECTION: (
        r"\bkindesschutz\b", r"\bkindeswohl\b", r"\bkesb\b", r"\bchild protection\b",
        r"\bprotection de l'enfant\b", r"\bvormundschaft\b", r"\bobhut\b", r"\bsorgerecht\b",
    ),
    RiskTopic.HEALTH: (
        r"\bgesundheit\b", r"\bkrankheit\b", r"\barzt\b", r"\bspital\b", r"\bmedizin",
        r"\bhealth\b", r"\bdoctor\b", r"\bhospital\b", r"\bsante\b", r"\bmedico\b",
        r"\bimpfung\b", r"\bvaccin", r"\bpsychiatr",
    ),
    RiskTopic.IMMIGRATION: (
        r"\baufenthalt", r"\bniederlassung", r"\bausweis b\b", r"\bausweis c\b",
        r"\bvisum\b", r"\bvisa\b", r"\beinbuergerung\b", r"\bnaturalisation\b",
        r"\bresidence permit\b", r"\bpermis de sejour\b", r"\basyl", r"\basylum\b",
        r"\bmigration", r"\bauslaender",
    ),
    RiskTopic.TAX: (
        r"\bsteuer", r"\btax\b", r"\btaxes\b", r"\bimpot", r"\bimposta",
        r"\bveranlagung\b", r"\bsteuererklaerung\b", r"\btax return\b",
        r"\bmehrwertsteuer\b", r"\bquellensteuer\b",
    ),
    RiskTopic.SOCIAL_BENEFITS: (
        r"\bsozialhilfe\b", r"\berganzungsleistung", r"\bergaenzungsleistung",
        r"\bahv\b", r"\biv\b", r"\barbeitslos", r"\bunemploy", r"\bpramienverbilligung",
        r"\bpraemienverbilligung", r"\bsocial benefit", r"\baide sociale\b",
        r"\bassistenza sociale\b", r"\bkinderzulage",
    ),
    RiskTopic.LEGAL: (
        r"\brecht\b", r"\bgesetz\b", r"\bklage\b", r"\bgericht\b", r"\banwalt\b",
        r"\bstrafe\b", r"\bbusse\b", r"\blegal\b", r"\blawyer\b", r"\bcourt\b",
        r"\bavocat\b", r"\btribunal\b", r"\bavvocato\b", r"\beinsprache\b",
        r"\brekurs\b", r"\bbeschwerde\b",
    ),
    RiskTopic.DEADLINE: (
        r"\bfrist\b", r"\btermin\b", r"\bdeadline\b", r"\bdelai\b", r"\bscadenza\b",
        r"\bverjaehrung\b", r"\binnert\b", r"\bbis wann\b", r"\bby when\b",
    ),
    RiskTopic.PERMIT: (
        r"\bbewilligung\b", r"\bgenehmigung\b", r"\bpermit\b", r"\bautorisation\b",
        r"\bautorizzazione\b", r"\bbaugesuch\b", r"\bkonzession\b", r"\blizenz\b",
    ),
    RiskTopic.FINANCIAL_OBLIGATION: (
        r"\bgebuehr", r"\bkosten\b", r"\brechnung\b", r"\bzahlung\b", r"\bbusse\b",
        r"\bfee\b", r"\bcharge\b", r"\bpayment\b", r"\btarif\b", r"\bcosto\b",
    ),
}

_COMPILED_RISK = {
    topic: tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)
    for topic, patterns in RISK_PATTERNS.items()
}


def classify_risk(question: str) -> tuple[RiskTopic, ...]:
    """Return the high-risk topics a question touches.

    Broad by design. Adding a caution notice to a question that did not need
    one costs a line of text; omitting it from one that did could cost someone
    a deadline or send them to the wrong place in an emergency.
    """
    found: list[RiskTopic] = []
    for topic, patterns in _COMPILED_RISK.items():
        if any(pattern.search(question) for pattern in patterns):
            found.append(topic)
    return tuple(found)


@dataclass
class EvidenceAssessment:
    """The confidence decision and the reasons behind it.

    Reasons are kept so the interface can explain a qualification honestly,
    and so an operator reviewing a bad answer can see what the policy saw.
    """

    confidence: Confidence
    chunks: list[RetrievedChunk] = field(default_factory=list)
    reasons: tuple[str, ...] = ()
    risk_topics: tuple[RiskTopic, ...] = ()
    # Distinct documents behind the evidence. One passage from one page is
    # weaker support than agreeing passages from two.
    document_count: int = 0
    oldest_verification_days: int | None = None
    # True when the evidence is in a different language from the answer, which
    # section 3 requires be disclosed.
    cross_language: bool = False

    @property
    def has_emergency_topic(self) -> bool:
        return RiskTopic.EMERGENCY in self.risk_topics or (
            RiskTopic.CHILD_PROTECTION in self.risk_topics
        )


def _age_in_days(timestamp: object, now: dt.datetime) -> int | None:
    """Return the age of a timestamp in days, or None when it is absent."""
    if not isinstance(timestamp, dt.datetime):
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.UTC)
    return max(0, (now - timestamp).days)


def assess(
    result: SearchResult,
    question: str,
    *,
    answer_language: str = "de",
    now: dt.datetime | None = None,
) -> EvidenceAssessment:
    """Decide how far the retrieved evidence supports an answer.

    Deterministic and computed before the model runs. Every downgrade records
    a reason, so nothing about the outcome depends on the model's opinion of
    its own reliability.
    """
    now = now or dt.datetime.now(dt.UTC)
    risk_topics = classify_risk(question)
    chunks = result.chunks
    reasons: list[str] = []

    if len(chunks) < MIN_USABLE_CHUNKS:
        return EvidenceAssessment(
            confidence=Confidence.INSUFFICIENT,
            reasons=("no_matching_sources",),
            risk_topics=risk_topics,
        )

    documents = {chunk.document_id for chunk in chunks}
    strongest = max(chunk.fused_score for chunk in chunks)
    found_by_both = any(chunk.found_by_both for chunk in chunks)

    ages = [
        age
        for age in (
            _age_in_days(chunk.last_verified_at or chunk.retrieved_at, now) for chunk in chunks
        )
        if age is not None
    ]
    oldest = max(ages) if ages else None

    cross_language = any(
        chunk.language and chunk.language != answer_language for chunk in chunks
    )

    # Start optimistic and downgrade. Every step down names its cause, so a
    # qualification shown to a resident can say something true.
    confidence = Confidence.HIGH

    if strongest < WEAK_SCORE_THRESHOLD:
        confidence = Confidence.LOW
        reasons.append("weak_match")

    if not found_by_both:
        # Only one arm found anything. Either the wording matched but the
        # meaning did not, or the reverse.
        confidence = min(confidence, Confidence.MEDIUM, key=_severity)
        reasons.append("single_retrieval_signal")

    if len(documents) < 2:
        # One source can still be authoritative, so this is a qualification
        # rather than a downgrade to low.
        confidence = min(confidence, Confidence.MEDIUM, key=_severity)
        reasons.append("single_source")

    if not result.semantic_available:
        confidence = min(confidence, Confidence.MEDIUM, key=_severity)
        reasons.append(result.degraded_reason or "semantic_unavailable")

    if oldest is not None and oldest > FRESHNESS_STALE_DAYS:
        confidence = Confidence.LOW
        reasons.append("source_not_verified_within_a_year")
    elif oldest is not None and oldest > FRESHNESS_WARNING_DAYS:
        confidence = min(confidence, Confidence.MEDIUM, key=_severity)
        reasons.append("source_not_recently_verified")

    if cross_language:
        confidence = min(confidence, Confidence.MEDIUM, key=_severity)
        reasons.append("evidence_in_another_language")

    if any(chunk.extraction_quality in ("low", "partial") for chunk in chunks):
        confidence = min(confidence, Confidence.MEDIUM, key=_severity)
        reasons.append("imperfect_text_extraction")

    if any(chunk.injection_flagged for chunk in chunks):
        # Content flagged for instruction-shaped text reached the index, which
        # means a reviewer approved it. It still lowers confidence, because
        # the flag means the page is unusual.
        confidence = min(confidence, Confidence.LOW, key=_severity)
        reasons.append("source_flagged_for_review")

    # High-risk topics never answer at high confidence. Section 12 requires a
    # limitation notice and verification with the responsible authority, and
    # presenting a tax deadline as certain is exactly what must not happen.
    if risk_topics and confidence is Confidence.HIGH:
        confidence = Confidence.MEDIUM
        reasons.append("high_risk_topic")

    return EvidenceAssessment(
        confidence=confidence,
        chunks=chunks,
        reasons=tuple(dict.fromkeys(reasons)),
        risk_topics=risk_topics,
        document_count=len(documents),
        oldest_verification_days=oldest,
        cross_language=cross_language,
    )


_SEVERITY_ORDER = {
    Confidence.HIGH: 3,
    Confidence.MEDIUM: 2,
    Confidence.LOW: 1,
    Confidence.INSUFFICIENT: 0,
}


def _severity(confidence: Confidence) -> int:
    """Order confidence so ``min`` picks the more cautious of two values."""
    return _SEVERITY_ORDER[confidence]
