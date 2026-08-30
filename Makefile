# Dumi development commands.
#
# Every target is safe to run more than once. Targets for work that is not
# implemented yet say so and exit non-zero, rather than appearing to succeed.

SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := docker compose
PY      := .venv/bin/python
PIP     := .venv/bin/pip

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# --------------------------------------------------------------------- setup

.PHONY: setup
setup: ## Create the virtualenv, install dependencies, copy .env
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	@if [ ! -f .env ]; then \
	  cp .env.example .env; \
	  echo ""; \
	  echo "Created .env from the template. Edit it before continuing:"; \
	  echo "  - SECRET_KEY: run 'make secret' and paste the result"; \
	  echo "  - POSTGRES_PASSWORD and the password inside DATABASE_URL"; \
	  echo "  - APERTUS_BASE_URL: where your local Apertus is listening"; \
	else \
	  echo ".env already exists and was left alone."; \
	fi

.PHONY: secret
secret: ## Generate a value suitable for SECRET_KEY
	@$(PY) -c "import secrets; print(secrets.token_urlsafe(48))"

.PHONY: check-config
check-config: ## Show the effective configuration and what production would refuse
	$(PY) -m app.cli check-config

# ----------------------------------------------------------------- services

.PHONY: up
up: ## Start the development stack
	$(COMPOSE) up -d
	@echo ""
	@echo "  Application  http://127.0.0.1:8000"
	@echo "  Adminer      http://127.0.0.1:8081  (sign in with the database user from .env)"
	@echo ""
	@echo "Both are bound to loopback and are not reachable from the network."

.PHONY: down
down: ## Stop the development stack, keeping data
	$(COMPOSE) down

.PHONY: logs
logs: ## Follow application and worker logs
	$(COMPOSE) logs -f app worker

.PHONY: dev
dev: ## Run the application on the host with reload
	.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# ----------------------------------------------------------------- database

.PHONY: migrate
migrate: ## Apply all migrations
	.venv/bin/alembic upgrade head

.PHONY: migration
migration: ## Create a migration. Usage: make migration m="add sources table"
	@test -n "$(m)" || { echo 'Usage: make migration m="describe the change"'; exit 1; }
	.venv/bin/alembic revision --autogenerate -m "$(m)"
	@echo ""
	@echo "Read the generated file before committing. Autogenerate misses"
	@echo "server defaults, data migrations and index changes on expressions."

.PHONY: downgrade
downgrade: ## Roll back one migration
	.venv/bin/alembic downgrade -1

.PHONY: bootstrap-admin
bootstrap-admin: ## Create the first administrator
	$(PY) -m app.cli bootstrap-admin

# --------------------------------------------------------------- Apertus

.PHONY: apertus-check
apertus-check: ## Report whether the configured Apertus endpoint answers
	@$(PY) -c "import asyncio, json; \
from app.llm.apertus import ApertusProvider; \
p = ApertusProvider(); \
h = asyncio.run(p.health()); \
print(f'state:   {h.state}'); \
print(f'detail:  {h.detail}'); \
print(f'models:  {\", \".join(h.models) or \"(none reported)\"}'); \
asyncio.run(p.aclose())"

# -------------------------------------------------------------------- tests

.PHONY: test
test: ## Run the test suite. Set TEST_DATABASE_URL for the database tests.
	$(PY) -m pytest -q

.PHONY: test-all
test-all: ## Run every test including the database-backed ones
	@test -n "$(TEST_DATABASE_URL)" || { \
	  echo "TEST_DATABASE_URL is not set. Example:"; \
	  echo "  export TEST_DATABASE_URL=postgresql+psycopg://dumi:PASS@127.0.0.1:5432/dumi_test"; \
	  exit 1; }
	$(PY) -m pytest -q

.PHONY: lint
lint: ## Lint and type-check
	.venv/bin/ruff check app tests
	.venv/bin/ruff format --check app tests
	.venv/bin/mypy app

.PHONY: format
format: ## Format the code
	.venv/bin/ruff format app tests
	.venv/bin/ruff check --fix app tests

.PHONY: security
security: ## Run the security checks
	@echo "== dependency vulnerabilities =="
	.venv/bin/pip-audit --strict || true
	@echo ""
	@echo "== lint security rules (bandit set) =="
	.venv/bin/ruff check --select S app
	@echo ""
	@echo "== audit log integrity =="
	$(PY) -m app.cli verify-audit
	@echo ""
	@echo "== configuration =="
	$(PY) -m app.cli check-config

.PHONY: evaluate
evaluate: ## Run the evaluation suite, including the adversarial cases
	$(PY) -m app.cli evaluate

.PHONY: verify-audit
verify-audit: ## Check the audit log hash chain
	$(PY) -m app.cli verify-audit

# ------------------------------------------------------------------ backups

.PHONY: backup
backup: ## Write an encrypted database backup to ./backups
	./scripts/backup.sh

.PHONY: restore
restore: ## Restore from a backup. Usage: make restore f=backups/dumi-....sql.gz.age
	@test -n "$(f)" || { echo 'Usage: make restore f=backups/<file>'; exit 1; }
	./scripts/restore.sh "$(f)"

.PHONY: rotate-credentials
rotate-credentials: ## Print the credential rotation procedure
	./scripts/rotate-credentials.sh

# ---------------------------------------------------------------- ingestion
# Implemented in Phase 3. These targets fail loudly rather than pretending.

.PHONY: ingest
ingest: ## Run a crawl of the configured sources (Phase 3)
	@echo "Not implemented yet. The crawler lands in Phase 3; see docs/architecture-assessment.md."
	@exit 1

.PHONY: sync
sync: ## Run a synchronisation pass (Phase 3)
	@echo "Not implemented yet. Synchronisation lands in Phase 3; see docs/architecture-assessment.md."
	@exit 1
