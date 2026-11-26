import json
import time
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.security_hardening import sign_packet
from core.spore_vault_sync import router as spore_router, store_spore, build_local_bloom
from core.resilience_queue import router as resilience_router, enqueue_outbound, queue_depth


def test_spore_replication_and_bloom_manifest(monkeypatch, tmp_path):
    secret = "d" * 64
    monkeypatch.setenv("MYCELIUM_SECRET_KEY", secret)
    monkeypatch.setattr("core.spore_vault_sync.DB_PATH", str(tmp_path / "test_mesh.db"))

    app = FastAPI()
    app.include_router(spore_router)
    client = TestClient(app)

    store_spore("free-press", {"title": "Mesh Bulletin", "body": "Unthrottled edge note"}, author_node="node-1")

    manifest_resp = client.get("/mesh/spores/manifest")
    assert manifest_resp.status_code == 200
    assert manifest_resp.json()["count"] == 1

    push_payload = {
        "spores": [
            {"topic": "archive", "content": {"doc": "resilient-vault-entry"}, "author_node": "peer-2"}
        ]
    }
    raw = json.dumps({"ts": int(time.time()), "payload": push_payload}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = sign_packet(raw, secret)

    unsigned = client.post("/mesh/spores/push", content=raw)
    assert unsigned.status_code == 401

    signed = client.post("/mesh/spores/push", content=raw, headers={"X-Mycelium-Signature": sig})
    assert signed.status_code == 200
    assert signed.json()["accepted_count"] == 1


def test_resilience_queue_persists_when_peer_offline(monkeypatch, tmp_path):
    secret = "e" * 64
    monkeypatch.setenv("MYCELIUM_SECRET_KEY", secret)
    monkeypatch.setattr("core.resilience_queue.DB_PATH", str(tmp_path / "test_mesh.db"))

    app = FastAPI()
    app.include_router(resilience_router)
    client = TestClient(app)

    enqueue_outbound("https://unreachable-peer.example.com", "/mesh/spores/push", {"spores": []})
    assert queue_depth() == 1

    status_resp = client.get("/mesh/resilience/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["queued_packets"] == 1
