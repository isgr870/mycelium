from fastapi import HTTPException, Request
from core.peer_identity import PeerIdentityStore

PEER_STORE = PeerIdentityStore()


def authorize_peer_or_operator(request: Request, raw_body: bytes, hmac_valid: bool) -> str:
    peer_id = request.headers.get("X-Mycelium-Peer-Id", "").strip()
    ed_sig = request.headers.get("X-Mycelium-Ed25519-Sig", "").strip()

    if peer_id or ed_sig:
        ok, reason, peer = PEER_STORE.verify_ed25519(peer_id, raw_body, ed_sig)
        if not ok:
            status_code = 403 if (peer and peer.tier == "quarantined") else 401
            raise HTTPException(status_code=status_code, detail=reason)
        return f"peer:{peer_id}:{peer.tier}"

    if hmac_valid:
        return "operator:hmac"

    raise HTTPException(status_code=401, detail="Unauthorized mesh request.")
