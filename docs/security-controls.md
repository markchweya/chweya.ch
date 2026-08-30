# Security controls

What is implemented, where it lives, and what tests it. Anything absent is
listed at the end rather than left to be inferred.

## Authentication

| Control | Where | Tested by |
|---|---|---|
| Argon2id, 64 MiB, t=3, p=4 | `app/security/passwords.py` | `tests/test_admin_auth.py` |
| Password policy: length plus blocklist | `app/security/passwords.py` | `tests/test_config_production.py` |
| Account enumeration closed by timing | `dummy_verify` | measured, 77 vs 78 ms |
| Lockout after repeated failures | `app/security/auth.py` | `tests/test_admin_auth.py` |
| Forced password change on first login | `app/api/admin.py` | `tests/test_admin_auth.py` |
| Server-side sessions, immediate revocation | `app/security/sessions.py` | `tests/test_admin_auth.py` |
| HttpOnly, Secure, SameSite cookies | `app/api/admin.py` | `tests/test_admin_auth.py` |
| Other sessions revoked on password change | `app/api/admin.py` | `tests/test_admin_auth.py` |

## Authorisation

Role-based, enforced by a dependency that runs before the handler body. An
unknown role name grants nothing. Denials are audited as security events.

The auditor role holds only read permissions, which is the point of it.

## Input handling

Request validation through pydantic models; parameterised SQL everywhere via
SQLAlchemy; Jinja autoescaping; a Content-Security-Policy with no
`unsafe-inline` for scripts; `nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy`, `Permissions-Policy`, and HSTS in production.

Question length is bounded at 1000 characters; the prompt context budget is
enforced locally rather than left to the model server.

## Outbound requests

Every fetch goes through `GuardedFetcher`. Nothing else in the codebase opens
a connection to a URL that came from a page, a sitemap or a form.

Hostname allowlist before DNS; resolved addresses validated; the connection
pinned to a validated address; redirects followed manually and revalidated at
every hop; GET and HEAD only; response size capped twice, once against
`Content-Length` and again while streaming.

## Secrets

Loaded from the environment. `.env` is git-ignored. Production refuses to
start with a short or known-weak secret key, a database URL with no password
or a known one, plain HTTP, insecure cookies, debug mode, no crawler contact,
or uploads with no malware scanner.

Failure messages name variables and never values. The check raises a
non-`ValueError` exception, because pydantic embeds the whole input in a
`ValidationError` and that would print the passwords it refused.

Known bad credentials are recognised by SHA-256 digest, so the repository
contains no usable credential.

## Audit

Hash-chained and append-oriented. Editing, deleting, reordering or forging a
row breaks verification, and `verify-audit` reports where.

Sensitive keys are redacted recursively before writing. Detail payloads are
bounded, and an oversized one is replaced with a note rather than dropping the
record that the action happened.

## Logging

Question text, answers and passage content are dropped by key name before an
event is rendered, so an operational log cannot become a record of what
residents asked. Only hostnames are logged for crawl activity, never full URLs.

## Not implemented

- Multi-factor authentication.
- CSRF synchroniser tokens on administrative forms. `SameSite` covers the
  common case; a token is stronger.
- Distributed rate limiting. The current limiter is per process.
- Malware scanning execution. The configuration point exists and production
  refuses to start without it.
- Off-host audit shipping.
- TLS termination, which belongs in front of the application.
- Dependency vulnerability scanning in CI. `make security` runs `pip-audit`
  locally; nothing enforces it.
