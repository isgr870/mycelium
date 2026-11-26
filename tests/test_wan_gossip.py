from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.security_hardening import sign_packet
from core.wan_mesh import router, build_signed_envelope, PEER_REGISTRY


def test_wan_gossip_rejects_unsigned_and_accepts_signed(monkeypatch):
    secret = "c" * 64
    monkeypatch.setenv("MYCELIUM_SECRET_KEY", secret)
    PEER_REGISTRY.clear()

    test_app = FastAPI()
    test_app.include_router(router)
    client = TestClient(test_app)

    raw = build_signed_envelope(
        {"self_url": "https://peer-a.example.com", "known_peers": ["https://peer-b.example.com"]},
        secret,
    )

    # Unsigned request must be rejected
    bad_resp = client.post("/mesh/gossip", content=raw)
    assert bad_resp.status_code == 401

    # Valid HMAC-signed request must succeed and register peers
    sig = sign_packet(raw, secret)
    ok_resp = client.post(
        "/mesh/gossip",
        content=raw,
        headers={"X-Mycelium-Signature": sig},
    )
    assert ok_resp.status_code == 200
    data = ok_resp.json()
    assert "https://peer-a.example.com" in data["known_peers"]
    assert "https://peer-b.example.com" in data["known_peers"]

    peers_resp = client.get("/mesh/peers")
    assert peers_resp.status_code == 200
    assert peers_resp.json()["count"] == 2
