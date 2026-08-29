"""Create the first administrator account.

Run once, when a fresh database has no administrator:

    python -m app.cli bootstrap-admin

The password is read from BOOTSTRAP_ADMIN_PASSWORD, or prompted for when that
is unset. It is hashed with Argon2id immediately and the plaintext is never
written to the database, the log, the console or the process output.

The account is created with ``must_change_password`` set, so the first login
cannot proceed to any other page until the password has been replaced. That
is what makes it acceptable for the development bootstrap value to be a known
string: it can be used exactly once, to set a real one.

Deleting the administrator does not cause a later run to recreate it. A marker
is written to system_settings, and a run that finds the marker refuses unless
``--force`` is given. Section 5 of the brief requires this: silently
recreating a deleted account would undo a deliberate removal.
"""

from __future__ import annotations

import getpass
import sys
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Environment, get_settings, is_known_unsafe_credential
from app.db.models import (
    AuditAction,
    AuditOutcome,
    Role,
    RoleName,
    SettingKey,
    User,
    UserRole,
    get_setting,
    set_setting,
)
from app.db.models.system import utcnow_iso
from app.db.session import session_scope
from app.security.audit import record
from app.security.passwords import ALGORITHM_NAME, hash_password, validate_password


@dataclass(frozen=True)
class BootstrapResult:
    """What the command did, for the caller to report.

    Deliberately carries no password field. There is no code path that returns
    the plaintext to anything.
    """

    created: bool
    email: str
    reason: str = ""


class BootstrapRefused(Exception):
    """Raised when bootstrapping must not proceed."""


def _read_password(settings_password: str | None, *, interactive: bool) -> str:
    """Return the bootstrap password from configuration or an interactive prompt."""
    if settings_password:
        return settings_password
    if not interactive:
        raise BootstrapRefused(
            "BOOTSTRAP_ADMIN_PASSWORD is not set and there is no terminal to prompt on. "
            "Set it in the environment for an unattended run."
        )
    # getpass does not echo, so the password does not appear on screen or in
    # the shell history.
    first = getpass.getpass("New administrator password: ")
    second = getpass.getpass("Repeat password: ")
    if first != second:
        raise BootstrapRefused("The two passwords did not match.")
    return first


def bootstrap_admin(
    session: Session,
    *,
    email: str,
    password: str,
    force: bool = False,
) -> BootstrapResult:
    """Create the first administrator inside an existing transaction.

    Separated from the command-line wrapper so the test suite can exercise
    every refusal path without a subprocess.
    """
    settings = get_settings()
    email = email.strip().lower()
    if not email or "@" not in email:
        raise BootstrapRefused("A valid administrator email address is required.")

    # Refusal 1: the marker says an administrator has already been bootstrapped.
    marker = get_setting(session, SettingKey.ADMIN_BOOTSTRAPPED_AT)
    if marker is not None and not force:
        raise BootstrapRefused(
            f"An administrator was already bootstrapped at {marker}. "
            "Refusing to recreate it. If the account was deliberately removed and you "
            "genuinely want a new one, re-run with --force, which is audited."
        )

    # Refusal 2: an active administrator already exists. Cheaper to check than
    # to explain afterwards why there are two.
    existing_admins = session.execute(
        select(func.count())
        .select_from(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.name == RoleName.SUPER_ADMIN.value, User.is_active.is_(True))
    ).scalar_one()
    if existing_admins and not force:
        raise BootstrapRefused(
            f"{existing_admins} active super administrator account(s) already exist. "
            "Use the administration interface to add another user."
        )

    # Refusal 3: this address is already taken.
    taken = session.execute(
        select(User).where(func.lower(User.email) == email)
    ).scalar_one_or_none()
    if taken is not None:
        raise BootstrapRefused(f"A user already exists with that email address ({email}).")

    # Refusal 4: production must never accept a known bootstrap or weak value.
    # In development the known value is allowed precisely once, because
    # must_change_password forces it to be replaced at first login.
    if settings.environment is Environment.PRODUCTION and is_known_unsafe_credential(password):
        raise BootstrapRefused(
            "Refusing to create a production administrator with a known development "
            "or weak password."
        )

    if settings.environment is Environment.PRODUCTION:
        check = validate_password(password, email=email)
        if not check.ok:
            raise BootstrapRefused(
                "The password does not meet the policy: " + ", ".join(check.problems)
            )

    role = session.execute(
        select(Role).where(Role.name == RoleName.SUPER_ADMIN.value)
    ).scalar_one()

    user = User(
        email=email,
        display_name="Administrator",
        password_hash=hash_password(password),
        # Recorded so a future algorithm change can rehash without having
        # to guess what produced an existing hash. Taken from the hashing
        # module so the two cannot drift apart.
        password_algorithm=ALGORITHM_NAME,
        # The whole point of the bootstrap: this credential is good for one
        # login, which must be a password change.
        must_change_password=True,
        is_active=True,
    )
    session.add(user)
    session.flush()
    session.add(UserRole(user_id=user.id, role_id=role.id, granted_by_id=None))

    set_setting(
        session,
        SettingKey.ADMIN_BOOTSTRAPPED_AT,
        utcnow_iso(),
        note=(
            "Written by bootstrap-admin. Its presence prevents a later run from "
            "silently recreating a deliberately deleted administrator."
        ),
    )

    record(
        session,
        action=AuditAction.ADMIN_BOOTSTRAPPED,
        outcome=AuditOutcome.SUCCESS,
        actor_label="cli:bootstrap-admin",
        object_type="user",
        object_id=str(user.id),
        # The address is not recorded. The domain is enough to tell an auditor
        # which environment this happened in, without storing the identity.
        detail={"email_domain": email.split("@", 1)[1], "forced": force},
    )

    return BootstrapResult(created=True, email=email)


def main(argv: list[str]) -> int:
    """Command-line entry point. Returns a process exit code."""
    force = "--force" in argv
    settings = get_settings()

    email = settings.bootstrap_admin_email.strip()
    if not email:
        raise SystemExit(
            "BOOTSTRAP_ADMIN_EMAIL is not set. Add it to .env or export it before running."
        )

    configured = (
        settings.bootstrap_admin_password.get_secret_value()
        if settings.bootstrap_admin_password is not None
        else None
    )

    try:
        password = _read_password(configured, interactive=sys.stdin.isatty())
        with session_scope() as session:
            result = bootstrap_admin(session, email=email, password=password, force=force)
    except BootstrapRefused as exc:
        # The message names what is wrong. It never contains the password.
        print(f"Refused: {exc}", file=sys.stderr)
        return 2

    print(f"Administrator created for {result.email}.")
    print("The password must be changed at first login before anything else is reachable.")
    print("Now unset BOOTSTRAP_ADMIN_PASSWORD so the value stops living in the environment.")
    return 0
