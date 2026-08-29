#!/usr/bin/env bash
# Restore a database backup.
#
#   ./scripts/restore.sh backups/dumi-20260101T000000Z.sql.gz.age
#
# This REPLACES the current database contents. It asks for confirmation,
# because the most common way to lose data during an incident is a restore run
# against the wrong database.
set -euo pipefail

cd "$(dirname "$0")/.."

FILE="${1:-}"
if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
  echo "Usage: ./scripts/restore.sh <backup file>" >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a; source .env; set +a

echo "About to REPLACE the contents of:"
echo "  database ${POSTGRES_DB} on ${PGHOST:-127.0.0.1}:${PGPORT:-5432}"
echo "  from     $FILE"
echo ""
read -r -p "Type the database name to confirm: " CONFIRM
if [ "$CONFIRM" != "${POSTGRES_DB}" ]; then
  echo "Did not match. Nothing was changed." >&2
  exit 1
fi

STREAM="cat"
case "$FILE" in
  *.age)
    command -v age >/dev/null 2>&1 || { echo "age is required to decrypt this backup." >&2; exit 1; }
    STREAM="age -d -i ${BACKUP_AGE_IDENTITY:?BACKUP_AGE_IDENTITY must point at the private key}"
    ;;
esac

$STREAM "$FILE" | gunzip | PGPASSWORD="${POSTGRES_PASSWORD}" psql \
  --host "${PGHOST:-127.0.0.1}" \
  --port "${PGPORT:-5432}" \
  --username "${POSTGRES_USER}" \
  --dbname "${POSTGRES_DB}" \
  --quiet --set ON_ERROR_STOP=on

echo ""
echo "Restore complete. Now verify:"
echo "  .venv/bin/alembic current       # schema is at the expected revision"
echo "  python -m app.cli verify-audit  # the audit chain survived the round trip"
