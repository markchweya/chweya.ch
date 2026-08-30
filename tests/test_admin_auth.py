"""Authentication, authorisation and the forced password change.

The definition of done requires that an administrator can log in securely and
that the bootstrap password must be changed. These tests are that claim.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text as sql

from app.cli.bootstrap_admin import bootstrap_admin
from app.db.models import User, UserRole
from app.db.session import db_session
from app.main import create_app
from app.security.auth import Permission, permissions_for
from app.security.passwords import hash_password

BOOTSTRAP = "a-genuinely-long-bootstrap-password-1"
REPLACEMENT = "correct-horse-battery-staple-77"


def seed_roles(db) -> None:  # type: ignore[no-untyped-def]
    for name in ("super_admin", "content_admin", "reviewer", "support_operator", "auditor"):
        db.execute(
            sql("INSERT INTO roles (name, description) VALUES (:n, '') ON CONFLICT DO NOTHING"),
            {"n": name},
        )
    db.commit()


@pytest.fixture
def client(db):  # type: ignore[no-untyped-def]
    seed_roles(db)
    app = create_app()
    app.dependency_overrides[db_session] = lambda: db
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def admin(db):  # type: ignore[no-untyped-def]
    """A bootstrapped administrator who must still change their password."""
    seed_roles(db)
    bootstrap_admin(db, email="admin@example.ch", password=BOOTSTRAP)
    db.commit()
    return db.execute(sql("SELECT id FROM users")).scalar_one()


class TestPermissionMapping:
    def test_super_admin_holds_everything(self) -> None:
        assert permissions_for({"super_admin"}) == frozenset(Permission)

    def test_auditor_can_change_nothing(self) -> None:
        """An account that can change nothing is the point of the role."""
        granted = permissions_for({"auditor"})
        assert Permission.VIEW_AUDIT in granted
        assert Permission.MANAGE_SOURCES not in granted
        assert Permission.MANAGE_USERS not in granted
        assert Permission.APPROVE_CONTENT not in granted

    def test_reviewer_cannot_manage_sources(self) -> None:
        granted = permissions_for({"reviewer"})
        assert Permission.RESOLVE_CONTRADICTIONS in granted
        assert Permission.MANAGE_SOURCES not in granted

    def test_an_unknown_role_grants_nothing(self) -> None:
        """Failing open here would make a typo into super administrator."""
        assert permissions_for({"superadmin", "root", ""}) == frozenset()

    def test_several_roles_combine(self) -> None:
        granted = permissions_for({"content_admin", "reviewer"})
        assert Permission.MANAGE_SOURCES in granted
        assert Permission.RESOLVE_CONTRADICTIONS in granted


class TestLogin:
    def test_correct_credentials_create_a_session(self, client, admin) -> None:  # type: ignore[no-untyped-def]
        response = client.post(
            "/admin/login", data={"email": "admin@example.ch", "password": BOOTSTRAP}
        )
        assert response.status_code == 303
        assert response.cookies.get("dumi_session")

    def test_the_session_cookie_is_httponly(self, client, admin) -> None:  # type: ignore[no-untyped-def]
        """So an XSS cannot read it and hand over the session."""
        response = client.post(
            "/admin/login", data={"email": "admin@example.ch", "password": BOOTSTRAP}
        )
        header = response.headers.get("set-cookie", "")
        assert "HttpOnly" in header
        assert "SameSite" in header

    def test_a_wrong_password_is_refused(self, client, admin) -> None:  # type: ignore[no-untyped-def]
        response = client.post(
            "/admin/login", data={"email": "admin@example.ch", "password": "wrong"}
        )
        assert response.status_code == 401
        assert not response.cookies.get("dumi_session")

    def test_an_unknown_account_gives_the_same_error(self, client, admin) -> None:  # type: ignore[no-untyped-def]
        """Distinguishing them tells an attacker which addresses have accounts."""
        unknown = client.post(
            "/admin/login", data={"email": "nobody@example.ch", "password": "wrong"}
        )
        wrong = client.post(
            "/admin/login", data={"email": "admin@example.ch", "password": "wrong"}
        )
        assert unknown.status_code == wrong.status_code == 401

    def test_repeated_failures_lock_the_account(self, client, admin, db) -> None:  # type: ignore[no-untyped-def]
        for _ in range(6):
            client.post("/admin/login", data={"email": "admin@example.ch", "password": "no"})
        locked = db.execute(sql("SELECT locked_until FROM users")).scalar_one()
        assert locked is not None

    def test_lockout_refuses_even_the_correct_password(self, client, admin, db) -> None:  # type: ignore[no-untyped-def]
        for _ in range(6):
            client.post("/admin/login", data={"email": "admin@example.ch", "password": "no"})
        response = client.post(
            "/admin/login", data={"email": "admin@example.ch", "password": BOOTSTRAP}
        )
        assert response.status_code == 401

    def test_login_attempts_are_audited(self, client, admin, db) -> None:  # type: ignore[no-untyped-def]
        client.post("/admin/login", data={"email": "admin@example.ch", "password": "wrong"})
        client.post("/admin/login", data={"email": "admin@example.ch", "password": BOOTSTRAP})
        actions = [
            row[0]
            for row in db.execute(sql("SELECT action FROM audit_events ORDER BY id"))
        ]
        assert "login.failed" in actions
        assert "login.succeeded" in actions

    def test_the_audit_entry_holds_no_password(self, client, admin, db) -> None:  # type: ignore[no-untyped-def]
        client.post("/admin/login", data={"email": "admin@example.ch", "password": BOOTSTRAP})
        leaks = db.execute(
            sql("SELECT count(*) FROM audit_events WHERE detail::text LIKE :p"),
            {"p": f"%{BOOTSTRAP}%"},
        ).scalar_one()
        assert leaks == 0


class TestForcedPasswordChange:
    def test_login_redirects_to_the_password_page(self, client, admin) -> None:  # type: ignore[no-untyped-def]
        response = client.post(
            "/admin/login", data={"email": "admin@example.ch", "password": BOOTSTRAP}
        )
        assert response.headers["location"] == "/admin/password"

    def test_the_dashboard_is_refused_until_the_password_changes(self, client, admin) -> None:  # type: ignore[no-untyped-def]
        """This is what makes the bootstrap credential good for one login."""
        client.post("/admin/login", data={"email": "admin@example.ch", "password": BOOTSTRAP})
        assert client.get("/admin").status_code == 403

    def test_the_password_page_is_reachable(self, client, admin) -> None:  # type: ignore[no-untyped-def]
        client.post("/admin/login", data={"email": "admin@example.ch", "password": BOOTSTRAP})
        assert client.get("/admin/password").status_code == 200

    def test_changing_the_password_unlocks_the_dashboard(self, client, admin, db) -> None:  # type: ignore[no-untyped-def]
        client.post("/admin/login", data={"email": "admin@example.ch", "password": BOOTSTRAP})
        response = client.post(
            "/admin/password",
            data={"current": BOOTSTRAP, "new_password": REPLACEMENT, "repeat": REPLACEMENT},
        )
        assert response.status_code == 303
        assert client.get("/admin").status_code == 200

    def test_the_current_password_is_required(self, client, admin) -> None:  # type: ignore[no-untyped-def]
        """So a session left open on an unattended machine cannot take over."""
        client.post("/admin/login", data={"email": "admin@example.ch", "password": BOOTSTRAP})
        response = client.post(
            "/admin/password",
            data={"current": "wrong", "new_password": REPLACEMENT, "repeat": REPLACEMENT},
        )
        assert response.status_code == 401

    def test_mismatched_repetition_is_refused(self, client, admin) -> None:  # type: ignore[no-untyped-def]
        client.post("/admin/login", data={"email": "admin@example.ch", "password": BOOTSTRAP})
        response = client.post(
            "/admin/password",
            data={"current": BOOTSTRAP, "new_password": REPLACEMENT, "repeat": "different-one-9"},
        )
        assert response.status_code == 400

    def test_a_weak_new_password_is_refused(self, client, admin) -> None:  # type: ignore[no-untyped-def]
        client.post("/admin/login", data={"email": "admin@example.ch", "password": BOOTSTRAP})
        response = client.post(
            "/admin/password",
            data={"current": BOOTSTRAP, "new_password": "password", "repeat": "password"},
        )
        assert response.status_code == 400

    def test_changing_the_password_revokes_other_sessions(self, client, admin, db) -> None:  # type: ignore[no-untyped-def]
        """A change that leaves old sessions alive locks nobody out."""
        first = TestClient(client.app, follow_redirects=False)
        first.post("/admin/login", data={"email": "admin@example.ch", "password": BOOTSTRAP})

        client.post("/admin/login", data={"email": "admin@example.ch", "password": BOOTSTRAP})
        client.post(
            "/admin/password",
            data={"current": BOOTSTRAP, "new_password": REPLACEMENT, "repeat": REPLACEMENT},
        )

        revoked = db.execute(
            sql("SELECT count(*) FROM user_sessions WHERE revoked_at IS NOT NULL")
        ).scalar_one()
        assert revoked >= 1


class TestAuthorisation:
    def test_the_dashboard_needs_a_session(self, client) -> None:  # type: ignore[no-untyped-def]
        assert client.get("/admin").status_code == 401

    def test_sources_need_the_source_permission(self, client, db) -> None:  # type: ignore[no-untyped-def]
        """A reviewer may resolve contradictions and not manage sources."""
        seed_roles(db)
        reviewer = User(
            email="reviewer@example.ch",
            password_hash=hash_password(REPLACEMENT),
            must_change_password=False,
        )
        db.add(reviewer)
        db.flush()
        role_id = db.execute(
            sql("SELECT id FROM roles WHERE name='reviewer'")
        ).scalar_one()
        db.add(UserRole(user_id=reviewer.id, role_id=role_id))
        db.commit()

        client.post("/admin/login", data={"email": "reviewer@example.ch", "password": REPLACEMENT})
        assert client.get("/admin").status_code == 200
        assert client.get("/admin/sources").status_code == 403

    def test_a_denied_request_is_audited(self, client, db) -> None:  # type: ignore[no-untyped-def]
        seed_roles(db)
        reviewer = User(
            email="reviewer2@example.ch",
            password_hash=hash_password(REPLACEMENT),
            must_change_password=False,
        )
        db.add(reviewer)
        db.flush()
        role_id = db.execute(sql("SELECT id FROM roles WHERE name='reviewer'")).scalar_one()
        db.add(UserRole(user_id=reviewer.id, role_id=role_id))
        db.commit()

        client.post("/admin/login", data={"email": "reviewer2@example.ch", "password": REPLACEMENT})
        client.get("/admin/sources")
        alerts = db.execute(
            sql("SELECT count(*) FROM audit_events WHERE action='security.alert'")
        ).scalar_one()
        assert alerts >= 1


class TestLogout:
    def test_logout_revokes_the_session_immediately(self, client, db) -> None:  # type: ignore[no-untyped-def]
        seed_roles(db)
        user = User(
            email="ops@example.ch",
            password_hash=hash_password(REPLACEMENT),
            must_change_password=False,
        )
        db.add(user)
        db.flush()
        role_id = db.execute(sql("SELECT id FROM roles WHERE name='super_admin'")).scalar_one()
        db.add(UserRole(user_id=user.id, role_id=role_id))
        db.commit()

        client.post("/admin/login", data={"email": "ops@example.ch", "password": REPLACEMENT})
        assert client.get("/admin").status_code == 200
        client.post("/admin/logout")
        # Server-side revocation, so a retained cookie is useless.
        assert client.get("/admin").status_code == 401


class TestBrowserRedirects:
    """A browser without a session lands on the sign-in page, not raw JSON."""

    def test_a_browser_is_redirected_to_the_login_page(self, client) -> None:  # type: ignore[no-untyped-def]
        response = client.get("/admin/sources", headers={"Accept": "text/html"})
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/login"

    def test_an_api_caller_keeps_its_status_code(self, client) -> None:  # type: ignore[no-untyped-def]
        """The chat script and any API client act on the 401; only a
        navigation gets redirected."""
        response = client.get("/admin/sources", headers={"Accept": "application/json"})
        assert response.status_code == 401

    def test_a_forced_password_change_redirects_to_the_password_page(self, client, admin) -> None:  # type: ignore[no-untyped-def]
        client.post("/admin/login", data={"email": "admin@example.ch", "password": BOOTSTRAP})
        response = client.get("/admin/sources", headers={"Accept": "text/html"})
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/password"
