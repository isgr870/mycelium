import hashlib
import hmac
import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import wan_mesh


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_wan_gossip_accepts_secondary_key_and_custom_skew(monkeypatch):
    primary = "primary-wan-secret-key-1234567890"
    secondary = "secondary-wan-secret-key-1234567890"

    monkeypatch.setenv("MYCELIUM_SECRET_KEY", primary)
    monkeypatch.setenv("MYCELIUM_SECONDARY_SECRET_KEY", secondary)
    monkeypatch.setenv("MYCELIUM_MAX_CLOCK_SKEW_SECONDS", "240")

    app = FastAPI()
    app.include_router(wan_mesh.router)
    client = TestClient(app)

    env = {
        "ts": int(time.time()) - 150,
        "payload": {"self_url": "https://ug-node-01.example.mesh"},
    }
    raw = json.dumps(env, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = _sign(raw, secondary)

    resp = client.post(
        "/mesh/gossip",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Mycelium-Signature": sig,
        },
    )
    assert resp.status_code == 200
