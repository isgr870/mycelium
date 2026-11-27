import hashlib
import hmac
import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import wan_mesh


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_gossip_quarantines_after_repeated_bad_hmac_and_propagates_advisory(monkeypatch):
    secret = "mesh-defense-secret-key-1234567890"
    monkeypatch.setenv("MYCELIUM_SECRET_KEY", secret)
    wan_mesh.PEER_REGISTRY.clear()
    wan_mesh.DEFENSE._peers.clear()

    app = FastAPI()
    app.include_router(wan_mesh.router)
    client = TestClient(app)

    bad_env = {"ts": int(time.time()), "payload": {"self_url": "https://rogue.mesh"}}
    raw_bad = json.dumps(bad_env, separators=(",", ":"), sort_keys=True).encode("utf-8")

    for _ in range(wan_mesh.DEFENSE.strike_threshold):
        r = client.post(
            "/mesh/gossip",
            content=raw_bad,
            headers={"Content-Type": "application/json", "X-Mycelium-Signature": "bad-sig"},
        )
        assert r.status_code == 401

    assert wan_mesh.DEFENSE.is_quarantined("testclient") is True

    # Signed advisories across strike_threshold wall off compromised node
    for i in range(wan_mesh.DEFENSE.strike_threshold):
        adv_env = {
            "ts": int(time.time()),
            "payload": {
                "self_url": "https://ug-relay.mesh",
                "known_peers": [
                    "https://ug-relay.mesh",
                    "https://compromised.mesh",
                    "https://asia-relay.mesh",
                ],
                "quarantined_peers": ["https://compromised.mesh"],
                "seq": i,
            },
        }
        raw_adv = json.dumps(adv_env, separators=(",", ":"), sort_keys=True).encode("utf-8")
        r_adv = client.post(
            "/mesh/gossip",
            content=raw_adv,
            headers={
                "Content-Type": "application/json",
                "X-Mycelium-Signature": _sign(raw_adv, secret),
            },
        )
        assert r_adv.status_code == 200

    routed = wan_mesh.DEFENSE.route_peers(
        ["https://compromised.mesh", "https://ug-relay.mesh", "https://asia-relay.mesh"]
    )
    assert routed == ["https://ug-relay.mesh", "https://asia-relay.mesh"]


def test_partition_and_heal_reroutes_cleanly():
    wan_mesh.DEFENSE._peers.clear()
    peer = "https://us-node.mesh"
    for _ in range(wan_mesh.DEFENSE.strike_threshold):
        wan_mesh.DEFENSE.record_violation(peer, "transient_timeout", now=1000.0)

    assert wan_mesh.DEFENSE.is_quarantined(peer, now=1010.0) is True
    assert wan_mesh.DEFENSE.route_peers([peer, "https://ug-node.mesh"], now=1010.0) == [
        "https://ug-node.mesh"
    ]

    # After quarantine window passes and healthy heartbeats arrive, peer heals
    assert wan_mesh.DEFENSE.is_quarantined(peer, now=2000.0) is False
    assert wan_mesh.DEFENSE.route_peers([peer, "https://ug-node.mesh"], now=2000.0) == [
        peer,
        "https://ug-node.mesh",
    ]
