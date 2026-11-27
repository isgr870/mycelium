#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <url1> [url2 ...]" >&2
  exit 1
fi

TMP_JSON="${PREFIX:-/tmp}/tmp/myc_probe_status.json"
mkdir -p "$(dirname "$TMP_JSON")"

date -u +"CLOCK_UTC=%Y-%m-%dT%H:%M:%SZ EPOCH=%s"

for base in "$@"; do
  url="${base%/}"
  t0=$(python3 -c 'import time; print(int(time.time()*1000))')
  code=$(curl -s -o "$TMP_JSON" -w "%{http_code}" --max-time 4 "${url}/status" || echo "000")
  t1=$(python3 -c 'import time; print(int(time.time()*1000))')
  rtt=$((t1 - t0))

  spores="n/a"
  if [[ "$code" == "200" ]]; then
    spores=$(curl -sf --max-time 4 "${url}/mesh/spores/manifest" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get("count", len(d.get("spore_ids", d.get("spores", [])))))
except Exception:
    print("err")
' 2>/dev/null || echo "err")
  fi

  printf "%-26s HTTP=%s  RTT=%4sms  SPORES=%s\n" "$url" "$code" "$rtt" "$spores"
done

rm -f "$TMP_JSON"
