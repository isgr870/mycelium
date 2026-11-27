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
