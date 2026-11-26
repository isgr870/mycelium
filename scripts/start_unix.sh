#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d venv ] && source venv/bin/activate
if [ -f .env ]; then
  set -a && source .env && set +a
fi
export MYCELIUM_SECRET_KEY="${MYCELIUM_SECRET_KEY:-$(python3 -c 'import secrets; print(secrets.token_hex(32))')}"
export MYCELIUM_HOST="${MYCELIUM_HOST:-127.0.0.1}"
export MYCELIUM_PORT="${MYCELIUM_PORT:-8000}"
exec python node.py
