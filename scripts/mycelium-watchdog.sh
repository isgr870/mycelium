#!/usr/bin/env bash
set -euo pipefail

INTERVAL_SEC="${MYCELIUM_WATCHDOG_INTERVAL:-60}"
BACKUP_EVERY_N="${MYCELIUM_BACKUP_EVERY_N:-5}"
TERMUX_PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
BASE_DIR="${TERMUX_PREFIX}/tmp/mycelium_regions"
LOG_FILE="${BASE_DIR}/watchdog.log"
PID_FILE="${BASE_DIR}/watchdog.pid"
REGIONS_SCRIPT="$HOME/mycelium/scripts/mycelium-regions.sh"
BACKUP_SCRIPT="$HOME/mycelium/scripts/termux-backup.sh"

mkdir -p "$BASE_DIR"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "WATCHDOG_ALREADY_RUNNING pid=$(cat "$PID_FILE")"
  exit 0
fi

WAKE_HELD=0
if command -v termux-wake-lock >/dev/null 2>&1; then
  if termux-wake-lock 2>/dev/null; then
    WAKE_HELD=1
  fi
fi

cleanup() {
  rm -f "$PID_FILE"
  if [[ "$WAKE_HELD" -eq 1 ]] && command -v termux-wake-unlock >/dev/null 2>&1; then
    termux-wake-unlock 2>/dev/null || true
  fi
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WATCHDOG_STOPPED wake_lock_released=${WAKE_HELD}" >> "$LOG_FILE"
}

echo "$$" > "$PID_FILE"
trap cleanup EXIT

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WATCHDOG_STARTED pid=$$ interval=${INTERVAL_SEC}s backup_every=${BACKUP_EVERY_N} wake_lock=${WAKE_HELD}" >> "$LOG_FILE"

ensure_relays_healthy() {
  local unhealthy=0


  for port in 8101 8102 8103; do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "http://127.0.0.1:${port}/status" || echo "000")
    if [[ "$code" != "200" ]]; then
      echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] RELAY_DOWN port=${port} http=${code} -> triggering start"
      unhealthy=1
    fi
  done
  if [[ "$unhealthy" -eq 1 ]]; then
    "$REGIONS_SCRIPT" start
  fi
}


MYCELIUM_SYNC_INTERVAL_SEC="${MYCELIUM_SYNC_INTERVAL_SEC:-60}"
MYCELIUM_PEER_URLS="${MYCELIUM_PEER_URLS:-http://127.0.0.1:8101,http://127.0.0.1:8102,http://127.0.0.1:8103}"
LAST_HYPHAL_SYNC_EPOCH=0

run_hyphal_sync_pass() {
  local now_epoch
  now_epoch="$(date +%s)"
  if (( now_epoch - LAST_HYPHAL_SYNC_EPOCH < MYCELIUM_SYNC_INTERVAL_SEC )); then
    return 0
  fi
  LAST_HYPHAL_SYNC_EPOCH="$now_epoch"

  local py_bin="${VIRTUAL_ENV:-$HOME/mycelium/venv}/bin/python"
  [[ -x "$py_bin" ]] || py_bin="python3"

  local pairs=("us:8101" "ug:8102" "asia:8103")
  for pair in "${pairs[@]}"; do
    local reg="${pair%%:*}"
    local port="${pair##*:}"
    MYCELIUM_REGION="$reg" \
    MYCELIUM_PORT="$port" \
    MYCELIUM_PEER_URLS="$MYCELIUM_PEER_URLS" \
      "$py_bin" -m core.hyphal_sync >/dev/null 2>&1 || true
  done
}

cycle=0
while true; do
  cycle=$((cycle + 1))
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  {
    echo "=== CYCLE ${cycle} @ ${ts} ==="
    ensure_relays_healthy
    "$REGIONS_SCRIPT" sync
    run_hyphal_sync_pass
    if (( cycle % BACKUP_EVERY_N == 0 )); then
      for r in us ug asia; do
        MYCELIUM_BACKUP_TAG="region-${r}" \
        MYCELIUM_DB_PATH="${BASE_DIR}/${r}/${r}.db" \
        "$BACKUP_SCRIPT"
      done
    fi
  } >> "$LOG_FILE" 2>&1 || echo "[${ts}] CYCLE_${cycle}_WARN check $LOG_FILE" >> "$LOG_FILE"

  sleep "$INTERVAL_SEC"
done
