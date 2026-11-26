import json
import time
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.security_hardening import sign_packet
from core.spore_vault_sync import router as spore_router


def _signed_headers(secret: str, payload: dict, ts: int | None = None) -> tuple[bytes, dict]:
    stamp = int(time.time()) if ts is None else ts
    raw = json.dumps({"ts": stamp, "payload": payload}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return raw, {
        "Content-Type": "application/json",
        "X-Mycelium-Signature": sign_packet(raw, secret),
    }


def test_role_status_and_dynamic_db(monkeypatch, tmp_path):
    secret = "e" * 64
    monkeypatch.setenv("MYCELIUM_SECRET_KEY", secret)
    monkeypatch.setenv("MYCELIUM_ROLE", "relay")
    monkeypatch.setenv("MYCELIUM_CAPABILITIES", "gossip,sync")
    monkeypatch.setenv("MYCELIUM_NODE_ID", "relay-unit-01")
    monkeypatch.setattr("core.spore_vault_sync.DB_PATH", str(tmp_path / "role_unit.db"))

    app = FastAPI()
    app.include_router(spore_router)
    client = TestClient(app)

    resp = client.get("/mesh/spores/role")
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "relay"
    assert body["capabilities"] == ["gossip", "sync"]
    assert body["node_id"] == "relay-unit-01"
    assert body["recommended_bloom"]["size"] >= 512


def test_job_claim_contention_and_expiry_reclaim(monkeypatch, tmp_path):
    secret = "f" * 64
    monkeypatch.setenv("MYCELIUM_SECRET_KEY", secret)
    monkeypatch.setattr("core.spore_vault_sync.DB_PATH", str(tmp_path / "lease_unit.db"))

    app = FastAPI()
    app.include_router(spore_router)
    client = TestClient(app)

    t0 = int(time.time())
    raw_create, hdr_create = _signed_headers(
        secret,
        {"goal_id": "g-unit", "job_type": "compute", "task": {"item": 1}, "lease_seconds": 15},
        ts=t0,
    )
    created = client.post("/mesh/spores/jobs/create", content=raw_create, headers=hdr_create)
    assert created.status_code == 200
    job_id = created.json()["job"]["job_id"]

    raw_a, hdr_a = _signed_headers(secret, {"job_id": job_id, "worker_id": "worker-a", "lease_seconds": 15}, ts=t0)
    claim_a = client.post("/mesh/spores/jobs/claim", content=raw_a, headers=hdr_a).json()
    assert claim_a["claimed"] is True

    raw_b, hdr_b = _signed_headers(secret, {"job_id": job_id, "worker_id": "worker-b", "lease_seconds": 15}, ts=t0)
    claim_b = client.post("/mesh/spores/jobs/claim", content=raw_b, headers=hdr_b).json()
    assert claim_b["claimed"] is False
    assert claim_b["reason"] == "leased_by_another_worker"

    # Simulate clock advancing 20s past the 15s lease window (still within 120s clock skew)
    future_ts = t0 + 20
    monkeypatch.setattr(time, "time", lambda: future_ts)
    raw_reclaim, hdr_reclaim = _signed_headers(
        secret,
        {"job_id": job_id, "worker_id": "worker-b", "lease_seconds": 60},
        ts=future_ts,
    )
    reclaim = client.post("/mesh/spores/jobs/claim", content=raw_reclaim, headers=hdr_reclaim).json()
    assert reclaim["claimed"] is True
    assert reclaim["job"]["lease_owner"] == "worker-b"


def test_k6_gossip_sampling_and_deduplication(monkeypatch, tmp_path):
    secret = "a" * 64
    monkeypatch.setenv("MYCELIUM_SECRET_KEY", secret)
    monkeypatch.setenv("MYCELIUM_GOSSIP_FANOUT", "6")
    monkeypatch.setattr("core.spore_vault_sync.DB_PATH", str(tmp_path / "gossip_unit.db"))

    app = FastAPI()
    app.include_router(spore_router)
    client = TestClient(app)

    for idx in range(15):
        raw_p, hdr_p = _signed_headers(secret, {"url": f"http://10.1.0.{idx+1}:8000", "role": "worker"})
        assert client.post("/mesh/spores/peers/register", content=raw_p, headers=hdr_p).status_code == 200

    raw_g1, hdr_g1 = _signed_headers(secret, {"gossip_id": "unit-gossip-1", "ttl": 5, "hop": 0, "fanout": 6})
    t1 = client.post("/mesh/spores/gossip/tick", content=raw_g1, headers=hdr_g1).json()
    assert t1["accepted_for_forward"] is True
    assert t1["sampled_fanout"] == 6
    assert t1["ttl_remaining"] == 4

    raw_g2, hdr_g2 = _signed_headers(secret, {"gossip_id": "unit-gossip-1", "ttl": 5, "hop": 1, "fanout": 6})
    t2 = client.post("/mesh/spores/gossip/tick", content=raw_g2, headers=hdr_g2).json()
    assert t2["accepted_for_forward"] is False


def test_active_gossip_forwarder_handles_unreachable_peer(monkeypatch):
    import core.spore_vault_sync as svs

    monkeypatch.setenv("MYCELIUM_SECRET_KEY", "b" * 64)
    svs._PEER_TABLE.clear()
    svs._SEEN_GOSSIP_IDS.clear()
    svs.register_peer("http://127.0.0.1:59999", role="worker", node_id="dead-peer")

    report = svs.forward_gossip_to_peers(
        gossip_id="fwd-test-01",
        ttl=4,
        hop=0,
        fanout=6,
        data={"msg": "hello-mesh"},
        timeout_sec=0.2,
    )
    assert report["gossip_id"] == "fwd-test-01"
    assert report["forwarded_count"] == 0
    assert report["failed_count"] == 1
    assert report["next_ttl"] == 3
    assert report["next_hop"] == 1


def test_bloom_sizing_scales_for_1000_plus_nodes(monkeypatch):
    import core.spore_vault_sync as svs

    monkeypatch.setenv("MYCELIUM_BLOOM_MAX_BITS", "65536")
    small = svs.recommend_bloom_params(10)
    large = svs.recommend_bloom_params(1500)

    assert large["size_bits"] > small["size_bits"]
    assert large["size_bits"] >= 8192
    assert large["size_bits"] <= 65536
    assert 3 <= large["hash_count"] <= 8


def test_background_gossip_loop_start_and_stop(monkeypatch):
    import core.spore_vault_sync as svs

    monkeypatch.setenv("MYCELIUM_GOSSIP_INTERVAL_SEC", "1.0")
    svs._PEER_TABLE.clear()
    svs._SEEN_GOSSIP_IDS.clear()

    started = svs.start_background_gossip_loop(base_interval=1.0)
    assert started is True
    svs.stop_background_gossip_loop(timeout=1.5)
    assert svs._GOSSIP_STOP_EVENT.is_set()
