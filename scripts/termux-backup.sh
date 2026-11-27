#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${MYCELIUM_DB_PATH:-$PREFIX/tmp/mycelium_stage/node1.db}"
BACKUP_DIR="${MYCELIUM_BACKUP_DIR:-$PREFIX/tmp/mycelium_backups}"
KEEP_COUNT="${MYCELIUM_BACKUP_KEEP_COUNT:-10}"
DB_STEM="$(basename "${DB_PATH%.*}")"
TAG="${MYCELIUM_BACKUP_TAG:-$DB_STEM}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
MS="$(python3 -c 'import time; print(int(time.time()*1000) % 1000)')"
OUT_FILE="${BACKUP_DIR}/mycelium-${TAG}-${STAMP}-${MS}ms.sqlite3"

if [[ ! -f "$DB_PATH" ]]; then
  echo "ERROR: DB not found at $DB_PATH" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
sqlite3 "$DB_PATH" ".backup '${OUT_FILE}'"
sqlite3 "$OUT_FILE" "PRAGMA integrity_check;" | grep -qx "ok"

ls -1t "${BACKUP_DIR}"/mycelium-*.sqlite3 2>/dev/null | tail -n +"$((KEEP_COUNT + 1))" | xargs -r rm -f
echo "BACKUP_OK file=${OUT_FILE} kept=${KEEP_COUNT}"
