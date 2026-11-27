import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization


TIER_POLICY: Dict[str, Dict[str, int]] = {
    "operator": {"max_body_bytes": 2_097_152, "rate_per_min": 1200},
    "external": {"max_body_bytes": 65_536, "rate_per_min": 120},
    "quarantined": {"max_body_bytes": 0, "rate_per_min": 0},
}


@dataclass
class PeerIdentity:
    node_id: str
    public_key_b64: str
    tier: str = "external"
    strikes: int = 0
    label: str = ""


def generate_ed25519_identity(label: str = "") -> Dict[str, str]:
    priv = Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    priv_raw = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    node_id = hashlib.sha256(pub_raw).hexdigest()[:24]
    return {
        "label": label or node_id,
        "node_id": node_id,
        "public_key_b64": base64.b64encode(pub_raw).decode("ascii"),
        "private_key_b64": base64.b64encode(priv_raw).decode("ascii"),
    }


def sign_ed25519_b64(private_key_b64: str, raw_body: bytes) -> str:
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64, validate=True))
    return base64.b64encode(priv.sign(raw_body)).decode("ascii")


class PeerIdentityStore:
    def __init__(self, registry_path: Optional[str] = None, strike_threshold: int = 3):
        prefix = os.environ.get("PREFIX", "")
        default_path = (
            os.path.join(prefix, "tmp/mycelium_stage/peers_trust.json")
            if prefix
            else "./peers_trust.json"
        )
        self.path = Path(registry_path or os.environ.get("MYCELIUM_TRUST_REGISTRY", default_path))
        self.strike_threshold = strike_threshold
        self._peers: Dict[str, PeerIdentity] = {}
        self._window_hits: Dict[str, list[float]] = {}
        self.reload()

    def reload(self) -> None:
        self._peers.clear()
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        for nid, rec in data.get("peers", {}).items():
            self._peers[nid] = PeerIdentity(
                node_id=nid,
                public_key_b64=rec["public_key_b64"],
                tier=rec.get("tier", "external"),
                strikes=int(rec.get("strikes", 0)),
                label=rec.get("label", nid),
            )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "peers": {
                nid: {
                    "label": p.label,
                    "public_key_b64": p.public_key_b64,
                    "tier": p.tier,
                    "strikes": p.strikes,
                }
                for nid, p in sorted(self._peers.items())
            }
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def upsert_peer(self, node_id: str, public_key_b64: str, tier: str = "external", label: str = "") -> PeerIdentity:
        if tier not in TIER_POLICY:
            raise ValueError(f"Invalid trust tier: {tier}")
        existing = self._peers.get(node_id)
        peer = PeerIdentity(
            node_id=node_id,
            public_key_b64=public_key_b64,
            tier=tier,
            strikes=0 if tier == "operator" else (existing.strikes if existing else 0),
            label=label or (existing.label if existing else node_id),
        )
        self._peers[node_id] = peer
        self.save()
        return peer

    def record_strike(self, node_id: str, now: Optional[float] = None) -> str:
        peer = self._peers.get(node_id)
        if not peer:
            return "unknown"
        peer.strikes += 1
        if peer.strikes >= self.strike_threshold:
            peer.tier = "quarantined"
        self.save()
        return peer.tier

    def check_quota(self, peer: PeerIdentity, payload_bytes: int, now: Optional[float] = None) -> Tuple[bool, str]:
        pol = TIER_POLICY.get(peer.tier, TIER_POLICY["quarantined"])
        if peer.tier == "quarantined" or pol["rate_per_min"] <= 0:
            return False, "Peer is quarantined."
        if payload_bytes > pol["max_body_bytes"]:
            return False, f"Payload exceeds {peer.tier} limit ({pol['max_body_bytes']} bytes)."

        ts = now if now is not None else time.time()
        hits = [t for t in self._window_hits.get(peer.node_id, []) if ts - t < 60.0]
        if len(hits) >= pol["rate_per_min"]:
            self._window_hits[peer.node_id] = hits
            return False, f"Rate limit exceeded for tier={peer.tier}."
        hits.append(ts)
        self._window_hits[peer.node_id] = hits
        return True, "ok"

    def verify_request(
        self,
        node_id: str,
        raw_body: bytes,
        sig_b64: str,
        now: Optional[float] = None,
    ) -> Tuple[bool, str, Optional[PeerIdentity]]:
        peer = self._peers.get(node_id)
        if not peer:
            return False, "Unknown Ed25519 peer identity.", None
        if peer.tier == "quarantined":
            return False, "Peer is quarantined.", peer

        try:
            pub_raw = base64.b64decode(peer.public_key_b64, validate=True)
            derived_id = hashlib.sha256(pub_raw).hexdigest()[:24]
            if derived_id != node_id:
                tier = self.record_strike(node_id, now=now)
                return False, f"Peer node_id mismatch (tier={tier}).", peer
            pub_key = Ed25519PublicKey.from_public_bytes(pub_raw)
            sig_raw = base64.b64decode(sig_b64, validate=True)
            pub_key.verify(sig_raw, raw_body)
        except (InvalidSignature, ValueError, Exception):
            tier = self.record_strike(node_id, now=now)
            return False, f"Invalid Ed25519 signature (tier={tier}).", peer

        ok, reason = self.check_quota(peer, len(raw_body), now=now)
        if not ok:
            return False, reason, peer
        return True, "ok", peer
