# Deployment

Four environments, described in order of how much they have actually been
exercised.

## Local development

```bash
make setup           # venv, dependencies, .env from the template
make secret          # generate SECRET_KEY, paste it into .env
make up              # postgres, redis, adminer, app, worker
make migrate
make bootstrap-admin
```

The application is at `http://127.0.0.1:8000`, Adminer at
`http://127.0.0.1:8081`. Both bind to loopback only and are unreachable from
the network. Sign in to Adminer with the database user from `.env`; it has no
credentials of its own.

Apertus runs on the desktop, not in compose. See `docs/apertus.md`.

**Not verified end to end.** Docker could not run in the environment where
this was built, so the compose file is validated by parsing rather than by
starting the stack. A first run on a real machine may surface image or volume
problems this could not.

## Local Apertus inference

See `docs/apertus.md`. `make apertus-check` confirms it.

## Test deployment

Same compose stack with `ENVIRONMENT=test`, a separate database, and a copy of
the crawl. Adminer should be removed even here: the fewer places it exists,
the fewer places it can be reached.

Run `make evaluate` after any content or model change.

## Swiss-hosted production

**Never deployed. This section is a specification, not a report.**

### Refused at startup

Production will not start with: a secret key under 32 characters or a known
weak one, a database URL with no password or a known one, `DEBUG=true`, plain
HTTP, insecure session cookies, no crawler contact, or uploads accepted with
no malware scanner configured.

`python -m app.cli check-config` shows what would be refused before you try.

### What must be provided

**Data residency.** A Swiss provider for the application, the database,
backups and Apertus. Verified, not assumed. Until verified, no document may
claim Swiss hosting.

**TLS.** Terminated in front of the application. Nothing here implements it.
HSTS is emitted in production.

**Secrets.** A secret manager rather than a `.env` file. The application reads
the environment; how the environment is populated is the deployment's problem.

**Database.** PostgreSQL 16 with pgvector, streaming replication, encrypted
backups, and a restore that has actually been tested. A backup nobody has
restored is a hope.

**Two database roles.** Migrations run as the owner; the application connects
as a separate role. This is what makes the audit log append-only at the
database level, because an owner keeps its privileges through any REVOKE. Set
`DATABASE_APP_ROLE` so migration 0001 applies the grants.

**Rate limiting in Redis.** The current limiter is per process, so N processes
allow N times the configured rate.

**Malware scanning.** `MALWARE_SCANNER_COMMAND` must be set, and something must
actually run it. Production refuses to start without the setting; the
invocation is not implemented.

**Monitoring.** `/healthz` for liveness, `/readyz` for readiness. Alert on
readiness failure, audit chain failure, ingestion failure, and index staleness.

### Sizing

Unknown. No load test has been run. The application is IO-bound and modest;
Apertus dominates both cost and capacity, and its requirements depend on the
model variant chosen.

## Rollback

**Application:** deploy the previous image. Migrations are reversible, but a
downgrade that drops a column loses data, so check the migration before
running one.

**Index:** not implemented. There is no index version to promote or roll back.
Rolling back content today means restoring the database.
