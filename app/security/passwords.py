"""Password hashing and the password policy.

Argon2id, as required by section 5 of the brief. Parameters follow the OWASP
Password Storage Cheat Sheet's Argon2id recommendation and are stated
explicitly rather than left to library defaults, so that a library upgrade
cannot silently weaken them.

The encoded hash produced by argon2-cffi carries its own parameters and salt,
so raising the cost later does not invalidate existing hashes:
:func:`verify_password` reports when a stored hash was made with weaker
parameters and the caller rehashes on successful login.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

from app.config import is_known_unsafe_credential

# OWASP recommends, for Argon2id, at least 19 MiB of memory, 2 iterations and
# 1 degree of parallelism. Memory is the expensive dimension for an attacker,
# so it is raised rather than the iteration count.
ARGON2_MEMORY_COST_KIB = 65536  # 64 MiB
ARGON2_TIME_COST = 3
ARGON2_PARALLELISM = 4
ARGON2_HASH_LENGTH = 32
ARGON2_SALT_LENGTH = 16

ALGORITHM_NAME = "argon2id"

# Minimum length rather than a composition rule. NIST SP 800-63B advises
# against forced character-class mixing, which pushes people towards
# predictable substitutions, and towards length plus a blocklist instead.
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024  # bounded so a huge input cannot become a CPU attack

_hasher = PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_COST_KIB,
    parallelism=ARGON2_PARALLELISM,
    hash_len=ARGON2_HASH_LENGTH,
    salt_len=ARGON2_SALT_LENGTH,
    type=Type.ID,
)


@dataclass(frozen=True)
class PasswordCheck:
    """Result of validating a candidate password against the policy."""

    ok: bool
    # Message keys rather than sentences, so the interface can localise them
    # into the four supported languages. See app/i18n.
    problems: tuple[str, ...] = ()


def validate_password(password: str, *, email: str | None = None) -> PasswordCheck:
    """Check a candidate password against the policy.

    Returns message keys rather than prose so the caller can render them in
    the user's language. All failures are reported at once, so somebody
    choosing a new password is not sent round the loop repeatedly.
    """
    problems: list[str] = []

    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append("password.too_short")
    if len(password) > MAX_PASSWORD_LENGTH:
        problems.append("password.too_long")

    # Rejects the development bootstrap values and common weak choices. This
    # is the same digest list the production startup check uses.
    if is_known_unsafe_credential(password):
        problems.append("password.known_weak")

    # A password that is the local part of the account's own address is
    # guessable from the account name alone.
    if email:
        local_part = email.split("@", 1)[0].strip().lower()
        if local_part and local_part in password.lower():
            problems.append("password.contains_email")

    # A single repeated character, or a straightforward ascending run, passes a
    # length check while carrying almost no entropy.
    if password and len(set(password)) <= 3:
        problems.append("password.too_repetitive")
    if re.search(r"(?:0123|1234|2345|3456|4567|5678|6789|abcd|qwer)", password.lower()):
        problems.append("password.sequential")

    return PasswordCheck(ok=not problems, problems=tuple(problems))


def hash_password(password: str) -> str:
    """Return an Argon2id encoded hash of ``password``.

    The caller is responsible for having validated the password first. This
    function deliberately does not validate, so that rehashing an existing
    acceptable password never fails because the policy has since tightened.
    """
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError("password exceeds the maximum supported length")
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> tuple[bool, bool]:
    """Verify ``password`` against ``stored_hash``.

    Returns ``(is_valid, needs_rehash)``. ``needs_rehash`` is true when the
    stored hash was produced with weaker parameters than the current ones, so
    the caller can transparently upgrade it during a successful login.

    Never raises for an ordinary mismatch. A malformed stored hash is treated
    as a failed verification rather than an exception, because a corrupted row
    must not turn a login attempt into a 500 that leaks a stack trace.
    """
    try:
        _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False, False

    try:
        return True, _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:  # pragma: no cover - defensive
        return True, True


# A hash of a random value, computed once on first use. Nobody can present the
# matching password, because it is discarded. Generating it beats hardcoding an
# encoded hash, which would silently become invalid if the parameters change
# and would then return instantly, reopening the timing oracle it exists to
# close.
_dummy_hash: str | None = None


def dummy_verify() -> None:
    """Consume roughly the time a real verification would.

    Called on the login path when the account does not exist, so that response
    timing does not disclose which email addresses have accounts. Without it a
    missing user returns in microseconds while a real one pays the full Argon2
    cost, which is a usable account enumeration oracle.
    """
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash(secrets.token_urlsafe(32))
    try:
        _hasher.verify(_dummy_hash, "not-the-password")
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        # The mismatch is the point. The work has already been done.
        pass
