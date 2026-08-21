#!/usr/bin/env bash
# Daily Postgres backup for the AniFillerPedia droplet — internal operational
# recovery only, never public-facing (see #10/#22, deliberately distinct
# questions). Matches the daily-cadence convention of the existing Unraid
# backup scripts (see global ~/.claude/CLAUDE.md's Unraid Scripts table).
#
# Run via cron on the droplet (not inside a container — this shells out to
# `docker exec` against the running afp-postgres container). Suggested crontab
# line, installed manually during #10/#25's provisioning, not by this script:
#   5 4 * * * /path/to/scripts/backup-postgres.sh >> /var/log/afp-backup.log 2>&1
#
# Retention: keeps the last 14 daily dumps, deletes anything older. Not yet
# wired to off-droplet storage (e.g. DO Spaces) — a same-disk backup doesn't
# protect against droplet-level failure, only accidental data loss/corruption
# within Postgres itself. Worth a follow-up once this is actually running.

set -euo pipefail

BACKUP_DIR="${AFP_BACKUP_DIR:-/opt/afp/backups}"
RETENTION_DAYS=14
TIMESTAMP="$(date +%Y-%m-%d_%H%M%S)"
DUMP_FILE="${BACKUP_DIR}/afp-postgres_${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

docker exec afp-postgres pg_dump -U anifillerpedia anifillerpedia | gzip > "${DUMP_FILE}"

if [ ! -s "${DUMP_FILE}" ]; then
  echo "ERROR: backup produced an empty file: ${DUMP_FILE}" >&2
  rm -f "${DUMP_FILE}"
  exit 1
fi

echo "Backup written: ${DUMP_FILE} ($(du -h "${DUMP_FILE}" | cut -f1))"

find "${BACKUP_DIR}" -name 'afp-postgres_*.sql.gz' -mtime "+${RETENTION_DAYS}" -delete

echo "Retention: keeping backups from the last ${RETENTION_DAYS} days."
