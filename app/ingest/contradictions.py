"""Detecting inconsistencies between indexed passages.

What this does: notices that two passages about apparently the same thing
state different fees, deadlines, phone numbers or opening hours, and files a
finding for a person to look at.

What it deliberately does not do: decide which one is right. Section 9
prohibits it, and for good reason. Two Zug pages stating different fees might
be a stale page, two genuinely different services, or a typo, and nothing
available here distinguishes those. A system that picked a winner would put a
wrong fee in front of residents with its own confidence behind it.

Precision matters more than recall. Every finding costs a reviewer's
attention, and a queue full of false positives is a queue nobody reads, which
is worse than no queue.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Chunk, ContentStatus, Document, DocumentVersion
from app.db.models.review import ContradictionFinding, ContradictionKind, ReviewState
from app.observability import get_logger

logger = get_logger(__name__)

# Swiss franc amounts. Handles "CHF 20.--", "CHF 20.00", "20 Franken",
# "Fr. 20.-" and the thousands separator forms used on cantonal pages.
MONEY = re.compile(
    r"(?:CHF|Fr\.?|SFr\.?)\s*([\d'’.,]+)(?:\s*[.-]{1,2})?|([\d'’.,]+)\s*(?:Franken|francs|franchi)",
    re.IGNORECASE,
)

# Deadlines expressed as a count of days, weeks or months.
DEADLINE = re.compile(
    r"(?:innert|innerhalb\s+von|within|dans\s+un\s+d[ée]lai\s+de|entro)\s+"
    r"(\d{1,3})\s*(Tage?n?|Wochen?|Monate?n?|days?|weeks?|months?|jours?|semaines?|mois|giorni|settimane|mesi)",
    re.IGNORECASE,
)

# Swiss telephone numbers in the forms cantonal pages actually use.
PHONE = re.compile(r"(?:\+41|0041|0)\s?\(?0?\d{1,2}\)?[\s./-]?\d{3}[\s./-]?\d{2}[\s./-]?\d{2}")

# Opening hours such as "08.00 - 11.30" or "8:00-12:00".
HOURS = re.compile(r"\b([01]?\d|2[0-3])[.:]([0-5]\d)\s*(?:-|bis|to|à|alle)\s*([01]?\d|2[0-3])[.:]([0-5]\d)")

# Terms that identify what a passage is about. Two passages are only compared
# when they share enough of these, which is what keeps the queue readable.
SUBJECT_STOPWORDS = frozenset(
    {
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem",
        "und", "oder", "für", "fur", "von", "mit", "bei", "auf", "ist", "sind",
        "wird", "werden", "kann", "muss", "sie", "ihre", "ihren", "the", "and",
        "for", "with", "you", "your", "must", "can", "will", "les", "une",
        "pour", "avec", "vous", "che", "per", "con", "sono",
    }
)

MIN_SHARED_TERMS = 3
MIN_TERM_LENGTH = 5


def _subject_terms(text: str) -> set[str]:
    """Return the meaningful terms in a passage.

    Long words only, because German compounds carry the subject:
    "Einwohnerkontrolle" identifies a topic and "bei der" does not.
    """
    words = re.findall(rf"\w{{{MIN_TERM_LENGTH},}}", text.lower(), re.UNICODE)
    return {word for word in words if word not in SUBJECT_STOPWORDS}


def _normalise_amount(raw: str) -> float | None:
    """Parse a Swiss-formatted amount into a number.

    Handles the apostrophe thousands separator and both decimal marks, so
    "1'250.00" and "1250,00" compare equal.
    """
    cleaned = raw.replace("'", "").replace("’", "").strip()
    if cleaned.count(",") == 1 and cleaned.count(".") == 0:
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    cleaned = cleaned.rstrip(".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_amounts(text: str) -> set[float]:
    """Return the franc amounts stated in a passage."""
    found: set[float] = set()
    for match in MONEY.finditer(text):
        raw = match.group(1) or match.group(2) or ""
        value = _normalise_amount(raw)
        # Amounts above a million on a service page are almost always a year
        # or a reference number that matched by accident.
        if value is not None and 0 < value < 1_000_000:
            found.add(value)
    return found


def extract_deadlines(text: str) -> set[tuple[int, str]]:
    """Return deadlines as (count, normalised unit)."""
    units = {
        "tag": "days", "tage": "days", "tagen": "days", "day": "days", "days": "days",
        "jour": "days", "jours": "days", "giorni": "days",
        "woche": "weeks", "wochen": "weeks", "week": "weeks", "weeks": "weeks",
        "semaine": "weeks", "semaines": "weeks", "settimane": "weeks",
        "monat": "months", "monate": "months", "monaten": "months",
        "month": "months", "months": "months", "mois": "months", "mesi": "months",
    }
    found: set[tuple[int, str]] = set()
    for match in DEADLINE.finditer(text):
        count = int(match.group(1))
        unit = units.get(match.group(2).lower().rstrip("n"), "")
        if unit and 0 < count <= 400:
            found.add((count, unit))
    return found


def extract_phones(text: str) -> set[str]:
    """Return phone numbers, digits only, so formatting differences collapse."""
    return {re.sub(r"\D", "", match.group()) for match in PHONE.finditer(text)}


def extract_hours(text: str) -> set[str]:
    """Return opening hour ranges in a canonical form."""
    return {
        f"{int(m.group(1)):02d}:{m.group(2)}-{int(m.group(3)):02d}:{m.group(4)}"
        for m in HOURS.finditer(text)
    }


@dataclass
class Candidate:
    """A passage reduced to what the detector compares."""

    chunk_id: object
    document_id: object
    text: str
    terms: set[str]
    amounts: set[float]
    deadlines: set[tuple[int, str]]
    phones: set[str]
    hours: set[str]


def _priority(kind: ContradictionKind, first: str, second: str) -> int:
    """Rank a finding for the review queue.

    A deadline conflict outranks a fee conflict: missing a registration
    deadline has consequences a resident cannot undo, while paying the wrong
    fee is corrected at the counter.
    """
    base = {
        ContradictionKind.DEADLINE: 90,
        ContradictionKind.ELIGIBILITY: 80,
        ContradictionKind.FEE: 70,
        ContradictionKind.CONTACT: 60,
        ContradictionKind.OPENING_HOURS: 40,
        ContradictionKind.TRANSLATION_MISMATCH: 50,
        ContradictionKind.DUPLICATE_WITH_DIFFERENT_VALUES: 65,
    }[kind]

    # Widen the gap and the finding matters more.
    if kind is ContradictionKind.FEE:
        try:
            gap = abs(float(first) - float(second))
            if gap >= 100:
                base += 15
            elif gap < 5:
                base -= 15
        except ValueError:
            pass
    return max(1, min(100, base))


def _load_candidates(session: Session, limit: int = 5000) -> list[Candidate]:
    """Load approved passages with their extracted values."""
    rows = session.execute(
        select(Chunk.id, Chunk.document_id, Chunk.text)
        .join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Document.current_version_id == DocumentVersion.id,
            DocumentVersion.status == ContentStatus.APPROVED.value,
        )
        .limit(limit)
    ).all()

    candidates: list[Candidate] = []
    for chunk_id, document_id, text in rows:
        candidates.append(
            Candidate(
                chunk_id=chunk_id,
                document_id=document_id,
                text=text,
                terms=_subject_terms(text),
                amounts=extract_amounts(text),
                deadlines=extract_deadlines(text),
                phones=extract_phones(text),
                hours=extract_hours(text),
            )
        )
    return candidates


def detect(session: Session, *, min_shared_terms: int = MIN_SHARED_TERMS) -> list[ContradictionFinding]:
    """Compare approved passages and file findings for a reviewer.

    Passages are only compared when they come from different documents and
    share enough subject terms. Comparing everything with everything would be
    quadratic and would fill the queue with two unrelated services that happen
    to charge different fees.
    """
    candidates = _load_candidates(session)

    # Group by shared term so the comparison is not quadratic over the corpus.
    by_term: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        for term in candidate.terms:
            by_term[term].append(candidate)

    seen_pairs: set[tuple[object, object]] = set()
    findings: list[ContradictionFinding] = []

    for group in by_term.values():
        if len(group) < 2 or len(group) > 60:
            # A term shared by dozens of passages is a common word, not a
            # subject. Comparing them all yields noise.
            continue

        for index, first in enumerate(group):
            for second in group[index + 1 :]:
                if first.document_id == second.document_id:
                    continue
                pair = tuple(sorted((str(first.chunk_id), str(second.chunk_id))))
                if pair in seen_pairs:
                    continue

                shared = first.terms & second.terms
                if len(shared) < min_shared_terms:
                    continue
                seen_pairs.add(pair)

                findings.extend(_compare(first, second, sorted(shared)[:8]))

    for finding in findings:
        session.add(finding)

    logger.info("contradictions.detected", findings=len(findings), passages=len(candidates))
    return findings


def _compare(first: Candidate, second: Candidate, shared: list[str]) -> list[ContradictionFinding]:
    """Compare two passages and return any findings."""
    findings: list[ContradictionFinding] = []
    subject = ", ".join(shared[:3])

    def add(kind: ContradictionKind, a: str, b: str, explanation: str) -> None:
        findings.append(
            ContradictionFinding(
                kind=kind.value,
                state=ReviewState.OPEN.value,
                priority=_priority(kind, a, b),
                first_chunk_id=first.chunk_id,
                second_chunk_id=second.chunk_id,
                first_value=a,
                second_value=b,
                explanation=explanation,
                shared_context=shared,
            )
        )

    if first.amounts and second.amounts and first.amounts != second.amounts:
        a, b = sorted(first.amounts)[0], sorted(second.amounts)[0]
        add(
            ContradictionKind.FEE,
            f"{a:.2f}",
            f"{b:.2f}",
            f"Two passages about {subject} state different amounts: "
            f"CHF {a:.2f} and CHF {b:.2f}. They may cover different services, "
            f"or one may be out of date.",
        )

    if first.deadlines and second.deadlines and first.deadlines != second.deadlines:
        a = sorted(first.deadlines)[0]
        b = sorted(second.deadlines)[0]
        add(
            ContradictionKind.DEADLINE,
            f"{a[0]} {a[1]}",
            f"{b[0]} {b[1]}",
            f"Two passages about {subject} state different deadlines: "
            f"{a[0]} {a[1]} and {b[0]} {b[1]}.",
        )

    if first.phones and second.phones and not (first.phones & second.phones):
        a, b = sorted(first.phones)[0], sorted(second.phones)[0]
        add(
            ContradictionKind.CONTACT,
            a,
            b,
            f"Two passages about {subject} give different telephone numbers.",
        )

    if first.hours and second.hours and not (first.hours & second.hours):
        a, b = sorted(first.hours)[0], sorted(second.hours)[0]
        add(
            ContradictionKind.OPENING_HOURS,
            a,
            b,
            f"Two passages about {subject} state different opening hours: {a} and {b}.",
        )

    return findings


def open_findings_for_chunks(session: Session, chunk_ids: list[object]) -> int:
    """Count unresolved findings touching any of these passages.

    Used by the confidence policy: an answer drawing on evidence with an
    unresolved contradiction must say the official sources appear inconsistent.
    """
    if not chunk_ids:
        return 0
    open_states = [state.value for state in ReviewState if state.is_open]
    return int(
        session.execute(
            select(func.count(ContradictionFinding.id))
            .where(
                ContradictionFinding.state.in_(open_states),
                (ContradictionFinding.first_chunk_id.in_(chunk_ids))
                | (ContradictionFinding.second_chunk_id.in_(chunk_ids)),
            )
        ).scalar_one()
    )
