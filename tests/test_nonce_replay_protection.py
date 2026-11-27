import hashlib
import hmac
import json
import time

import pytest
from fastapi import HTTPException

from core import spore_vault_sync as svs


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_duplicate_nonce_rejected_before_and_after_restart(tmp_path, monkeypatch):
    secret = "test-strong-secret-key-for-replay-check-123456"
    db_file = tmp_path / "replay_test.db"
    monkeypatch.setenv("MYCELIUM_SECRET_KEY", secret)
    monkeypatch.setenv("MYCELIUM_DB_PATH", str(db_file))
    monkeypatch.setattr(svs, "DB_PATH", str(db_file), raising=False)
    monkeypatch.setattr(svs, "_INITIAL_DB_PATH", None, raising=False)

    conn = svs._get_conn()
    conn.close()

    envelope = {
        "ts": int(time.time()),
        "nonce": "nonce-unique-001",
        "payload": {"spores": []},
    }
    raw = json.dumps(envelope).encode("utf-8")
    sig = _sign(raw, secret)

    assert svs._verify_signed_request(raw, sig) == {"spores": []}

    with pytest.raises(HTTPException) as first_replay:
        svs._verify_signed_request(raw, sig)
    assert first_replay.value.status_code == 401

    monkeypatch.setattr(svs, "_SEEN_GOSSIP_IDS", set(), raising=False)

    with pytest.raises(HTTPException) as post_restart_replay:
        svs._verify_signed_request(raw, sig)
    assert post_restart_replay.value.status_code == 401

    envelope_next = {
        "ts": int(time.time()),
        "nonce": "nonce-unique-002",
        "payload": {"spores": []},
    }
    raw_next = json.dumps(envelope_next).encode("utf-8")
    sig_next = _sign(raw_next, secret)
    assert svs._verify_signed_request(raw_next, sig_next) == {"spores": []}
