"""Administrator bootstrap behaviour.

The requirement that carries the most weight is in section 5: a deleted
administrator must not be silently recreated. A bootstrap command that quietly
restores an account somebody deliberately removed is a backdoor, however well
intentioned.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.cli.bootstrap_admin import BootstrapRefused, bootstrap_admin
from app.db.models import RoleName
from app.security.audit import verify_chain
from app.security.passwords import verify_password

GOOD_PASSWORD = "a-genuinely-long-bootstrap-password-1"


def seed_roles(db) -> None:  # type: ignore[no-untyped-def]
    """Re-seed roles, which TRUNCATE removed.

    The roles are created by migration 0001, so a truncating fixture has to put
    them back.
    """
    rows = [
        ("super_admin", "Full administrative access."),
        ("content_admin", "Manages sources and uploads."),
        ("reviewer", "Resolves contradiction findings."),
        ("support_operator", "Reads anonymised feedback."),
        ("auditor", "Read-only access to audit events."),
    ]
    for name, description in rows:
        db.execute(
            text("INSERT INTO roles (name, description) VALUES (:n, :d) ON CONFLICT DO NOTHING"),
            {"n": name, "d": description},
        )
    db.commit()


@pytest.fixture
def ready(db):  # type: ignore[no-untyped-def]
    seed_roles(db)
    return db


class TestFirstRun:
    def test_creates_an_administrator(self, ready) -> None:  # type: ignore[no-untyped-def]
        result = bootstrap_admin(ready, email="admin@example.ch", password=GOOD_PASSWORD)
        ready.commit()
        assert result.created

        row = ready.execute(
            text("SELECT email, must_change_password, is_active, password_algorithm FROM users")
        ).one()
        assert row.email == "admin@example.ch"
        assert row.must_change_password is True, "the bootstrap credential is good for one login"
        assert row.is_active is True
        assert row.password_algorithm == "argon2id"

    def test_grants_super_admin(self, ready) -> None:  # type: ignore[no-untyped-def]
        bootstrap_admin(ready, email="admin@example.ch", password=GOOD_PASSWORD)
        ready.commit()
        granted = ready.execute(
            text("SELECT r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id")
        ).scalar_one()
        assert granted == RoleName.SUPER_ADMIN.value

    def test_password_is_hashed_and_verifiable(self, ready) -> None:  # type: ignore[no-untyped-def]
        bootstrap_admin(ready, email="admin@example.ch", password=GOOD_PASSWORD)
        ready.commit()
        stored = ready.execute(text("SELECT password_hash FROM users")).scalar_one()

        assert GOOD_PASSWORD not in stored
        assert stored.startswith("$argon2id$")
        assert verify_password(stored, GOOD_PASSWORD)[0]
        assert not verify_password(stored, "wrong")[0]

    def test_email_is_normalised_to_lower_case(self, ready) -> None:  # type: ignore[no-untyped-def]
        bootstrap_admin(ready, email="Admin@Example.CH", password=GOOD_PASSWORD)
        ready.commit()
        assert ready.execute(text("SELECT email FROM users")).scalar_one() == "admin@example.ch"

    def test_audit_entry_records_the_domain_not_the_address(self, ready) -> None:  # type: ignore[no-untyped-def]
        """Enough to identify the environment, without storing the person."""
        bootstrap_admin(ready, email="anna.muster@example.ch", password=GOOD_PASSWORD)
        ready.commit()
        detail = ready.execute(
            text("SELECT detail FROM audit_events WHERE action='admin.bootstrapped'")
        ).scalar_one()
        assert detail["email_domain"] == "example.ch"
        assert "anna.muster" not in str(detail)
        assert verify_chain(ready).ok


class TestRefusals:
    def test_second_run_refuses(self, ready) -> None:  # type: ignore[no-untyped-def]
        bootstrap_admin(ready, email="admin@example.ch", password=GOOD_PASSWORD)
        ready.commit()
        with pytest.raises(BootstrapRefused, match="already bootstrapped"):
            bootstrap_admin(ready, email="second@example.ch", password=GOOD_PASSWORD)

    def test_deleted_administrator_is_not_recreated(self, ready) -> None:  # type: ignore[no-untyped-def]
        """The requirement in section 5, and the reason the marker exists.

        Quietly restoring an account somebody deliberately removed would be a
        backdoor.
        """
        bootstrap_admin(ready, email="admin@example.ch", password=GOOD_PASSWORD)
        ready.commit()
        ready.execute(text("DELETE FROM user_roles"))
        ready.execute(text("DELETE FROM users"))
        ready.commit()

        with pytest.raises(BootstrapRefused, match="already bootstrapped"):
            bootstrap_admin(ready, email="admin@example.ch", password=GOOD_PASSWORD)

        assert ready.execute(text("SELECT count(*) FROM users")).scalar_one() == 0

    def test_force_overrides_and_is_audited(self, ready) -> None:  # type: ignore[no-untyped-def]
        bootstrap_admin(ready, email="admin@example.ch", password=GOOD_PASSWORD)
        ready.commit()
        ready.execute(text("DELETE FROM user_roles"))
        ready.execute(text("DELETE FROM users"))
        ready.commit()

        bootstrap_admin(ready, email="admin@example.ch", password=GOOD_PASSWORD, force=True)
        ready.commit()

        assert ready.execute(text("SELECT count(*) FROM users")).scalar_one() == 1
        forced = ready.execute(
            text("SELECT detail FROM audit_events WHERE action='admin.bootstrapped' ORDER BY id DESC LIMIT 1")
        ).scalar_one()
        assert forced["forced"] is True

    def test_rejects_a_malformed_email(self, ready) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(BootstrapRefused, match="valid administrator email"):
            bootstrap_admin(ready, email="not-an-address", password=GOOD_PASSWORD)

    def test_rejects_a_duplicate_address(self, ready) -> None:  # type: ignore[no-untyped-def]
        """Reaching this refusal needs the two earlier ones cleared.

        The marker check and the active-administrator check both fire first,
        which is the right order: they describe the situation more precisely
        than "that address is taken" would.
        """
        bootstrap_admin(ready, email="admin@example.ch", password=GOOD_PASSWORD)
        ready.commit()
        # Clear the marker and the role grant, leaving the user row in place.
        ready.execute(text("DELETE FROM system_settings"))
        ready.execute(text("DELETE FROM user_roles"))
        ready.commit()
        with pytest.raises(BootstrapRefused, match="already exists"):
            bootstrap_admin(ready, email="admin@example.ch", password=GOOD_PASSWORD)

    def test_refusals_are_ordered_most_specific_first(self, ready) -> None:  # type: ignore[no-untyped-def]
        """The marker explains the situation better than a duplicate-email error."""
        bootstrap_admin(ready, email="admin@example.ch", password=GOOD_PASSWORD)
        ready.commit()
        with pytest.raises(BootstrapRefused, match="already bootstrapped"):
            bootstrap_admin(ready, email="admin@example.ch", password=GOOD_PASSWORD)

    def test_refuses_a_second_active_super_admin_without_force(self, ready) -> None:  # type: ignore[no-untyped-def]
        bootstrap_admin(ready, email="first@example.ch", password=GOOD_PASSWORD)
        ready.commit()
        ready.execute(text("DELETE FROM system_settings"))
        ready.commit()
        with pytest.raises(BootstrapRefused, match="already exist"):
            bootstrap_admin(ready, email="second@example.ch", password=GOOD_PASSWORD)


class TestNoPlaintextAnywhere:
    def test_the_password_reaches_no_column(self, ready) -> None:  # type: ignore[no-untyped-def]
        bootstrap_admin(ready, email="admin@example.ch", password=GOOD_PASSWORD)
        ready.commit()

        leaks = ready.execute(
            text(
                "SELECT count(*) FROM users "
                "WHERE password_hash LIKE :p OR email LIKE :p OR display_name LIKE :p"
            ),
            {"p": f"%{GOOD_PASSWORD}%"},
        ).scalar_one()
        assert leaks == 0

        audit_leaks = ready.execute(
            text("SELECT count(*) FROM audit_events WHERE detail::text LIKE :p"),
            {"p": f"%{GOOD_PASSWORD}%"},
        ).scalar_one()
        assert audit_leaks == 0

    def test_result_object_carries_no_password_field(self, ready) -> None:  # type: ignore[no-untyped-def]
        result = bootstrap_admin(ready, email="admin@example.ch", password=GOOD_PASSWORD)
        assert not any("password" in field.lower() for field in vars(result))
