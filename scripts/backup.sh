#!/usr/bin/env bash
# Create a compressed, encrypted database backup.
#
#   ./scripts/backup.sh
#
# Encryption uses age when it is available. An unencrypted database dump of
# this system contains administrator password hashes, audit history and, if
# transcript storage was ever enabled, resident questions. Writing that to disk
# in the clear, or to object storage later, is a data protection problem.
#
# Restoring is scripts/restore.sh. A backup that has never been restored is a
# hope, not a backup, so the operations runbook schedules restore drills.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "No .env found. Run 'make setup' first." >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a; source .env; set +a

BACKUP_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BASENAME="dumi-${STAMP}.sql.gz"
TARGET="${BACKUP_DIR}/${BASENAME}"

echo "Dumping ${POSTGRES_DB:-dumi} ..."
# PGPASSWORD is exported for this command only, so the password does not appear
# in the process list of any other command.
PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
  --host "${PGHOST:-127.0.0.1}" \
  --port "${PGPORT:-5432}" \
  --username "${POSTGRES_USER}" \
  --dbname "${POSTGRES_DB}" \
  --no-owner --no-privileges --clean --if-exists \
  | gzip -9 > "$TARGET"

if command -v age >/dev/null 2>&1 && [ -n "${BACKUP_AGE_RECIPIENT:-}" ]; then
  echo "Encrypting to ${BACKUP_AGE_RECIPIENT} ..."
  age -r "${BACKUP_AGE_RECIPIENT}" -o "${TARGET}.age" "$TARGET"
  rm -f "$TARGET"
  TARGET="${TARGET}.age"
else
  echo ""
  echo "WARNING: this backup is NOT encrypted."
  echo "It contains password hashes and audit history. Install age and set"
  echo "BACKUP_AGE_RECIPIENT before storing it anywhere but this machine."
fi

chmod 600 "$TARGET"
echo "Wrote $TARGET ($(du -h "$TARGET" | cut -f1))"
