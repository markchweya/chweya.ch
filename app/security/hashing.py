"""Non-password hashing: session tokens, client addresses, content digests.

Three different jobs, deliberately kept apart because they have different
requirements:

* Session tokens are high-entropy secrets. A plain SHA-256 is correct and
  fast; the token cannot be brute-forced, so a slow hash buys nothing and
  would add latency to every authenticated request.
* Client addresses and user agents are low-entropy. There are only about four
  billion IPv4 addresses, so an unsalted hash is reversible by enumeration in
  minutes. These are hashed with a secret pepper, which means a database
  disclosure alone does not reveal who visited.
* Content digests identify crawled bytes. They are not secrets at all.

Passwords use Argon2id and live in app.security.passwords. Never hash a
password with anything here.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from app.config import get_settings

# Domain separation. Hashing an address and a user agent through the same
# pepper without a label would let equal outputs imply equal inputs across
# fields that mean different things.
_ADDRESS_LABEL = b"dumi.client-address.v1"
_USER_AGENT_LABEL = b"dumi.user-agent.v1"


def new_session_token() -> str:
    """Return a fresh, high-entropy session token.

    32 bytes from the OS CSPRNG. This value goes to the client in a cookie and
    is never stored; only :func:`hash_session_token` of it is.
    """
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Return the SHA-256 hex digest of a session token.

    Unsalted on purpose. The token has 256 bits of entropy, so there is no
    dictionary to attack, and the lookup has to be a single indexed equality
    match on every authenticated request.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _peppered(label: bytes, value: str) -> str:
    """HMAC ``value`` under the application secret with a domain label.

    The pepper is SECRET_KEY, which lives in the environment and not in the
    database. An attacker who exfiltrates the database therefore cannot
    reverse these by enumeration; they need the application secret as well.
    """
    key = get_settings().secret_key.get_secret_value().encode("utf-8")
    return hmac.new(key, label + b"\x00" + value.encode("utf-8"), hashlib.sha256).hexdigest()


def hash_client_address(address: str | None) -> str | None:
    """Return a peppered hash of a client IP address, or None.

    Returns None when the address is absent, or when HASH_CLIENT_ADDRESSES is
    disabled and the operator has accepted storing nothing. This function
    never returns the address itself: there is no configuration under which
    Dumi stores a raw client address.
    """
    if not address:
        return None
    if not get_settings().hash_client_addresses:
        return None
    return _peppered(_ADDRESS_LABEL, address)


def hash_user_agent(user_agent: str | None) -> str | None:
    """Return a peppered hash of a User-Agent string, or None."""
    if not user_agent:
        return None
    return _peppered(_USER_AGENT_LABEL, user_agent)


def content_digest(data: bytes) -> str:
    """Return the SHA-256 hex digest of retrieved content.

    Used for change detection during crawling. Not a secret and not peppered:
    the same bytes must produce the same digest across deployments, otherwise
    conditional fetching cannot work.
    """
    return hashlib.sha256(data).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    """Compare two hex digests without leaking their contents through timing."""
    return hmac.compare_digest(left, right)
