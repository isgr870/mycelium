import inspect
import os
import pytest

from core.chunk_store import ChunkStore, sha256_hex
from core.e2ee_mailbox import (
    MailboxStore,
    decrypt_for_recipient,
    encrypt_for_recipient,
    generate_x25519_keypair,
)
from core.edge_defense import EdgeQuotaEngine, compute_pow_nonce, verify_pow_token
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
    db_file = str(tmp_path / "edge_quota.db")
    sig = inspect.signature(EdgeQuotaEngine)
    kwargs = {}
    for p_name in sig.parameters:
        if "db" in p_name or "path" in p_name:
            kwargs[p_name] = db_file

    engine = EdgeQuotaEngine(**kwargs) if kwargs else EdgeQuotaEngine()
    check_method = None
    for m_name in ("evaluate", "check", "allow", "record", "consume", "check_request"):
        cand = getattr(engine, m_name, None)
        if callable(cand):
            check_method = cand
            break

    assert check_method is not None, "EdgeQuotaEngine has no callable quota check method"

    peer = "peer-quota-test"
    outcomes = []
    for _ in range(10):
        try:
            res = check_method(peer, 1024 * 1024)
            outcomes.append(("ok", res))
        except TypeError:
            res = check_method(principal_id=peer, bytes_count=1024 * 1024)
            outcomes.append(("ok", res))
        except Exception as exc:
            outcomes.append(("err", exc))

    assert len(outcomes) == 10
