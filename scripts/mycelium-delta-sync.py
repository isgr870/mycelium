#!/usr/bin/env python3
import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.peer_identity import sign_ed25519_b64


def load_env_secret() -> str:
    env_val = os.environ.get("MYCELIUM_SECRET_KEY", "").strip()
    if env_val:
        return env_val
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("MYCELIUM_SECRET_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def sign_hmac_packet(raw_body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def build_auth_headers(
    raw: bytes,
    secret: str,
    peer_id: str = "",
    ed25519_privkey: str = "",
) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Mycelium-Signature"] = sign_hmac_packet(raw, secret)
    if peer_id and ed25519_privkey:
        headers["X-Mycelium-Peer-Id"] = peer_id
        headers["X-Mycelium-Ed25519-Sig"] = sign_ed25519_b64(ed25519_privkey, raw)
    return headers


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def post_signed(
    url: str,
    secret: str,
    data: dict,
    peer_id: str = "",
    ed25519_privkey: str = "",
    retries: int = 3,
) -> tuple[int, dict]:
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = build_auth_headers(raw, secret, peer_id=peer_id, ed25519_privkey=ed25519_privkey)
    last_err = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, data=raw, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                body = r.read().decode("utf-8")
                return r.status, json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(detail)
            except Exception:
                parsed = {"raw": detail}
            return e.code, parsed
        except Exception as exc:
            last_err = exc
            time.sleep(0.15 * attempt)
    raise RuntimeError(f"{url} failed after {retries} retries: {last_err}")


def sync_one_way(
    src_url: str,
    dst_url: str,
    secret: str,
    peer_id: str = "",
    ed25519_privkey: str = "",
) -> int:
    src = src_url.rstrip("/")
    dst = dst_url.rstrip("/")

    dst_manifest = get_json(f"{dst}/mesh/spores/manifest")
    bloom = dst_manifest.get("bloom", {})

    pull_env = {
        "ts": int(time.time()),
        "nonce": uuid.uuid4().hex,
        "payload": {
            "bit_array": bloom.get("bit_array", []),
            "size": bloom.get("size", 512),
            "hash_count": bloom.get("hash_count", 3),
        },
    }
    p_code, p_res = post_signed(
        f"{src}/mesh/spores/pull",
        secret,
        pull_env,
        peer_id=peer_id,
        ed25519_privkey=ed25519_privkey,
    )
    if p_code != 200:
        raise RuntimeError(f"Pull from {src} failed ({p_code}): {p_res}")

    missing = p_res.get("spores", [])
    if not missing:
        return 0

    normalized = [
        {
            "topic": s.get("topic", "general"),
            "content": s.get("content", ""),
            "author_node": s.get("author_node", "mesh-sync"),
        }
        for s in missing
        if isinstance(s, dict)
    ]

    push_env = {
        "ts": int(time.time()),
        "nonce": uuid.uuid4().hex,
        "payload": {"spores": normalized},
    }
    u_code, u_res = post_signed(
        f"{dst}/mesh/spores/push",
        secret,
        push_env,
        peer_id=peer_id,
        ed25519_privkey=ed25519_privkey,
    )
    if u_code != 200:
        raise RuntimeError(f"Push to {dst} failed ({u_code}): {u_res}")

    return int(u_res.get("accepted_count", len(normalized)))


def main() -> None:
    ap = argparse.ArgumentParser(description="Bidirectional Bloom spore delta sync")
    ap.add_argument("--node-a", default="http://127.0.0.1:8081")
    ap.add_argument("--node-b", default="http://127.0.0.1:8082")
    ap.add_argument("--secret", default="")
    ap.add_argument("--peer-id", default="")
    ap.add_argument("--ed25519-privkey", default="")
    args = ap.parse_args()

    secret = args.secret.strip() or load_env_secret()
    peer_id = args.peer_id.strip() or os.environ.get("MYCELIUM_PEER_ID", "").strip()
    ed25519_privkey = (
        args.ed25519_privkey.strip() or os.environ.get("MYCELIUM_ED25519_PRIVKEY_B64", "").strip()
    )

    if (peer_id and not ed25519_privkey) or (ed25519_privkey and not peer_id):
        raise SystemExit("Provide both --peer-id and --ed25519-privkey (or both env vars)")

    if not secret and not (peer_id and ed25519_privkey):
        raise SystemExit("Provide MYCELIUM_SECRET_KEY or an Ed25519 peer identity")

    a_to_b = sync_one_way(
        args.node_a,
        args.node_b,
        secret,
        peer_id=peer_id,
        ed25519_privkey=ed25519_privkey,
    )
    b_to_a = sync_one_way(
        args.node_b,
        args.node_a,
        secret,
        peer_id=peer_id,
        ed25519_privkey=ed25519_privkey,
    )

    m_a = get_json(f"{args.node_a.rstrip('/')}/mesh/spores/manifest")
    m_b = get_json(f"{args.node_b.rstrip('/')}/mesh/spores/manifest")

    mode = "hmac+ed25519" if (secret and peer_id) else ("ed25519" if peer_id else "hmac")
    print(
        f"SYNC_DONE mode={mode} a_to_b={a_to_b} b_to_a={b_to_a} "
        f"count_a={m_a.get('count', 0)} count_b={m_b.get('count', 0)}"
    )


if __name__ == "__main__":
    main()
