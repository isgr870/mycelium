import os
import time
import json
import asyncio
import httpx
from typing import Dict, Any, List
from fastapi import APIRouter, Request, HTTPException, status
from core.security_hardening import sign_packet, verify_packet

router = APIRouter(prefix="/mesh", tags=["mesh"])

# In-memory registry of reachable WAN/LAN peers: {peer_url: {"last_seen": float, "meta": dict}}
PEER_REGISTRY: Dict[str, Dict[str, Any]] = {}
MAX_CLOCK_SKEW_SECONDS = 60


def get_bootstrap_peers() -> List[str]:
    raw = os.environ.get("MYCELIUM_BOOTSTRAP_PEERS", "").strip()
    if not raw:
        return []
    return [p.strip().rstrip("/") for p in raw.split(",") if p.strip()]


def register_peer(peer_url: str, meta: Dict[str, Any] | None = None) -> None:
    clean = peer_url.strip().rstrip("/")
    if not clean:
        return
    PEER_REGISTRY[clean] = {
        "last_seen": time.time(),
        "meta": meta or {},
    }


def prune_stale_peers(ttl_seconds: int = 300) -> None:
    cutoff = time.time() - ttl_seconds
    stale = [url for url, info in PEER_REGISTRY.items() if info["last_seen"] < cutoff]
    for url in stale:
        PEER_REGISTRY.pop(url, None)


def build_signed_envelope(payload: Dict[str, Any], secret: str) -> bytes:
    body_obj = {
        "ts": int(time.time()),
        "payload": payload,
    }
    return json.dumps(body_obj, separators=(",", ":"), sort_keys=True).encode("utf-8")


@router.get("/peers")
async def list_peers():
    prune_stale_peers()
    return {
        "count": len(PEER_REGISTRY),
        "peers": [
            {"url": url, "last_seen": info["last_seen"], "meta": info["meta"]}
            for url, info in PEER_REGISTRY.items()
        ],
    }


@router.post("/gossip")
async def receive_gossip(request: Request):
    secret = os.environ.get("MYCELIUM_SECRET_KEY", "")
    signature = request.headers.get("X-Mycelium-Signature", "")
    raw_body = await request.body()

    rotate_verifier = globals().get("verify_packet_with_rotation")
    skew_getter = globals().get("get_clock_skew_seconds")
    skew_window = int(skew_getter(MAX_CLOCK_SKEW_SECONDS)) if callable(skew_getter) else MAX_CLOCK_SKEW_SECONDS
    sig_ok = (
        bool(rotate_verifier(raw_body, signature, secret))
        if callable(rotate_verifier)
        else bool(signature and verify_packet(raw_body, signature, secret))
    )
    if not signature or not sig_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing HMAC packet signature.",
        )

    try:
        envelope = json.loads(raw_body.decode("utf-8"))
        ts = int(envelope.get("ts", 0))
        payload = envelope.get("payload", {})
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed gossip JSON envelope.",
        )

    if abs(int(time.time()) - ts) > skew_window:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Gossip packet timestamp outside allowed replay window.",
        )

    sender_url = payload.get("self_url")
    if isinstance(sender_url, str) and sender_url.startswith(("http://", "https://")):
        register_peer(sender_url, {"source": "gossip"})

    for peer_url in payload.get("known_peers", []):
        if isinstance(peer_url, str) and peer_url.startswith(("http://", "https://")):
            register_peer(peer_url, {"source": "peer_exchange"})

    prune_stale_peers()
    return {
        "status": "accepted",
        "known_peers": list(PEER_REGISTRY.keys()),
    }


async def sync_with_bootstrap_peers(self_url: str = "") -> None:
    """Periodically exchanges signed peer lists with configured WAN seed nodes."""
    secret = os.environ.get("MYCELIUM_SECRET_KEY", "")
    for seed in get_bootstrap_peers():
        register_peer(seed, {"source": "bootstrap"})

    while True:
        await asyncio.sleep(15)
        prune_stale_peers()
        targets = list(PEER_REGISTRY.keys())
        if not targets:
            continue

        body = build_signed_envelope(
            {"self_url": self_url, "known_peers": targets},
            secret,
        )
        sig = sign_packet(body, secret)

        async with httpx.AsyncClient(timeout=5.0) as client:
            for peer_url in targets:
                if self_url and peer_url == self_url.rstrip("/"):
                    continue
                try:
                    resp = await client.post(
                        f"{peer_url}/mesh/gossip",
                        content=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Mycelium-Signature": sig,
                        },
                    )
                    if resp.status_code == 200:
                        register_peer(peer_url, {"source": "active_sync"})
                        for discovered in resp.json().get("known_peers", []):
                            if isinstance(discovered, str) and discovered.startswith(("http://", "https://")):
                                register_peer(discovered, {"source": "gossip_discovery"})
                except Exception:
                    pass
