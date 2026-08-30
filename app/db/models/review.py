"""Contradiction findings and their review.

Section 9 is explicit that detection must not decide which official statement
is correct. A model comparing two canton pages and picking a winner would be
asserting authority it does not have, and getting it wrong would put a wrong
fee in front of residents with the system's confidence behind it.

So a finding records what looks inconsistent, shows both passages with their
dates, assigns a review priority, and waits. Only a person resolves it, and
the resolution is audited.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid_pk


class ContradictionKind(StrEnum):
    """What sort of inconsistency was noticed.

    Named by the observable difference rather than by a guess at the cause. Two
    pages stating different fees may be a stale page, a genuine difference
    between two services, or a typo, and the detector cannot tell which.
    """

    FEE = "fee"
    DEADLINE = "deadline"
    CONTACT = "contact"
    OPENING_HOURS = "opening_hours"
    ELIGIBILITY = "eligibility"
    TRANSLATION_MISMATCH = "translation_mismatch"
    DUPLICATE_WITH_DIFFERENT_VALUES = "duplicate_with_different_values"


class ReviewState(StrEnum):
    """Where a finding is in the review process.

    ``NOT_A_CONTRADICTION`` exists because most findings will be exactly that:
    two different services that legitimately charge different fees. Without it,
    reviewers would have to force real distinctions into a resolution that
    implies one page is wrong.
    """

    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED_FIRST_CURRENT = "resolved_first_current"
    RESOLVED_SECOND_CURRENT = "resolved_second_current"
    RESOLVED_BOTH_EXCLUDED = "resolved_both_excluded"
    NOT_A_CONTRADICTION = "not_a_contradiction"
    UNRESOLVED = "unresolved"

    @property
    def is_open(self) -> bool:
        """Whether an answer drawing on this evidence must lower confidence."""
        return self in (ReviewState.OPEN, ReviewState.IN_REVIEW, ReviewState.UNRESOLVED)


class ContradictionFinding(Base, TimestampMixin):
    """One suspected inconsistency between two passages."""

    __tablename__ = "contradiction_findings"

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    state: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=ReviewState.OPEN.value,
        server_default=ReviewState.OPEN.value,
    )

    # Higher is more urgent. Derived from the kind and from how far apart the
    # values are, so a fee differing by a franc does not outrank one differing
    # by a hundred.
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=50, server_default="50"
    )

    first_chunk_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False
    )
    second_chunk_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False
    )

    # The values that differ, as extracted. Kept so a reviewer sees what the
    # detector actually compared rather than having to infer it.
    first_value: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    second_value: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    # A plain sentence describing the suspicion. Never a verdict.
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # The shared terms that caused the two passages to be compared at all.
    shared_context: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")

    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewer_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    __table_args__ = (
        Index("ix_contradiction_findings_state", "state"),
        Index("ix_contradiction_findings_priority", "priority"),
        Index("ix_contradiction_findings_first_chunk_id", "first_chunk_id"),
        Index("ix_contradiction_findings_second_chunk_id", "second_chunk_id"),
    )

    def __repr__(self) -> str:
        return f"<ContradictionFinding {self.kind} {self.state}>"
