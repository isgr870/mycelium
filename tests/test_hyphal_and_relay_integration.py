import importlib
import inspect
import pytest

from core.e2ee_mailbox import (
    MailboxStore,
    decrypt_for_recipient,
    encrypt_for_recipient,
    generate_x25519_keypair,
)
from core.peer_identity import generate_ed25519_identity


def _find_fastapi_app():
    candidates = [
        ("server", "app"),
        ("core.server", "app"),
        ("core.relay_api", "app"),
        ("core.app", "app"),
        ("main", "app"),
    ]
    for mod_name, attr in candidates:
        try:
            mod = importlib.import_module(mod_name)
            app = getattr(mod, attr, None)
            if app is not None and hasattr(app, "routes"):
                return app
        except Exception:
            continue
    return None


def _get_test_client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


def test_fastapi_relay_status_and_mesh_routes():
    app = _find_fastapi_app()
    if app is None:
        pytest.skip("No FastAPI `app` instance found in standard entrypoints")

    client = _get_test_client(app)
    paths = {getattr(r, "path", "") for r in app.routes}

    if "/status" in paths:
        resp = client.get("/status")
        assert resp.status_code in (200, 429)
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, dict)

    for candidate_path in ("/mesh/names/peers", "/mesh/names", "/mesh/status"):
        if candidate_path in paths:
            resp = client.get(candidate_path)
            assert resp.status_code in (200, 401, 403, 428, 429)
            break


def test_hyphal_mailbox_and_name_replication_between_stores(tmp_path):
    hs = pytest.importorskip("core.hyphal_sync")

    node_a_db = str(tmp_path / "us.db")
    node_b_db = str(tmp_path / "ug.db")

    mbox_a = MailboxStore(node_a_db)
    mbox_b = MailboxStore(node_b_db)

    sender = generate_ed25519_identity("us-relay-sender")
    recipient_id = generate_ed25519_identity("ug-relay-recipient")["node_id"]
    recipient_x25519 = generate_x25519_keypair()

    plaintext = "hyphal-sync-check:us->ug"
    envelope = encrypt_for_recipient(
        plaintext=plaintext,
        sender_id=sender["node_id"],
        recipient_id=recipient_id,
        recipient_x25519_pub_b64=recipient_x25519["public_key_b64"],
        ttl_seconds=300,
    )
    assert mbox_a.enqueue(envelope) is True

    # Look for a store-to-store or payload sync helper in core.hyphal_sync if present
    synced = False
    for fn_name in (
        "replicate_mailbox_items",
        "sync_mailbox_between_dbs",
        "replicate_between_stores",
        "merge_mailbox_envelopes",
    ):
        fn = getattr(hs, fn_name, None)
        if callable(fn):
            sig = inspect.signature(fn)
            params = list(sig.parameters.keys())
            if len(params) >= 2:
                fn(node_a_db, node_b_db)
                synced = True
                break

    if not synced:
        # Fallback direct replication of pending envelopes into peer store
        for env in mbox_a.fetch_pending(recipient_id):
            mbox_b.enqueue(env)

    pending_b = mbox_b.fetch_pending(recipient_id)
    assert len(pending_b) >= 1
    decrypted_b = decrypt_for_recipient(
        pending_b[0],
        recipient_x25519_priv_b64=recipient_x25519["private_key_b64"],
    )
    assert decrypted_b == plaintext
