#!/usr/bin/env bash
set -euo pipefail

CMD="${1:-status}"
REPO_DIR="$HOME/mycelium"
TERMUX_PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
BASE_DIR="${TERMUX_PREFIX}/tmp/mycelium_regions"
TRUST_FILE="${BASE_DIR}/peers_trust.json"
IDS_FILE="${BASE_DIR}/region_identities.json"
BIND_HOST="${MYCELIUM_BIND_HOST:-127.0.0.1}"
EXTRA_PEERS="${MYCELIUM_EXTRA_PEERS:-}"

set -a
[ -f "${REPO_DIR}/.env" ] && . "${REPO_DIR}/.env"
export MYCELIUM_TRUST_REGISTRY="$TRUST_FILE"
export PYTHONPATH="$REPO_DIR"
set +a

start_region() {
  local code="$1"
  local port="$2"
  local rdir="${BASE_DIR}/${code}"
  local db_path="${rdir}/${code}.db"
  local log_path="${rdir}/uvicorn.log"

  pkill -f "uvicorn main:app --host .* --port ${port}" 2>/dev/null || true
  sleep 0.3

  MYCELIUM_REGION="$code" \
  MYCELIUM_BIND_HOST="$BIND_HOST" \
  MYCELIUM_DB_PATH="$db_path" \
  nohup "${REPO_DIR}/venv/bin/uvicorn" main:app --host "$BIND_HOST" --port "$port" \
    > "$log_path" 2>&1 &
  echo "STARTED region=${code} host=${BIND_HOST} port=${port} db=${db_path}"
}

stop_all() {
  for port in 8101 8102 8103; do
    pkill -f "uvicorn main:app --host .* --port ${port}" 2>/dev/null || true
  done
  echo "STOPPED_REGIONS us(8101) ug(8102) asia(8103)"
}

probe_all() {
  local targets=("http://127.0.0.1:8101" "http://127.0.0.1:8102" "http://127.0.0.1:8103")
  if [[ -n "$EXTRA_PEERS" ]]; then
    IFS=',' read -ra extras <<< "$EXTRA_PEERS"
    for ep in "${extras[@]}"; do
      ep="$(echo "$ep" | xargs)"
      [[ -n "$ep" ]] && targets+=("$ep")
    done
  fi
  "${REPO_DIR}/scripts/termux-probe.sh" "${targets[@]}"
}

sync_all() {
  python3 - << 'PYEOF'
import json
import os
import subprocess
from pathlib import Path

prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
base = Path(prefix) / "tmp/mycelium_regions"
ids = json.loads((base / "region_identities.json").read_text(encoding="utf-8"))
py_bin = "/data/data/com.termux/files/home/mycelium/venv/bin/python"
sync_script = "/data/data/com.termux/files/home/mycelium/scripts/mycelium-delta-sync.py"

endpoints = {
    "us": "http://127.0.0.1:8101",
    "ug": "http://127.0.0.1:8102",
    "asia": "http://127.0.0.1:8103",
}

pairs = [("us", "ug"), ("ug", "asia"), ("us", "asia")]
for a, b in pairs:
    ident = ids[a]
    res = subprocess.run(
        [
            py_bin, sync_script,
            "--node-a", endpoints[a],
            "--node-b", endpoints[b],
            "--peer-id", ident["node_id"],
            "--ed25519-privkey", ident["private_key_b64"],
        ],
        capture_output=True, text=True, check=True,
    )
    print(f"[{a} <-> {b}] {res.stdout.strip()}")

extra = [u.strip().rstrip("/") for u in os.environ.get("MYCELIUM_EXTRA_PEERS", "").split(",") if u.strip()]
for remote_url in extra:
    ident = ids["ug"]
    res = subprocess.run(
        [
            py_bin, sync_script,
            "--node-a", endpoints["ug"],
            "--node-b", remote_url,
            "--peer-id", ident["node_id"],
            "--ed25519-privkey", ident["private_key_b64"],
        ],
        capture_output=True, text=True, check=True,
    )
    print(f"[ug <-> wan:{remote_url}] {res.stdout.strip()}")
PYEOF
}

case "$CMD" in
  start)
    start_region "us" "8101"
    start_region "ug" "8102"
    start_region "asia" "8103"
    sleep 2
    probe_all
    ;;
  stop)
    stop_all
    ;;
  status)
    probe_all
    ;;
  sync)
    sync_all
    probe_all
    ;;
  *)
    echo "Usage: $0 {start|stop|status|sync}" >&2
    exit 1
    ;;
esac
