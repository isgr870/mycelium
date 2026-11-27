import hashlib
import hmac
import json
import time

import pytest
from fastapi import HTTPException

from core import spore_vault_sync as svs
from core.security_hardening import get_clock_skew_seconds, verify_packet_with_rotation


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_dual_key_rotation_accepts_secondary_and_rejects_unknown(monkeypatch):
    primary = "primary-secret-key-alpha-1234567890"
    secondary = "secondary-secret-key-beta-1234567890"
    unknown = "unrelated-secret-key-gamma-1234567890"

    monkeypatch.setenv("MYCELIUM_SECRET_KEY", primary)
    monkeypatch.setenv("MYCELIUM_SECONDARY_SECRET_KEY", secondary)

    body = b'{"ts": 1700000000, "nonce": "n-1", "payload": {}}'
    sig_secondary = _sign(body, secondary)
    sig_unknown = _sign(body, unknown)

    assert verify_packet_with_rotation(body, sig_secondary) is True
    assert verify_packet_with_rotation(body, sig_unknown) is False


def test_configurable_clock_skew_respected_in_spore_verify(tmp_path, monkeypatch):
    secret = "active-secret-key-for-skew-test-123456"
    db_file = tmp_path / "skew_test.db"
    monkeypatch.setenv("MYCELIUM_SECRET_KEY", secret)
    monkeypatch.setenv("MYCELIUM_DB_PATH", str(db_file))
    monkeypatch.setattr(svs, "DB_PATH", str(db_file), raising=False)
    monkeypatch.setattr(svs, "_INITIAL_DB_PATH", None, raising=False)

    # Set custom skew window to 300s
    monkeypatch.setenv("MYCELIUM_MAX_CLOCK_SKEW_SECONDS", "300")
    assert get_clock_skew_seconds(120) == 300

    # Timestamp 180s in the past (outside old 120s default, inside new 300s window)
    skewed_env = {
        "ts": int(time.time()) - 180,
        "nonce": "skew-ok-nonce-1",
        "payload": {"spores": []},
    }
    raw = json.dumps(skewed_env).encode("utf-8")
    sig = _sign(raw, secret)

    assert svs._verify_signed_request(raw, sig) == {"spores": []}

    # Timestamp 400s in the past fails even with 300s skew
    too_old_env = {
        "ts": int(time.time()) - 400,
        "nonce": "skew-too-old-nonce-2",
        "payload": {"spores": []},
    }
    raw_old = json.dumps(too_old_env).encode("utf-8")
    sig_old = _sign(raw_old, secret)

    with pytest.raises(HTTPException) as exc_info:
        svs._verify_signed_request(raw_old, sig_old)
    assert exc_info.value.status_code == 401
