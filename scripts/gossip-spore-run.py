#!/usr/bin/env python3
import argparse
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def load_env_secret() -> str:
    env_val = os.environ.get("MYCELIUM_SECRET_KEY", "").strip()
    if env_val:
        return env_val
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("MYCELIUM_SECRET_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def sign_packet(raw_body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def post_json(url: str, secret: str, data: dict, retries: int = 3) -> tuple[int, str]:
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = sign_packet(raw, secret)
    last_err = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            url,
            data=raw,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Mycelium-Signature": sig,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last_err = exc
            time.sleep(0.15 * attempt)
    raise RuntimeError(f"{url} failed: {last_err}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="http://127.0.0.1:8082")
    ap.add_argument("--target", default="http://127.0.0.1:8081")
    ap.add_argument("--secret", default="")
    ap.add_argument("--spores", type=int, default=5)
    args = ap.parse_args()

    secret = args.secret.strip() or load_env_secret()
    if not secret:
        raise SystemExit("Missing MYCELIUM_SECRET_KEY: set in .env, env, or --secret")

    now_i = int(time.time())
    gossip_payload = {
        "ts": now_i,
        "nonce": uuid.uuid4().hex,
        "peers": [{"url": args.source, "role": "relay", "capabilities": ["general", "sync", "relay"]}],
    }
    g_code, g_body = post_json(f"{args.target}/mesh/gossip", secret, gossip_payload)
    print(f"GOSSIP status={g_code} body={g_body}")

    for i in range(args.spores):
        spore_ts = int(time.time())
        spore = {
            "topic": "mesh.test",
            "content": {
                "seq": i,
                "from": args.source,
                "digest": hashlib.sha256(f"termux-{time.time_ns()}-{i}".encode()).hexdigest()[:16],
                "ts": spore_ts,
            },
            "author_node": "termux-local-node",
        }
        envelope = {
            "ts": spore_ts,
            "nonce": uuid.uuid4().hex,
            "payload": {"spores": [spore]},
        }
        p_code, p_body = post_json(f"{args.target}/mesh/spores/push", secret, envelope)
        print(f"SPORE[{i}] status={p_code} body={p_body}")

    with urllib.request.urlopen(f"{args.target}/mesh/spores/manifest", timeout=5) as r:
        print(f"MANIFEST status={r.status} body={r.read().decode('utf-8', errors='replace')}")


if __name__ == "__main__":
    main()
