#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.peer_identity import PeerIdentityStore, generate_ed25519_identity, sign_ed25519_b64


def load_secret() -> str:
    val = os.environ.get("MYCELIUM_SECRET_KEY", "").strip()
    if val:
        return val
    env_p = REPO_ROOT / ".env"
    if env_p.exists():
        for line in env_p.read_text(encoding="utf-8").splitlines():
            if line.startswith("MYCELIUM_SECRET_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def signed_post(url: str, payload: dict, secret: str, peer: dict | None = None) -> tuple[int, str]:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Mycelium-Signature"] = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    if peer:
        headers["X-Mycelium-Peer-Id"] = peer["node_id"]
        headers["X-Mycelium-Ed25519-Sig"] = sign_ed25519_b64(peer["private_key_b64"], raw)
    req = urllib.request.Request(url, data=raw, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def main() -> None:
    prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    trust_path = os.environ.get("MYCELIUM_TRUST_REGISTRY", str(Path(prefix) / "tmp/mycelium_regions/peers_trust.json"))
    secret = load_secret()

    store = PeerIdentityStore(registry_path=trust_path)
    ext_peer = generate_ed25519_identity("external-quota-probe")
    store.upsert_peer(ext_peer["node_id"], ext_peer["public_key_b64"], tier="external", label=ext_peer["label"])

    print("=== 1. EXTERNAL TIER PUSH BURST (8101) ===")
    status_hist = []
    for i in range(12):
        now_i = int(time.time())
        env = {
            "ts": now_i,
            "nonce": uuid.uuid4().hex,
            "payload": {
                "spores": [
                    {
                        "topic": "mesh.quota.test",
                        "content": {"seq": i, "probe": "external-burst"},
                        "author_node": ext_peer["node_id"],
                    }
                ]
            },
        }
        code, body = signed_post("http://127.0.0.1:8101/mesh/spores/push", env, secret, peer=ext_peer)
        status_hist.append(code)
        if i in (0, 1, 5, 11) or code not in (200, 201):
            print(f"  burst[{i:02d}] -> HTTP {code}: {body[:140]}")
    print("  status_histogram:", {c: status_hist.count(c) for c in sorted(set(status_hist))})

    print("\n=== 2. GOSSIP & GOSSIP/TICK ACROSS REGIONS (8101 -> 8102 -> 8103) ===")
    gossip_id = f"gossip-{uuid.uuid4().hex[:10]}"
    now_i = int(time.time())
    gossip_env = {
        "ts": now_i,
        "nonce": uuid.uuid4().hex,
        "payload": {
            "gossip_id": gossip_id,
            "ttl": 4,
            "hop": 0,
            "fanout": 6,
            "active_forward": False,
            "origin": "ug-kampala",
            "topic": "mesh.gossip.verify",
        },
    }
    for ep in ("/mesh/gossip", "/mesh/gossip/tick"):
        for port in (8101, 8102, 8103):
            code, body = signed_post(f"http://127.0.0.1:{port}{ep}", gossip_env, secret, peer=ext_peer)
            print(f"  {port}{ep} -> HTTP {code}: {body[:160]}")


if __name__ == "__main__":
    main()
