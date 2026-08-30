# chweya.ch — Dumi

**Dumi** is an unofficial AI assistant for public Canton of Zug information. It
answers questions about canton services in German, English, French and Italian,
grounded in retrieved official content, and cites the page each answer came
from.

**It is not operated or endorsed by the Canton of Zug.** It has never been
deployed. See [known limitations](docs/known-limitations.md), which is the
first document to read.

## What it does

Crawls approved public zug.ch content, extracts and cleans it, chunks it with
citation anchors, indexes it for hybrid semantic and keyword retrieval, and
answers questions through Apertus using only what it retrieved. When the
evidence does not support an answer it says so rather than guessing.

## Getting started

```bash
make setup            # venv, dependencies, .env from the template
make secret           # generate SECRET_KEY, paste it into .env
make up               # postgres with pgvector, redis, adminer, app, worker
make migrate
make bootstrap-admin  # the password must be changed at first login
make apertus-check    # confirm your local Apertus endpoint
```

Application on `http://127.0.0.1:8000`, Adminer on `http://127.0.0.1:8081`.
Both bind to loopback only.

`make help` lists everything.

### On Windows

`make` assumes a Unix shell. The same setup in `cmd.exe`, with Docker Desktop
running for the database:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,ingest,embed]"
copy .env.example .env
notepad .env
```

In `.env`, set `SECRET_KEY` (generate one with
`python -c "import secrets; print(secrets.token_urlsafe(48))"`), put the same
database password in `POSTGRES_PASSWORD` and inside `DATABASE_URL`, and write
the database host as `127.0.0.1` rather than `localhost`: Windows sometimes
resolves `localhost` to IPv6 first and the connection hangs instead of
falling back. For Ollama, `APERTUS_BASE_URL=http://localhost:11434/v1` and
`APERTUS_MODEL` set to exactly what `ollama list` shows, tag included.

```bat
docker compose up -d db
alembic upgrade head
python -m app.cli bootstrap-admin
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The bootstrap password prompt shows nothing while you type; that is normal.
Set `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` in `.env` to skip
the prompt, and blank the password line after the first login.

## Repository

```
app/
  config.py       validated settings; refuses unsafe production configuration
  db/             models and session handling
  security/       Argon2id, sessions, authorisation, tamper-evident audit
  llm/            the LLMProvider protocol and the Apertus provider
  ingest/         allowlist, SSRF guards, crawler, extraction, chunking
  retrieval/      embeddings, hybrid search, confidence policy, answering
  evaluation/     adversarial and grounded evaluation cases
  api/            chat surface and administration
  templates/      server-rendered, works without JavaScript
shared/brand/     the Dumi design system, served unchanged
migrations/       Alembic
docs/             architecture, security, privacy, operations, policy
```

## Principles the code enforces

- **No answer without evidence.** Insufficient evidence does not call the
  model at all.
- **Every factual answer cites its source.** An answer that produces no
  citations is replaced.
- **Retrieved content is untrusted**, including pages the canton published. It
  never occupies the system role, the model has no tools, and the evidence
  delimiter is random per request.
- **The mark is the only status indicator.** No spinner, no typing dots.
- **Nothing fakes presence.** It is a model and the interface says so.

## Documentation

| Read first | |
|---|---|
| [Known limitations](docs/known-limitations.md) | What does not work and what must not be claimed |
| [Production readiness](docs/production-readiness.md) | About twenty blocking items, none ticked |
| [Architecture](docs/architecture-assessment.md) | Decisions and the alternatives rejected |

| Security and privacy | |
|---|---|
| [Threat model](docs/threat-model.md) · [Security controls](docs/security-controls.md) | |
| [Privacy](docs/privacy.md) · [DPIA draft](docs/dpia-draft.md) · [Privacy notice](docs/privacy-notice.md) | Not reviewed by a qualified professional |

| Operations | |
|---|---|
| [Deployment](docs/deployment.md) · [Apertus](docs/apertus.md) | |
| [Operations](docs/runbook-operations.md) · [Incidents](docs/runbook-incident.md) · [Backups](docs/backup-recovery.md) | |

| Policy and process | |
|---|---|
| [Crawler](docs/crawler-policy.md) · [Sources](docs/source-policy.md) | |
| [Content lifecycle](docs/content-lifecycle.md) · [Contradiction review](docs/contradiction-review.md) | |

| People | |
|---|---|
| [Administrator guide](docs/administrator-guide.md) · [Staff training](docs/staff-training.md) · [Support](docs/support-runbook.md) | |

| Commercial | |
|---|---|
| [Proposed SLA](docs/sla-proposal.md) · [2-year](docs/maintenance-2-year.md) · [3-year](docs/maintenance-3-year.md) | Drafts, not agreements |

| Accessibility | |
|---|---|
| [Accessibility report](docs/accessibility.md) | Not a conformance claim |

Phase reports: [1](docs/architecture-assessment.md) ·
[2](docs/phase-2-report.md) · [3](docs/phase-3-report.md) ·
[4](docs/phase-4-report.md) · [5](docs/phase-5-report.md)

## Tests

```bash
make test       # runs anywhere
export TEST_DATABASE_URL=postgresql+psycopg://dumi:PASS@127.0.0.1:5432/dumi_test
make test-all   # includes the database-backed tests
make evaluate   # adversarial evaluation cases
make security   # dependency audit, lint security rules, audit chain, config
```

## Reference

The Canton of Basel-Stadt runs a comparable assistant, **Alva**, at
[bs.ch](https://www.bs.ch). Worth reading as prior art.
