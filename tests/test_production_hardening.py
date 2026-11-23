import pytest
from core.security_hardening import (
    validate_production_environment,
    SlidingWindowRateLimiter,
    sign_packet,
    verify_packet,
    init_wal_sqlite,
)


def test_fail_closed_on_missing_or_weak_secret(monkeypatch):
    monkeypatch.delenv("MYCELIUM_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        validate_production_environment(strict=False)

    monkeypatch.setenv("MYCELIUM_SECRET_KEY", "test-secret-key")
    with pytest.raises(RuntimeError):
        validate_production_environment(strict=False)


def test_accepts_strong_secret(monkeypatch):
    strong = "a" * 64
    monkeypatch.setenv("MYCELIUM_SECRET_KEY", strong)
    assert validate_production_environment(strict=False) == strong


def test_rate_limiter_enforces_window():
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
    assert limiter.allow("peer_1") is True
    assert limiter.allow("peer_1") is True
    assert limiter.allow("peer_1") is True
    assert limiter.allow("peer_1") is False
    assert limiter.allow("peer_2") is True


def test_hmac_packet_signing_and_tamper_rejection():
    secret = "b" * 64
    payload = b'{"node":"spore_alpha","msg":"hello"}'
    sig = sign_packet(payload, secret)
    assert verify_packet(payload, sig, secret) is True
    assert verify_packet(b'{"node":"spore_alpha","msg":"tampered"}', sig, secret) is False


def test_sqlite_wal_mode_enabled(tmp_path):
    db_file = str(tmp_path / "test_wal.db")
    conn = init_wal_sqlite(db_file)
    mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    conn.close()
    assert mode.lower() == "wal"
