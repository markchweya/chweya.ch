# Phase 2 report: secure foundation

Status at commit `5728e7c`. Written to the rule in section 26: report what
works, report what does not, and do not claim completion for anything
unverified.

## Verified working

Each item was exercised against a real PostgreSQL 16 instance or a running
application, not inferred from the code.

**Schema and migrations.** Six tables across two migrations. `alembic upgrade
head` creates them and seeds the five roles, `downgrade base` removes all of
them, and a second upgrade restores the seed. The schema is not created by an
undocumented manual step.

**Configuration.** Loaded from the environment and validated at startup.
`check-config` against the development `.env` correctly refuses six things for
production, including both supplied development passwords, recognised by
digest rather than by carrying the values in source.

**Password hashing.** Argon2id at 64 MiB, 3 iterations, parallelism 4. The
policy rejects the bootstrap values, short passwords, sequences, and passwords
containing the account's own address. Account enumeration through response
timing is closed, measured at matching minimum times of 77 and 78 ms.

**Audit log.** Tamper-evident by hash chain, verified against the database.
Editing a row, deleting one, changing a detail payload, reassigning the actor,
and inserting a forged row are each detected and reported at the correct
identifier. Restoring an edited value verifies clean again, which proves
detection is content-based rather than a one-way flag.

**Administrator bootstrap.** Creates the account, forces a password change,
grants `super_admin`, and audits the event with the email domain rather than
the address. A second run refuses. Deleting the administrator and running
again still refuses, which is the requirement in section 5. `--force`
overrides and records that it did.

**Application.** `/healthz` answers without touching a dependency. `/readyz`
reports the database and migration state, and reports Apertus separately
without marking the service unready when the model is down.

**Apertus provider.** 16 tests against a mocked transport cover every failure
mode. The system fails closed: nothing degrades into an empty answer.

**Development stack.** Compose validates, and all four published ports bind to
`127.0.0.1`, confirmed by parsing the resolved configuration.

**Tests.** 68 passing. 42 run anywhere; 26 need `TEST_DATABASE_URL`.

## Two defects found and fixed

Both are recorded because they show where reading the code was not enough.

**The production credential check could not run.** It read
`self.database_url.password`, but `PostgresDsn` exposes credentials only
through `hosts()`. A production deployment carrying a development password
would have raised `AttributeError` instead of refusing. Found by running
`check-config`, not by reading it, because the production branch never
executes in development. Fixed in `4b3aec3`.

**The refusal printed the password it refused.** Raising `ValueError` inside a
pydantic validator produces a `ValidationError` whose message includes the
entire input, so the database and administrator passwords would have been
written to stderr and the container log. The messages themselves were written
carefully; the leak was underneath them, in the framework's error wrapping.
Found by the test asserting a refusal never contains the credential it
refused. Fixed in `ba35914`.

## Not implemented

Phase 2 scope that is deliberately absent, so nothing above is read as more
than it is.

- **Login, sessions and RBAC enforcement.** The schema, hashing, throttling
  columns and session model exist. The routes that use them do not. There is
  no way to log in yet.
- **Password change flow.** `must_change_password` is set and stored, and
  nothing reads it yet.
- **Rate limiting.** Configured and unenforced.
- **CSRF protection.** Needed once there are forms.
- **`pgvector`.** The compose image provides it. No migration enables the
  extension, because no table needs it before Phase 4.
- **Redis and the worker.** Both are in compose and neither has work to do.

## Environment limitations

**No Apertus endpoint is reachable from the build environment.** Apertus is on
the developer's desktop; this work was done in a remote container. The
provider is verified against a recorded contract, and the live endpoint has
not been contacted. Confirm locally with `make apertus-check`, which should
report `healthy` and list the model.

**`pgvector` is not installed on the build machine.** It ships in the compose
image and will be exercised in Phase 4.

**Docker could not run here.** The compose file is validated by parsing, and
the stack has not been started end to end. First run on a real machine may
surface image or volume problems this could not.

## Security posture

Present: Argon2id, tamper-evident audit, production credential refusal,
loopback-only service binding, a strict Content-Security-Policy with no
`unsafe-inline` for scripts, security headers, safe error responses, request
correlation, log filtering for question text and secrets, non-root containers,
and a statement timeout on every connection.

Absent, and needed before any deployment: authentication and authorisation
enforcement, CSRF, rate limiting, TLS termination, a secret manager, and
malware scanning for uploads. Production configuration already refuses to
start without a scanner configured.

## Requires human review

Unchanged from the Phase 1 assessment, section 9. Nothing in Phase 2 has been
reviewed by a qualified security, privacy or legal professional, and no
document in this repository claims otherwise.
