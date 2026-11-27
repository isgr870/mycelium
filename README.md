# Mycelium (`v0.4.0-alpha`)

Mycelium is a distributed, self-defending mesh networking and spore-replication prototype inspired by underground fungal networks—featuring **septal quarantine** of misbehaving peers, **anastomosis rerouting** around degraded links, **alarm advisories**, HMAC-SHA256 packet signing, key rotation, and SQLite WAL persistence.

## Current Status & Readiness

- **Stage:** `v0.4.0-alpha` — ready for **controlled multi-node testing, peer review, and pre-audit validation**.
- **Not yet open-WAN production / formal-audit ready:** See [SECURITY.md](SECURITY.md) and [AUDIT_READINESS.md](AUDIT_READINESS.md) before exposing nodes beyond trusted WireGuard/TLS overlays or handling sensitive/regulated data.

## Quick Start (Local / Linux / Termux)

```bash
git clone [https://github.com/isgr870/mycelium.git](https://github.com/isgr870/mycelium.git)
cd mycelium
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and set a strong MYCELIUM_SECRET_KEY

Running the Test Suite
source venv/bin/activate
PYTHONPATH=. python -m pytest -v

Multi-Region & Encrypted Transport Guidance
 * Run cross-region traffic (e.g., across America, Uganda, and Asia) over WireGuard or HTTPS/TLS rather than plain HTTP on public interfaces.
 * Keep MYCELIUM_MAX_CLOCK_SKEW_SECONDS aligned with NTP synchronization across regions.
 * Store SQLite databases on durable storage and back up state before upgrades.
   EOF
cat << 'EOF' > AUDIT_READINESS.md
Mycelium Pre-Audit & Global Readiness Checklist
Use this checklist before external security/legal review or wider multi-region tester rollout.
1. Transport & Cryptographic Security
 * [ ] All non-loopback and cross-region links run over WireGuard or HTTPS/TLS (never unencrypted HTTP over public WAN).
 * [ ] Every node uses a high-entropy MYCELIUM_SECRET_KEY (and MYCELIUM_SECONDARY_SECRET_KEY during rotations), with documented key-rotation and compromise-response steps.
 * [ ] Replay protection (seen_nonces in SQLite WAL) and MYCELIUM_MAX_CLOCK_SKEW_SECONDS are verified across node restarts.
2. Self-Defense & Resilience
 * [ ] MycelialDefense strike thresholds, exponential quarantine windows, alarm advisories, and healthy-streak recovery match expected WAN behavior without false-locking healthy high-latency peers.
 * [ ] Offline store-and-forward queue (resilience_queue) and Bloom manifest spore sync handle temporary peer partitions and recovery cleanly.
3. Observability & Operations
 * [ ] Logs avoid leaking secret keys, raw tokens, or sensitive payload contents.
 * [ ] Health checks, peer status (/mesh/peers), and systemd (or process supervisor) restart policies are verified on target Linux hosts.
4. Legal, Privacy & Cross-Border Data
 * [ ] Confirm what data is placed inside replicated spores—avoid sensitive personal data or regulated records unless cross-border transfer, retention, and deletion requirements for involved jurisdictions are addressed.
 * [ ] Keep LICENSE (MIT) and SECURITY.md accurate as features and threat boundaries evolve.
   EOF
cat << 'EOF' > tests/test_wan_chaos_and_recovery.py
import hashlib
import hmac
import json
import time
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core import wan_mesh
from core.mycelial_defense import MycelialDefense
def _sign(body: bytes, secret: str) -> str:
return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
def test_wan_skew_window_allows_delayed_packet_and_blocks_excessive_drift(monkeypatch):
secret = "wan-chaos-secret-key-64-chars-1234567890abcdef1234567890abcdef12"
monkeypatch.setenv("MYCELIUM_SECRET_KEY", secret)
monkeypatch.setenv("MYCELIUM_MAX_CLOCK_SKEW_SECONDS", "240")
wan_mesh.PEER_REGISTRY.clear()
wan_mesh.DEFENSE._peers.clear()
app = FastAPI()
app.include_router(wan_mesh.router)
client = TestClient(app)
now = int(time.time())
delayed_env = {
"ts": now - 120,
"payload": {"self_url": "https://ug-node.wg.mesh", "known_peers": ["https://ug-node.wg.mesh"]},
}
raw_delayed = json.dumps(delayed_env, separators=(",", ":"), sort_keys=True).encode("utf-8")
ok_resp = client.post(
"/mesh/gossip",
content=raw_delayed,
headers={"X-Mycelium-Signature": _sign(raw_delayed, secret)},
)
assert ok_resp.status_code == 200
stale_env = {
"ts": now - 600,
"payload": {"self_url": "https://drifting-node.wg.mesh"},
}
raw_stale = json.dumps(stale_env, separators=(",", ":"), sort_keys=True).encode("utf-8")
bad_resp = client.post(
"/mesh/gossip",
content=raw_stale,
headers={"X-Mycelium-Signature": _sign(raw_stale, secret)},
)
assert bad_resp.status_code == 401
def test_partition_reroute_and_healthy_recovery_across_regions():
defense = MycelialDefense(
strike_threshold=2,
base_quarantine_seconds=45.0,
max_quarantine_seconds=300.0,
recovery_healthy_streak=2,
)
us_peer = "https://us-east.wg.mesh"
ug_peer = "https://ug-kampala.wg.mesh"
asia_peer = "https://asia-sg.wg.mesh"
t0 = 1_770_000_000.0
defense.record_violation(us_peer, "partition_timeout", now=t0)
defense.record_violation(us_peer, "partition_timeout", now=t0 + 5)
assert defense.is_quarantined(us_peer, now=t0 + 10) is True
assert defense.route_peers([us_peer, ug_peer, asia_peer], now=t0 + 10) == [ug_peer, asia_peer]
assert defense.is_quarantined(us_peer, now=t0 + 60) is False
defense.record_healthy(us_peer)
defense.record_healthy(us_peer)
assert defense.route_peers([us_peer, ug_peer, asia_peer], now=t0 + 60) == [
us_peer,
ug_peer,
asia_peer,
]
