import inspect
import os

from core.chunk_store import ChunkStore, sha256_hex
from core.e2ee_mailbox import (
    MailboxStore,
    decrypt_for_recipient,
    encrypt_for_recipient,
    generate_x25519_keypair,
)
from core.edge_defense import DEFAULT_TIER_LIMITS, EdgeQuotaEngine, compute_pow_nonce, verify_pow_token
from core.peer_identity import generate_ed25519_identity


def _extract_msg_id(env: dict) -> str:
    for key in ("message_id", "msg_id", "id", "envelope_id"):
        val = env.get(key)
        if val:
            return str(val)
    raise AssertionError(f"Could not find message id in envelope keys: {list(env.keys())}")


def _ack_envelope(mbox: MailboxStore, msg_id: str, recipient_id: str) -> bool:
    sig = inspect.signature(mbox.ack)
    params = [
        p for p in sig.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    if len(params) >= 2:
        return bool(mbox.ack(msg_id, recipient_id))
    return bool(mbox.ack(msg_id))


def test_e2ee_mailbox_roundtrip_and_ack(tmp_path):
    sender = generate_ed25519_identity("test-sender")
    recipient_id = generate_ed25519_identity("test-recipient")["node_id"]
    recipient_x25519 = generate_x25519_keypair()

    mbox = MailboxStore(str(tmp_path / "mailbox.db"))
    plaintext = "hyphal-e2ee-payload:kampala-node-01"

    envelope = encrypt_for_recipient(
        plaintext=plaintext,
        sender_id=sender["node_id"],
        recipient_id=recipient_id,
        recipient_x25519_pub_b64=recipient_x25519["public_key_b64"],
        ttl_seconds=300,
    )
    assert mbox.enqueue(envelope) is True

    pending = mbox.fetch_pending(recipient_id)
    assert len(pending) == 1

    decrypted = decrypt_for_recipient(
        pending[0],
        recipient_x25519_priv_b64=recipient_x25519["private_key_b64"],
    )
    assert decrypted == plaintext

    msg_id = _extract_msg_id(pending[0])
    assert _ack_envelope(mbox, msg_id, recipient_id) is True
    assert mbox.fetch_pending(recipient_id) == []


def test_sha256_chunk_store_reassembly_and_budget(tmp_path):
    store = ChunkStore(str(tmp_path / "blobs"), chunk_size=128, max_bytes=256)
    payload_a = os.urandom(200)
    manifest_a = store.build_manifest_from_bytes(payload_a, filename="pinned.bin", pinned=True)
    assert manifest_a["chunk_count"] == 2
    assert store.missing_chunks(manifest_a) == []
    reassembled_a = store.reassemble_bytes(manifest_a)
    assert reassembled_a == payload_a
    assert sha256_hex(reassembled_a) == sha256_hex(payload_a)

    payload_b = os.urandom(256)
    manifest_b = store.build_manifest_from_bytes(payload_b, filename="unpinned.bin", pinned=False)
    assert store.disk_usage_bytes() <= 256
    for ch in manifest_a["chunks"]:
        assert store.has_chunk(ch)
        assert store.is_pinned(ch)

    mh = manifest_b["manifest_hash"]
    assert isinstance(mh, str) and len(mh) == 64
    int(mh, 16)
    assert len(sha256_hex(payload_b)) == 64


def test_naming_pow_verification():
    subject = "kampala-relay.mycelium:node123abc"
    bits = 10
    nonce, digest = compute_pow_nonce(subject, difficulty_bits=bits)
    token = f"{nonce}:{digest}"
    assert verify_pow_token(subject, token, difficulty_bits=bits) is True
    assert verify_pow_token(subject, "0:0000", difficulty_bits=bits) is False
    assert verify_pow_token("other-subject", token, difficulty_bits=bits) is False


def test_edge_quota_enforcement(tmp_path):
    now = 1_795_854_500.0
    engine = EdgeQuotaEngine(db_path=str(tmp_path / "edge_quota.db"))
    peer = "peer-quota-test"

    assert engine.effective_tier(peer, base_tier="external", now=now) == "external"

    # Byte budget for external tier is 1,048,576 bytes per window
    byte_cap = DEFAULT_TIER_LIMITS["external"]["max_bytes"]
    allowed, reason, _ = engine.consume_quota(peer, payload_bytes=byte_cap // 2, base_tier="external", now=now)
    assert allowed is True

    denied, reason, _ = engine.consume_quota(peer, payload_bytes=byte_cap, base_tier="external", now=now + 1)
    assert denied is False
    assert isinstance(reason, str) and len(reason) > 0

    # Escalate strikes up to external max_strikes (3) -> quarantined tier
    max_strikes = DEFAULT_TIER_LIMITS["external"]["max_strikes"]
    tier_after_strikes = "external"
    for i in range(max_strikes):
        _, tier_after_strikes = engine.record_strike(
            peer, base_tier="external", quarantine_sec=300.0, now=now + 2 + i
        )

    assert tier_after_strikes == "quarantined"
    assert engine.effective_tier(peer, base_tier="external", now=now + 10) == "quarantined"

    q_allowed, _, _ = engine.consume_quota(peer, payload_bytes=64, base_tier="external", now=now + 10)
    assert q_allowed is False
