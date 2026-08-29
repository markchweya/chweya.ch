"""Writing and verifying the tamper-evident audit log.

Every entry carries a hash of its own content chained to the previous entry's
hash. Editing, reordering or deleting a row breaks verification from that
point onward, and :func:`verify_chain` reports where the break is.

This detects tampering. It does not prevent it. Prevention comes from the
privilege revocation in the initial migration and from shipping entries
off-host, which the operations runbook covers.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.audit import GENESIS_HASH, AuditAction, AuditEvent, AuditOutcome

# Keys whose values must never be written to the audit log, matched
# case-insensitively as substrings so that "new_password" and
# "authorization_header" are both caught.
#
# This is a safety net for mistakes, not a licence to pass secrets and rely on
# filtering. The caller is responsible for what it hands over.
SENSITIVE_KEY_FRAGMENTS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "auth_header",
    "cookie",
    "session_id",
    "private_key",
    "credential",
)

REDACTED = "[redacted]"

# Bounds the size of one detail payload. An unbounded dictionary would let a
# single event fill the table, and the log has to keep working under abuse.
MAX_DETAIL_BYTES = 8192


def redact(detail: dict[str, Any]) -> dict[str, Any]:
    """Return ``detail`` with sensitive values replaced, recursively."""
    cleaned: dict[str, Any] = {}
    for key, value in detail.items():
        lowered = str(key).lower()
        if any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS):
            cleaned[key] = REDACTED
        elif isinstance(value, dict):
            cleaned[key] = redact(value)
        elif isinstance(value, list):
            cleaned[key] = [redact(v) if isinstance(v, dict) else v for v in value]
        else:
            cleaned[key] = value
    return cleaned


def _canonical(payload: dict[str, Any]) -> bytes:
    """Serialise a payload so the same content always hashes identically.

    Sorted keys, no incidental whitespace, and ensure_ascii so that a
    non-ASCII character cannot hash differently depending on the writer's
    encoding.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def compute_entry_hash(
    *,
    previous_hash: str,
    occurred_at_iso: str,
    actor_label: str,
    action: str,
    outcome: str,
    object_type: str | None,
    object_id: str | None,
    detail: dict[str, Any],
) -> str:
    """Return the chained hash for one entry.

    Covers the previous hash and every field that carries meaning. Fields
    excluded from the hash could be altered without detection, so the only
    omissions are the surrogate primary key and indexes derived from the
    hashed fields.
    """
    return hashlib.sha256(
        _canonical(
            {
                "previous_hash": previous_hash,
                "occurred_at": occurred_at_iso,
                "actor_label": actor_label,
                "action": action,
                "outcome": outcome,
                "object_type": object_type,
                "object_id": object_id,
                "detail": detail,
            }
        )
    ).hexdigest()


def _latest_hash(session: Session) -> str:
    """Return the most recent entry's hash, or the genesis value."""
    row = session.execute(
        select(AuditEvent.entry_hash).order_by(AuditEvent.id.desc()).limit(1)
    ).scalar_one_or_none()
    return row or GENESIS_HASH


def record(
    session: Session,
    *,
    action: AuditAction,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    actor_user_id: uuid.UUID | None = None,
    actor_label: str = "system",
    object_type: str | None = None,
    object_id: str | None = None,
    request_id: str | None = None,
    client_address_hash: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append one entry to the audit log.

    The entry is added to ``session`` but not committed, so the audit record
    and the change it describes commit together. An action that is rolled back
    must not leave an audit entry claiming it happened.

    ``actor_label`` must not be an email address. Use an opaque identifier or a
    component name, so that pruning a user under the retention policy does not
    leave personal data behind in the log.
    """
    payload = redact(detail or {})

    encoded = _canonical(payload)
    if len(encoded) > MAX_DETAIL_BYTES:
        # Truncate rather than refuse. Losing detail is much better than losing
        # the fact that the action happened.
        payload = {
            "truncated": True,
            "original_bytes": len(encoded),
            "note": "detail exceeded MAX_DETAIL_BYTES and was dropped",
        }

    previous_hash = _latest_hash(session)

    event = AuditEvent(
        actor_user_id=actor_user_id,
        actor_label=actor_label,
        action=action.value,
        outcome=outcome.value,
        object_type=object_type,
        object_id=object_id,
        request_id=request_id,
        client_address_hash=client_address_hash,
        detail=payload,
        previous_hash=previous_hash,
        entry_hash="",  # replaced below, once the timestamp is known
    )
    session.add(event)
    # Assigns the primary key and the server-side occurred_at default, both of
    # which the hash needs, without ending the transaction.
    session.flush()

    event.entry_hash = compute_entry_hash(
        previous_hash=previous_hash,
        occurred_at_iso=event.occurred_at.isoformat(),
        actor_label=event.actor_label,
        action=event.action,
        outcome=event.outcome,
        object_type=event.object_type,
        object_id=event.object_id,
        detail=payload,
    )
    session.flush()
    return event


class ChainVerification:
    """Outcome of verifying the audit chain."""

    def __init__(self, checked: int, broken_at: int | None, reason: str | None = None) -> None:
        self.checked = checked
        self.broken_at = broken_at
        self.reason = reason

    @property
    def ok(self) -> bool:
        return self.broken_at is None

    def __repr__(self) -> str:
        if self.ok:
            return f"<ChainVerification ok checked={self.checked}>"
        return f"<ChainVerification BROKEN at id={self.broken_at} reason={self.reason!r}>"


def verify_chain(session: Session, *, start_after_id: int = 0, limit: int | None = None) -> ChainVerification:
    """Walk the audit log and confirm the hash chain is intact.

    Returns the identifier of the first entry that fails, so an investigation
    knows where history was altered. Run from the operations runbook, and by
    the test suite.
    """
    query = select(AuditEvent).where(AuditEvent.id > start_after_id).order_by(AuditEvent.id.asc())
    if limit is not None:
        query = query.limit(limit)

    expected_previous = GENESIS_HASH
    if start_after_id:
        prior = session.execute(
            select(AuditEvent.entry_hash).where(AuditEvent.id == start_after_id)
        ).scalar_one_or_none()
        if prior is None:
            return ChainVerification(0, start_after_id, "start_after_id does not exist")
        expected_previous = prior

    checked = 0
    for event in session.execute(query).scalars():
        if event.previous_hash != expected_previous:
            return ChainVerification(checked, event.id, "previous_hash does not match the prior entry")

        recomputed = compute_entry_hash(
            previous_hash=event.previous_hash,
            occurred_at_iso=event.occurred_at.isoformat(),
            actor_label=event.actor_label,
            action=event.action,
            outcome=event.outcome,
            object_type=event.object_type,
            object_id=event.object_id,
            detail=event.detail,
        )
        if recomputed != event.entry_hash:
            return ChainVerification(checked, event.id, "entry content does not match its hash")

        expected_previous = event.entry_hash
        checked += 1

    return ChainVerification(checked, None)
