"""Authentication and authorisation.

Login throttling counts failures in the database rather than in a cache, so
flushing a cache cannot reset an attacker's budget. Lockout is per account and
time-bounded.

Authorisation is enforced server-side on every privileged operation, through
dependencies that raise before a handler body runs. No authorisation decision
is made in a template or in the browser.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AuditAction, AuditOutcome, RoleName, User, UserSession
from app.db.session import db_session
from app.observability import get_logger
from app.security.audit import record
from app.security.hashing import hash_client_address
from app.security.passwords import dummy_verify, hash_password, verify_password
from app.security.sessions import load_session

logger = get_logger(__name__)


class Permission(StrEnum):
    """What an operation requires.

    Named by what they let someone do rather than by role, so a handler states
    its requirement and the role mapping can change without touching handlers.
    """

    MANAGE_USERS = "manage_users"
    MANAGE_SOURCES = "manage_sources"
    MANAGE_DOCUMENTS = "manage_documents"
    APPROVE_CONTENT = "approve_content"
    RESOLVE_CONTRADICTIONS = "resolve_contradictions"
    VIEW_FEEDBACK = "view_feedback"
    VIEW_AUDIT = "view_audit"
    MANAGE_CONFIGURATION = "manage_configuration"


# Which roles hold which permissions. The auditor deliberately holds only
# read permissions: an account that can change nothing is the point of it.
ROLE_PERMISSIONS: dict[RoleName, frozenset[Permission]] = {
    RoleName.SUPER_ADMIN: frozenset(Permission),
    RoleName.CONTENT_ADMIN: frozenset(
        {
            Permission.MANAGE_SOURCES,
            Permission.MANAGE_DOCUMENTS,
            Permission.APPROVE_CONTENT,
            Permission.VIEW_FEEDBACK,
        }
    ),
    RoleName.REVIEWER: frozenset(
        {Permission.RESOLVE_CONTRADICTIONS, Permission.VIEW_FEEDBACK}
    ),
    RoleName.SUPPORT_OPERATOR: frozenset({Permission.VIEW_FEEDBACK}),
    RoleName.AUDITOR: frozenset({Permission.VIEW_AUDIT, Permission.VIEW_FEEDBACK}),
}


def permissions_for(role_names: set[str]) -> frozenset[Permission]:
    """Return the union of permissions held by a set of role names."""
    granted: set[Permission] = set()
    for name in role_names:
        try:
            role = RoleName(name)
        except ValueError:
            # An unknown role grants nothing. Failing open here would mean a
            # typo in a role name silently became super administrator.
            continue
        granted |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(granted)


@dataclass
class LoginResult:
    """The outcome of a login attempt."""

    user: User | None = None
    # A message key, so the interface can render it in the user's language.
    error: str = ""
    locked_until: dt.datetime | None = None

    @property
    def ok(self) -> bool:
        return self.user is not None


def authenticate(
    db: Session,
    email: str,
    password: str,
    *,
    client_host: str | None = None,
    request_id: str | None = None,
) -> LoginResult:
    """Verify credentials, applying throttling and lockout.

    The same generic error is returned whether the account does not exist, the
    password is wrong, or the account is inactive. Distinguishing them tells an
    attacker which addresses have accounts.
    """
    settings = get_settings()
    now = dt.datetime.now(dt.UTC)
    address_hash = hash_client_address(client_host)
    email = email.strip().lower()

    user = db.execute(
        select(User).where(func.lower(User.email) == email)
    ).scalar_one_or_none()

    if user is None:
        # Spend the same time a real verification would, so response timing
        # does not reveal which addresses exist.
        dummy_verify()
        record(
            db,
            action=AuditAction.LOGIN_FAILED,
            outcome=AuditOutcome.FAILURE,
            actor_label="anonymous",
            request_id=request_id,
            client_address_hash=address_hash,
            detail={"reason": "unknown_account"},
        )
        return LoginResult(error="auth.invalid_credentials")

    if user.locked_until is not None and user.locked_until > now:
        record(
            db,
            action=AuditAction.LOGIN_LOCKED_OUT,
            outcome=AuditOutcome.DENIED,
            actor_user_id=user.id,
            actor_label=f"user:{user.id}",
            request_id=request_id,
            client_address_hash=address_hash,
        )
        return LoginResult(error="auth.locked", locked_until=user.locked_until)

    valid, needs_rehash = verify_password(user.password_hash, password)

    if not valid or not user.is_active:
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_max_failures:
            user.locked_until = now + dt.timedelta(seconds=settings.login_lockout_seconds)
            user.failed_login_count = 0
        record(
            db,
            action=AuditAction.LOGIN_FAILED,
            outcome=AuditOutcome.FAILURE,
            actor_user_id=user.id,
            actor_label=f"user:{user.id}",
            request_id=request_id,
            client_address_hash=address_hash,
            detail={"reason": "bad_password" if not valid else "inactive_account"},
        )
        return LoginResult(error="auth.invalid_credentials")

    if needs_rehash:
        # Transparently upgrade a hash made with weaker parameters.
        user.password_hash = hash_password(password)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now

    record(
        db,
        action=AuditAction.LOGIN_SUCCEEDED,
        actor_user_id=user.id,
        actor_label=f"user:{user.id}",
        request_id=request_id,
        client_address_hash=address_hash,
    )
    return LoginResult(user=user)


@dataclass
class CurrentUser:
    """The authenticated user for one request."""

    user: User
    session: UserSession
    permissions: frozenset[Permission]

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions


def current_user(
    request: Request, db: Session = Depends(db_session)
) -> CurrentUser | None:
    """Resolve the signed-in user, or None."""
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    session_row = load_session(db, token)
    if session_row is None:
        return None

    user = db.get(User, session_row.user_id)
    if user is None or not user.is_active:
        return None

    return CurrentUser(
        user=user,
        session=session_row,
        permissions=permissions_for(user.role_names()),
    )


def require_login(
    who: CurrentUser | None = Depends(current_user),
) -> CurrentUser:
    """Require an authenticated user.

    An account with must_change_password set is refused everywhere except the
    password-change route, which passes ``allow_password_change``. That is what
    makes the bootstrap credential good for exactly one login.
    """
    if who is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login_required")
    if who.user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="password_change_required"
        )
    return who


def require_login_allowing_password_change(
    who: CurrentUser | None = Depends(current_user),
) -> CurrentUser:
    """Require a session, but permit an account that must change its password."""
    if who is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login_required")
    return who


def require(permission: Permission):  # type: ignore[no-untyped-def]
    """Build a dependency requiring one permission.

    The check runs before the handler body, so a handler cannot forget it, and
    a denial is audited.
    """

    def dependency(
        who: CurrentUser = Depends(require_login),
        db: Session = Depends(db_session),
    ) -> CurrentUser:
        if not who.can(permission):
            record(
                db,
                action=AuditAction.SECURITY_ALERT,
                outcome=AuditOutcome.DENIED,
                actor_user_id=who.user.id,
                actor_label=f"user:{who.user.id}",
                detail={"denied_permission": permission.value},
            )
            db.commit()
            logger.warning("authz.denied", permission=permission.value)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        return who

    return dependency
