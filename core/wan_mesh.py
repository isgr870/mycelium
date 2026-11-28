import os
import time
import json
import asyncio
import httpx
from typing import Dict, Any, List
from fastapi import APIRouter, Request, HTTPException, status
from core.mycelial_defense import MycelialDefense
from core.security_hardening import sign_packet, verify_packet, verify_packet_with_rotation, get_clock_skew_seconds

router = APIRouter(prefix="/mesh", tags=["mesh"])

# In-memory registry of reachable WAN/LAN peers: {peer_url: {"last_seen": float, "meta": dict}}
PEER_REGISTRY: Dict[str, Dict[str, Any]] = {}
DEFENSE = MycelialDefense(strike_threshold=3, base_quarantine_seconds=30.0, max_quarantine_seconds=900.0, recovery_healthy_streak=3)
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
        peer_hint = request.client.host if request.client else "unknown-peer"
        DEFENSE.record_violation(peer_hint, "invalid_hmac")
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

    local_self_url = (
        os.environ.get("MYCELIUM_PUBLIC_URL") or os.environ.get("MYCELIUM_SELF_URL") or ""
    ).strip().rstrip("/")

    sender_url = payload.get("self_url")
    if isinstance(sender_url, str):
        clean_sender = sender_url.strip().rstrip("/")
        if clean_sender.startswith(("http://", "https://")) and clean_sender != local_self_url:
            register_peer(clean_sender, {"source": "gossip"})

    for peer_url in payload.get("known_peers", []):
        if isinstance(peer_url, str):
            clean_peer = peer_url.strip().rstrip("/")
            if clean_peer.startswith(("http://", "https://")) and clean_peer != local_self_url:
                register_peer(clean_peer, {"source": "peer_exchange"})

    for q_peer in payload.get("quarantined_peers", []):
        if isinstance(q_peer, str) and q_peer.strip():
            DEFENSE.record_violation(q_peer.strip(), "mesh_alarm_advisory")
    if isinstance(sender_url, str) and sender_url.strip():
        DEFENSE.record_healthy(sender_url.strip())

    prune_stale_peers()
    return {
        "status": "accepted",
        "known_peers": list(PEER_REGISTRY.keys()),
    }


async def sync_with_bootstrap_peers(self_url: str = "") -> None:
    """Periodically exchanges signed peer lists with configured WAN seed nodes."""
    clean_self = (self_url or "").strip().rstrip("/")
    for seed in get_bootstrap_peers():
        clean_seed = seed.strip().rstrip("/")
        if clean_seed and clean_seed != clean_self:
            register_peer(clean_seed, {"source": "bootstrap"})

    while True:
        await asyncio.sleep(15)
        prune_stale_peers()
        secret = os.environ.get("MYCELIUM_SECRET_KEY", "")
        timeout_sec = float(os.environ.get("MYCELIUM_GOSSIP_TIMEOUT", "5.0"))
        targets = [
            u for u in DEFENSE.route_peers(list(PEER_REGISTRY.keys()))
            if not clean_self or u.rstrip("/") != clean_self
        ]
        if not targets:
            continue

        body = build_signed_envelope(
            {"self_url": clean_self, "known_peers": targets},
            secret,
        )
        sig = sign_packet(body, secret)

        async with httpx.AsyncClient(timeout=timeout_sec) as client:
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
                            if isinstance(discovered, str):
                                clean_disc = discovered.strip().rstrip("/")
                                if clean_disc.startswith(("http://", "https://")) and clean_disc != clean_self:
                                    register_peer(clean_disc, {"source": "gossip_discovery"})
                except Exception:
                    pass


from core.peer_identity import PeerIdentityStore

PEER_STORE = PeerIdentityStore()


def verify_peer_or_hmac(request: Request, raw_body: bytes, hmac_signature: str) -> str:
    peer_id = request.headers.get("X-Mycelium-Peer-Id", "").strip()
    ed25519_sig = request.headers.get("X-Mycelium-Ed25519-Sig", "").strip()

    if peer_id or ed25519_sig:
        if not peer_id or not ed25519_sig:
            raise HTTPException(
                status_code=401,
                detail="Both X-Mycelium-Peer-Id and X-Mycelium-Ed25519-Sig are required.",
            )
        ok, reason, peer = PEER_STORE.verify_request(peer_id, raw_body, ed25519_sig)
        if not ok:
            status_code = 403 if (peer and peer.tier == "quarantined") else 401
            raise HTTPException(status_code=status_code, detail=reason)
        return f"ed25519:{peer_id}:{peer.tier}"

    return "hmac:operator"


@router.post("/gossip/tick")
async def mesh_gossip_tick_alias(request: Request):
    return await receive_gossip(request)
