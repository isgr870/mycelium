#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -d "$ROOT_DIR/venv" ]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/venv/bin/activate"
fi

if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

export MYCELIUM_SECRET_KEY="${MYCELIUM_SECRET_KEY:-$(python3 -c 'import secrets; print(secrets.token_hex(32))')}"
export MYCELIUM_GOSSIP_FANOUT="${MYCELIUM_GOSSIP_FANOUT:-6}"
export MYCELIUM_BLOOM_MAX_BITS="${MYCELIUM_BLOOM_MAX_BITS:-65536}"

TMP_BASE="${PREFIX:-}/tmp"
[ -z "$TMP_BASE" ] && TMP_BASE="/tmp"
CLUSTER_DIR="$TMP_BASE/mycelium_cluster"
PID_FILE="$CLUSTER_DIR/pids.env"

cmd="${1:-start}"

start_node() {
  local name="$1"
  local role="$2"
  local caps="$3"
  local port="$4"
  local node_dir="$CLUSTER_DIR/$name"
  mkdir -p "$node_dir"

  MYCELIUM_DATA_DIR="$node_dir" \
  MYCELIUM_DB_PATH="$node_dir/${name}.db" \
  MYCELIUM_ROLE="$role" \
  MYCELIUM_CAPABILITIES="$caps" \
  MYCELIUM_NODE_ID="${name}-01" \
  MYCELIUM_HOST="127.0.0.1" \
  MYCELIUM_PORT="$port" \
  python node.py > "$CLUSTER_DIR/${name}.log" 2>&1 &

  echo "PID_${name^^}=$!" >> "$PID_FILE"
  echo "Started $name ($role) on 127.0.0.1:$port (PID $!)"
}

stop_cluster() {
  if [ -f "$PID_FILE" ]; then
    # shellcheck disable=SC1090
    source "$PID_FILE"
    for pid in "${PID_RELAY:-}" "${PID_STORAGE:-}" "${PID_WORKER:-}"; do
      if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        echo "Stopped PID $pid"
      fi
    done
    rm -f "$PID_FILE"
  fi
  else
    echo "No active cluster PID file at $PID_FILE"
  fi
  release_wakelock
}


register_cluster_peers() {
  python3 - << 'REG_EOF'
import json
import os
import time
import urllib.request
from core.security_hardening import sign_packet

nodes = [
    ("relay", "relay-01", "http://127.0.0.1:8021"),
    ("storage", "storage-01", "http://127.0.0.1:8022"),
    ("worker", "worker-01", "http://127.0.0.1:8023"),
]
secret = os.environ.get("MYCELIUM_SECRET_KEY", "")

for _, _, url in nodes:
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"{url}/mesh/spores/role", timeout=1) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.25)

peer_entries = [{"url": u, "role": r, "node_id": nid} for r, nid, u in nodes]
for _, _, target_base in nodes:
    for entry in peer_entries:
        payload = {
            "url": entry["url"],
            "role": entry["role"],
            "node_id": entry["node_id"],
            "peers": peer_entries,
        }
        raw = json.dumps({"ts": int(time.time()), "payload": payload}, separators=(",", ":"), sort_keys=True).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["X-Mycelium-Signature"] = sign_packet(raw, secret)
        try:
            req = urllib.request.Request(
                f"{target_base}/mesh/spores/peers/register",
                data=raw,
                method="POST",
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                resp.read()
        except Exception:
            pass
print("Auto-registered relay, storage, and worker peers.")
REG_EOF
}


acquire_wakelock() {
  if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock >/dev/null 2>&1 && echo "Acquired Termux wake-lock." || true
  fi
}

release_wakelock() {
  if command -v termux-wake-unlock >/dev/null 2>&1; then
    termux-wake-unlock >/dev/null 2>&1 && echo "Released Termux wake-lock." || true
  fi
}

status_cluster() {
  for port in 8021 8022 8023; do
    if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${port}/mesh/spores/role', timeout=1)" >/dev/null 2>&1; then
      echo "Port $port: UP"
    else
      echo "Port $port: DOWN"
    fi
  done
}

case "$cmd" in
  start)
    stop_cluster
    mkdir -p "$CLUSTER_DIR"
    : > "$PID_FILE"
    acquire_wakelock
    start_node "relay" "relay" "gossip,relay,sync" "8021"
    start_node "storage" "storage" "vault,archive,sync" "8022"
    start_node "worker" "worker" "compute,sync" "8023"
    register_cluster_peers
    status_cluster
    ;;
  stop)
    stop_cluster
    ;;
  status)
    status_cluster
    ;;
  *)
    echo "Usage: $0 {start|stop|status}"
    exit 1
    ;;
esac
