"""Audit log integrity.

The chain has to do two things: record faithfully, and make later alteration
detectable. These tests exercise both against a real PostgreSQL database,
because the tamper cases are SQL statements an operator could run through
Adminer.
"""

from __future__ import annotations

from sqlalchemy import text

from app.db.models import AuditAction
from app.security.audit import record, redact, verify_chain


def append_three(db) -> None:  # type: ignore[no-untyped-def]
    record(db, action=AuditAction.ADMIN_BOOTSTRAPPED, actor_label="cli")
    record(db, action=AuditAction.LOGIN_SUCCEEDED, actor_label="user:a")
    record(db, action=AuditAction.ROLE_GRANTED, actor_label="user:a", detail={"role": "reviewer"})
    db.commit()


class TestRecording:
    def test_chain_verifies_after_appends(self, db) -> None:  # type: ignore[no-untyped-def]
        append_three(db)
        result = verify_chain(db)
        assert result.ok
        assert result.checked == 3

    def test_an_empty_log_verifies(self, db) -> None:  # type: ignore[no-untyped-def]
        assert verify_chain(db).ok

    def test_entry_is_not_committed_by_record_itself(self, db) -> None:  # type: ignore[no-untyped-def]
        """The audit entry must commit with the change it describes, not before.

        An action that is rolled back must not leave a record claiming it
        happened.
        """
        record(db, action=AuditAction.LOGIN_FAILED, actor_label="user:b")
        db.rollback()
        assert verify_chain(db).checked == 0


class TestRedaction:
    def test_sensitive_keys_are_replaced(self, db) -> None:  # type: ignore[no-untyped-def]
        record(
            db,
            action=AuditAction.PASSWORD_CHANGED,
            actor_label="user:a",
            detail={
                "password": "hunter2",
                "new_password": "hunter3",
                "api_key": "sk-live-1",
                "authorization": "Bearer abc",
                "session_id": "s-1",
                "role": "reviewer",
            },
        )
        db.commit()
        stored = db.execute(text("SELECT detail FROM audit_events")).scalar_one()

        assert stored["role"] == "reviewer", "non-sensitive keys must survive"
        for key in ("password", "new_password", "api_key", "authorization", "session_id"):
            assert stored[key] == "[redacted]", key

    def test_redaction_reaches_nested_structures(self) -> None:
        cleaned = redact(
            {"outer": {"token": "t"}, "items": [{"secret": "s"}, {"ok": 1}], "fine": "yes"}
        )
        assert cleaned["outer"]["token"] == "[redacted]"
        assert cleaned["items"][0]["secret"] == "[redacted]"
        assert cleaned["items"][1]["ok"] == 1
        assert cleaned["fine"] == "yes"

    def test_oversized_detail_is_replaced_not_rejected(self, db) -> None:  # type: ignore[no-untyped-def]
        """Losing detail beats losing the record that the action happened."""
        record(
            db,
            action=AuditAction.DOCUMENT_UPLOADED,
            actor_label="user:a",
            detail={"blob": "x" * 20_000},
        )
        db.commit()
        stored = db.execute(text("SELECT detail FROM audit_events")).scalar_one()
        assert stored["truncated"] is True
        assert verify_chain(db).ok, "a truncated payload must still hash consistently"


class TestTamperDetection:
    def test_editing_a_row_breaks_the_chain(self, db) -> None:  # type: ignore[no-untyped-def]
        append_three(db)
        first_id = db.execute(text("SELECT min(id) FROM audit_events")).scalar_one()
        db.execute(text("UPDATE audit_events SET outcome='failure' WHERE id=:i"), {"i": first_id})
        db.commit()

        result = verify_chain(db)
        assert not result.ok
        assert result.broken_at == first_id
        assert "hash" in (result.reason or "")

    def test_restoring_the_value_verifies_again(self, db) -> None:  # type: ignore[no-untyped-def]
        """Detection is content-based, not a one-way tripped flag."""
        append_three(db)
        first_id = db.execute(text("SELECT min(id) FROM audit_events")).scalar_one()
        db.execute(text("UPDATE audit_events SET outcome='failure' WHERE id=:i"), {"i": first_id})
        db.commit()
        assert not verify_chain(db).ok

        db.execute(text("UPDATE audit_events SET outcome='success' WHERE id=:i"), {"i": first_id})
        db.commit()
        assert verify_chain(db).ok

    def test_deleting_a_row_breaks_the_chain(self, db) -> None:  # type: ignore[no-untyped-def]
        append_three(db)
        ids = [r[0] for r in db.execute(text("SELECT id FROM audit_events ORDER BY id"))]
        db.execute(text("DELETE FROM audit_events WHERE id=:i"), {"i": ids[1]})
        db.commit()

        result = verify_chain(db)
        assert not result.ok
        assert result.broken_at == ids[2], "the break shows at the row after the gap"

    def test_altering_the_detail_payload_is_detected(self, db) -> None:  # type: ignore[no-untyped-def]
        """Changing what an action recorded must break the hash."""
        record(
            db,
            action=AuditAction.CONTRADICTION_RESOLVED,
            actor_label="user:a",
            detail={"decision": "superseded"},
        )
        db.commit()
        db.execute(text("""UPDATE audit_events SET detail = '{"decision": "current"}'::jsonb"""))
        db.commit()
        assert not verify_chain(db).ok

    def test_changing_the_actor_is_detected(self, db) -> None:  # type: ignore[no-untyped-def]
        """Reassigning blame for an action must not go unnoticed."""
        append_three(db)
        db.execute(
            text("UPDATE audit_events SET actor_label='someone_else' WHERE id=(SELECT min(id) FROM audit_events)")
        )
        db.commit()
        assert not verify_chain(db).ok

    def test_appending_a_forged_row_is_detected(self, db) -> None:  # type: ignore[no-untyped-def]
        """A row inserted directly, without the chain, does not verify."""
        append_three(db)
        db.execute(
            text(
                "INSERT INTO audit_events "
                "(actor_label, action, outcome, detail, previous_hash, entry_hash) "
                "VALUES ('attacker', 'login.succeeded', 'success', '{}'::jsonb, "
                "repeat('a', 64), repeat('b', 64))"
            )
        )
        db.commit()
        result = verify_chain(db)
        assert not result.ok
