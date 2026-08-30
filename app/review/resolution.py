"""Resolving a contradiction finding.

The detector never decides which official statement is correct; section 9
reserves that for a person. This module is where the person's decision takes
effect, and the design constraint is stated in the review documentation:

* "Not a contradiction" will be the most common outcome, and it must be a
  first-class one. Forcing a reviewer to imply that one page is wrong when
  two services legitimately differ would corrupt the record.
* A resolution that takes official content out of the index requires a
  written reason. Removing a canton page from retrieval is a real decision
  with a real cost, and a decision with no recorded reason cannot be
  revisited when the canton clarifies.
* "Unresolved" is not a resolution. It records that a person looked and
  could not tell, keeps the finding open, and keeps the qualification on
  every answer that touches the affected passages. It can be returned to.

Every outcome writes its audit entries in the same transaction as the change
it describes.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AuditAction,
    Chunk,
    ContentStatus,
    ContradictionFinding,
    Document,
    DocumentVersion,
    ReviewState,
    User,
)
from app.observability import get_logger
from app.security.audit import record

logger = get_logger(__name__)

# The outcomes a reviewer may choose, in the order the interface offers them.
# Everything else in ReviewState is machinery (OPEN, IN_REVIEW), not a choice.
RESOLUTIONS: tuple[ReviewState, ...] = (
    ReviewState.NOT_A_CONTRADICTION,
    ReviewState.RESOLVED_FIRST_CURRENT,
    ReviewState.RESOLVED_SECOND_CURRENT,
    ReviewState.RESOLVED_BOTH_EXCLUDED,
    ReviewState.UNRESOLVED,
)

# Outcomes that remove content from the public index, and therefore require
# a written reason.
EXCLUDING_RESOLUTIONS = frozenset(
    {
        ReviewState.RESOLVED_FIRST_CURRENT,
        ReviewState.RESOLVED_SECOND_CURRENT,
        ReviewState.RESOLVED_BOTH_EXCLUDED,
    }
)

# States a reviewer may act on. The three RESOLVED_* states and
# NOT_A_CONTRADICTION are final: reopening a decided finding would let a
# second reviewer silently overrule the first with no trace in the finding
# itself. UNRESOLVED stays actionable, because it means "waiting for the
# canton", and the canton eventually answers.
ACTIONABLE_STATES = frozenset(
    {ReviewState.OPEN, ReviewState.IN_REVIEW, ReviewState.UNRESOLVED}
)


@dataclass(frozen=True)
class FindingContext:
    """One finding with everything a reviewer needs to decide.

    Both passages travel with their document titles, URLs and version dates,
    because the review documentation promises exactly that: the reviewer sees
    what the detector compared, not an identifier to chase through four
    tables.
    """

    finding: ContradictionFinding
    first_chunk: Chunk | None
    second_chunk: Chunk | None
    first_document: Document | None
    second_document: Document | None
    first_version: DocumentVersion | None
    second_version: DocumentVersion | None


def load_context(db: Session, finding: ContradictionFinding) -> FindingContext:
    """Load both sides of a finding for display."""

    def side(chunk_id: uuid.UUID):  # type: ignore[no-untyped-def]
        chunk = db.get(Chunk, chunk_id)
        if chunk is None:
            return None, None, None
        return (
            chunk,
            db.get(Document, chunk.document_id),
            db.get(DocumentVersion, chunk.version_id),
        )

    first_chunk, first_document, first_version = side(finding.first_chunk_id)
    second_chunk, second_document, second_version = side(finding.second_chunk_id)
    return FindingContext(
        finding=finding,
        first_chunk=first_chunk,
        second_chunk=second_chunk,
        first_document=first_document,
        second_document=second_document,
        first_version=first_version,
        second_version=second_version,
    )


def open_queue(db: Session, *, limit: int = 100) -> list[ContradictionFinding]:
    """Findings awaiting a decision, most urgent first.

    UNRESOLVED is included: it is open by definition, and a queue that hides
    what nobody could decide is a queue that quietly forgets it.
    """
    states = [state.value for state in ACTIONABLE_STATES]
    return list(
        db.execute(
            select(ContradictionFinding)
            .where(ContradictionFinding.state.in_(states))
            .order_by(
                ContradictionFinding.priority.desc(),
                ContradictionFinding.created_at.asc(),
            )
            .limit(limit)
        ).scalars()
    )


def recent_decisions(db: Session, *, limit: int = 10) -> list[ContradictionFinding]:
    """The latest decided findings, so the queue page shows its own history."""
    states = [state.value for state in ReviewState if state not in ACTIONABLE_STATES]
    return list(
        db.execute(
            select(ContradictionFinding)
            .where(ContradictionFinding.state.in_(states))
            # nullslast: a finding decided directly in the database has no
            # resolved_at, and it should not outrank every real decision.
            .order_by(ContradictionFinding.resolved_at.desc().nullslast())
            .limit(limit)
        ).scalars()
    )


def claim(
    db: Session,
    finding: ContradictionFinding,
    *,
    actor: User,
    request_id: str | None = None,
) -> list[str]:
    """Mark a finding as being looked at.

    Advisory, not a lock: it tells a second reviewer that someone is already
    on it, and nothing more. A claimed finding can still be resolved by
    anyone with the permission, because a reviewer who went home must not
    freeze the queue.
    """
    if ReviewState(finding.state) is not ReviewState.OPEN:
        return ["review.not_open"]

    finding.state = ReviewState.IN_REVIEW.value
    record(
        db,
        action=AuditAction.CONTRADICTION_RESOLVED,
        actor_user_id=actor.id,
        actor_label=f"user:{actor.id}",
        object_type="contradiction",
        object_id=str(finding.id),
        request_id=request_id,
        detail={"step": "claimed", "kind": finding.kind},
    )
    return []


def _exclude_version(
    db: Session,
    version: DocumentVersion | None,
    *,
    actor: User,
    finding: ContradictionFinding,
    note: str,
    request_id: str | None,
) -> None:
    """Take one document version out of the public index.

    Only an APPROVED version changes state; one already superseded, excluded
    or gone is left as it is, so resolving an old finding cannot resurrect or
    reclassify history. The exclusion self-heals: when the canton fixes the
    page, the next crawl files a new version, and approval of that version is
    a fresh decision.
    """
    if version is None or version.status != ContentStatus.APPROVED.value:
        return

    version.status = ContentStatus.EXCLUDED.value
    version.reviewed_by_id = actor.id
    version.reviewed_at = dt.datetime.now(dt.UTC)
    version.review_note = f"contradiction {finding.id}: {note}"[:2000]

    document = db.get(Document, version.document_id)
    if document is not None and document.current_version_id == version.id:
        document.current_version_id = None

    record(
        db,
        action=AuditAction.CONTENT_EXCLUDED,
        actor_user_id=actor.id,
        actor_label=f"user:{actor.id}",
        object_type="document_version",
        object_id=str(version.id),
        request_id=request_id,
        detail={"contradiction_id": str(finding.id), "reason": note[:200]},
    )


def resolve(
    db: Session,
    finding: ContradictionFinding,
    outcome: str,
    *,
    actor: User,
    note: str = "",
    request_id: str | None = None,
) -> list[str]:
    """Apply a reviewer's decision to a finding.

    Returns a list of problems as message keys; empty means it was applied.
    """
    try:
        target = ReviewState(outcome)
    except ValueError:
        return ["review.unknown_outcome"]
    if target not in RESOLUTIONS:
        return ["review.unknown_outcome"]

    if ReviewState(finding.state) not in ACTIONABLE_STATES:
        return ["review.already_decided"]

    note = note.strip()
    if target in EXCLUDING_RESOLUTIONS and not note:
        # Removing official content from the index with no recorded reason
        # leaves nothing to revisit when the canton clarifies.
        return ["review.note_required"]

    context = load_context(db, finding)

    if target is ReviewState.RESOLVED_FIRST_CURRENT:
        # The first passage is right, so the version carrying the second
        # leaves the index until the canton's page changes.
        _exclude_version(
            db, context.second_version, actor=actor, finding=finding,
            note=note, request_id=request_id,
        )
    elif target is ReviewState.RESOLVED_SECOND_CURRENT:
        _exclude_version(
            db, context.first_version, actor=actor, finding=finding,
            note=note, request_id=request_id,
        )
    elif target is ReviewState.RESOLVED_BOTH_EXCLUDED:
        _exclude_version(
            db, context.first_version, actor=actor, finding=finding,
            note=note, request_id=request_id,
        )
        _exclude_version(
            db, context.second_version, actor=actor, finding=finding,
            note=note, request_id=request_id,
        )
    # NOT_A_CONTRADICTION and UNRESOLVED touch no content. The first records
    # that both statements stand; the second keeps the finding open, which
    # keeps the inconsistency notice on every answer drawing on either side.

    finding.state = target.value
    finding.reviewer_note = note[:2000]
    # For UNRESOLVED these record who looked and when, not that it is done;
    # the state says it is not.
    finding.resolved_by_id = actor.id
    finding.resolved_at = dt.datetime.now(dt.UTC)

    record(
        db,
        action=AuditAction.CONTRADICTION_RESOLVED,
        actor_user_id=actor.id,
        actor_label=f"user:{actor.id}",
        object_type="contradiction",
        object_id=str(finding.id),
        request_id=request_id,
        detail={
            "outcome": target.value,
            "kind": finding.kind,
            "note": note[:200],
        },
    )
    logger.info("review.resolved", outcome=target.value, kind=finding.kind)
    return []
