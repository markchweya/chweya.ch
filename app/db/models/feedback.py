"""Resident feedback on answers.

One row per thumb. Deliberately narrow: the question is never stored, which
is the section 18 rule, and the answer text is not stored either, because a
transcript nobody agreed to keep should not accumulate one thumb at a time.
What remains is enough to see how often answers are disliked, whether
refusals draw complaints, and which cited pages sit under the answers people
flag.
"""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid_pk


class AnswerFeedback(Base, TimestampMixin):
    """One thumbs up or down on one answer."""

    __tablename__ = "answer_feedback"
    __table_args__ = (
        CheckConstraint("vote IN ('up', 'down')", name="vote_known"),
    )

    id: Mapped[object] = uuid_pk()
    vote: Mapped[str] = mapped_column(String(8), nullable=False)
    # The answer's coarse shape, so a dislike can be read in context without
    # storing the conversation: which language, how confident the system
    # claimed to be, and whether the answer was a refusal.
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="", server_default="")
    # Which canton the answer served; see cantons/.
    canton: Mapped[str] = mapped_column(String(16), nullable=False, default="zug", server_default="zug")
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")
    is_refusal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # The cited pages, as URLs. A page that keeps appearing under disliked
    # answers is a page worth re-reading.
    citation_urls: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")

    def __repr__(self) -> str:
        return f"<AnswerFeedback {self.vote}>"
