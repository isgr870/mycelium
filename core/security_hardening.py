import os
import sys
import time
import hmac
import hashlib
import sqlite3
from collections import defaultdict, deque
from typing import Deque, Dict, Optional
from fastapi import Request, WebSocket, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware

WEAK_DEFAULTS = {
    "",
    "test-secret-key",
    "secret",
    "changeme",
    "CHANGE_ME_GENERATE_64_CHAR_HEX_SECRET",
}


def validate_production_environment(strict: bool = True) -> str:
    """
    Enforces fail-closed startup policy.
    Rejects missing, weak, or default MYCELIUM_SECRET_KEY values.
    """
    secret = os.environ.get("MYCELIUM_SECRET_KEY", "").strip()
    if secret in WEAK_DEFAULTS or len(secret) < 24:
        msg = (
            "[FATAL SECURITY POLICY] MYCELIUM_SECRET_KEY is missing, weak, or using a default placeholder.\n"
            "Generate a strong key with: export MYCELIUM_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')"
        )
        if strict:
            print(msg, file=sys.stderr)
            sys.exit(1)
        raise RuntimeError(msg)
    return secret


class SlidingWindowRateLimiter:
    """In-memory sliding window rate limiter for HTTP and WebSocket peers."""

    def __init__(self, max_requests: int = 120, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        bucket = self._hits[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.max_requests:
            return False
        bucket.append(now)
        return True


class PayloadAndRateLimitMiddleware(BaseHTTPMiddleware):
    """Rejects oversized HTTP bodies (413) and flood requests (429)."""

    def __init__(self, app, max_bytes: int = 65536, rate_per_min: int = 120):
        super().__init__(app)
        self.max_bytes = max_bytes
        self.limiter = SlidingWindowRateLimiter(max_requests=rate_per_min, window_seconds=60)

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        if not self.limiter.allow(client_ip):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Slow down mesh requests.",
            )

        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Payload exceeds maximum allowed {self.max_bytes} bytes.",
            )

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


class WebSocketGuard:
    """Guards WebSocket connections against message flooding and oversized frames."""

    def __init__(self, max_bytes: int = 65536, rate_per_min: int = 240):
        self.max_bytes = max_bytes
        self.limiter = SlidingWindowRateLimiter(max_requests=rate_per_min, window_seconds=60)

    async def verify_frame(self, ws: WebSocket, raw_data: str, peer_id: Optional[str] = None) -> bool:
        identity = peer_id or (ws.client.host if ws.client else "unknown")
        if len(raw_data.encode("utf-8")) > self.max_bytes:
            await ws.close(code=1009, reason="Payload too large")
            return False
        if not self.limiter.allow(identity):
            await ws.close(code=1008, reason="Rate limit exceeded")
            return False
        return True


def sign_packet(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_packet(payload: bytes, signature: str, secret: str) -> bool:
    expected = sign_packet(payload, secret)
    return hmac.compare_digest(expected, signature)


def init_wal_sqlite(db_path: str) -> sqlite3.Connection:
    """Opens SQLite with WAL mode and busy timeout for safe concurrent mesh writes."""
    conn = sqlite3.connect(db_path, timeout=15.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=15000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


# --- Non-breaking key rotation & clock skew helpers ---
def get_clock_skew_seconds(default: int = 120) -> int:
    raw = os.environ.get("MYCELIUM_MAX_CLOCK_SKEW_SECONDS", "").strip()
    if not raw:
        return default
    try:
        val = int(raw)
    except ValueError:
        return default
    return max(5, min(3600, val))


def get_signing_secrets(primary_secret: Optional[str] = None) -> list[str]:
    secrets_list: list[str] = []
    primary = (
        primary_secret
        if primary_secret is not None
        else os.environ.get("MYCELIUM_SECRET_KEY", "")
    ).strip()
    if primary:
        secrets_list.append(primary)

    secondary = os.environ.get("MYCELIUM_SECONDARY_SECRET_KEY", "").strip()
    if secondary and secondary not in secrets_list:
        secrets_list.append(secondary)

    extra_raw = os.environ.get("MYCELIUM_SECRET_KEYS", "")
    for item in extra_raw.split(","):
        candidate = item.strip()
        if candidate and candidate not in secrets_list:
            secrets_list.append(candidate)

    return secrets_list


def verify_packet_with_rotation(
    payload: bytes,
    signature: str,
    primary_secret: Optional[str] = None,
) -> bool:
    if not signature:
        return False
    for secret in get_signing_secrets(primary_secret):
        if verify_packet(payload, signature, secret):
            return True
    return False
