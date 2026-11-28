#!/usr/bin/env python3
import hashlib
import os
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Tuple


DEFAULT_TIER_LIMITS: Dict[str, Dict[str, int]] = {
    "operator": {
        "window_sec": 60,
        "max_requests": 600,
        "max_bytes": 50 * 1024 * 1024,  # 50 MiB / min
        "max_strikes": 10,
    },
    "external": {
        "window_sec": 60,
        "max_requests": 30,
        "max_bytes": 1 * 1024 * 1024,   # 1 MiB / min
        "max_strikes": 3,
    },
    "quarantined": {
        "window_sec": 60,
        "max_requests": 0,
        "max_bytes": 0,
        "max_strikes": 0,
    },
}


def compute_pow_nonce(subject: str, difficulty_bits: int = 12, max_iters: int = 2_000_000) -> Tuple[int, str]:
    """Find an integer nonce such that sha256(f'{subject}:{nonce}') has `difficulty_bits` leading zero bits."""
    if difficulty_bits <= 0:
        digest = hashlib.sha256(f"{subject}:0".encode("utf-8")).hexdigest()
        return 0, digest
    full_nibbles = difficulty_bits // 4
    rem_bits = difficulty_bits % 4
    mask = (0xF << (4 - rem_bits)) & 0xF if rem_bits else 0

    for nonce in range(max_iters):
        digest = hashlib.sha256(f"{subject}:{nonce}".encode("utf-8")).hexdigest()
        if full_nibbles and not digest.startswith("0" * full_nibbles):
            continue
        if rem_bits:
            nxt = int(digest[full_nibbles], 16)
            if (nxt & mask) != 0:
                continue
        return nonce, digest
    raise RuntimeError("PoW search exceeded max_iters")


def verify_pow_token(subject: str, token: str, difficulty_bits: int = 12) -> bool:
    """Verify `<nonce>:<hex_digest>` against `subject` and `difficulty_bits`."""
    if not token or ":" not in token:
        return False
    nonce_str, digest = token.split(":", 1)
    try:
        nonce = int(nonce_str)
    except ValueError:
        return False
    expected = hashlib.sha256(f"{subject}:{nonce}".encode("utf-8")).hexdigest()
    if expected != digest.lower():
        return False
    if difficulty_bits <= 0:
        return True
    full_nibbles = difficulty_bits // 4
    rem_bits = difficulty_bits % 4
    mask = (0xF << (4 - rem_bits)) & 0xF if rem_bits else 0
    if full_nibbles and not expected.startswith("0" * full_nibbles):
        return False
    if rem_bits:
        nxt = int(expected[full_nibbles], 16)
        if (nxt & mask) != 0:
            return False
    return True


@dataclass
class _UsageEvent:
    ts: float
    num_bytes: int


@dataclass
class EdgeQuotaEngine:
    db_path: Optional[str] = None
    tier_limits: Dict[str, Dict[str, int]] = field(default_factory=lambda: {k: dict(v) for k, v in DEFAULT_TIER_LIMITS.items()})
    sybil_pow_bits: int = 12

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self._events: Dict[str, Deque[_UsageEvent]] = {}
        self._strikes: Dict[str, int] = {}
        self._quarantined_until: Dict[str, float] = {}

        if self.db_path:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
            with self._conn() as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS edge_peer_state (
                        principal_key TEXT PRIMARY KEY,
                        tier TEXT NOT NULL,
                        strikes INTEGER NOT NULL DEFAULT 0,
                        quarantined_until REAL NOT NULL DEFAULT 0.0,
                        updated_at REAL NOT NULL
                    )
                    """
                )
                for pkey, tier, strikes, q_until, _ in conn.execute(
                    "SELECT principal_key, tier, strikes, quarantined_until, updated_at FROM edge_peer_state"
                ):
                    self._strikes[pkey] = int(strikes)
                    if float(q_until) > 0:
                        self._quarantined_until[pkey] = float(q_until)

    def _conn(self) -> sqlite3.Connection:
        assert self.db_path is not None
        return sqlite3.connect(self.db_path, timeout=10.0)

    def _persist_principal(self, principal_key: str, tier: str, now: float) -> None:
        if not self.db_path:
            return
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO edge_peer_state (principal_key, tier, strikes, quarantined_until, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(principal_key) DO UPDATE SET
                    tier = excluded.tier,
                    strikes = excluded.strikes,
                    quarantined_until = excluded.quarantined_until,
                    updated_at = excluded.updated_at
                """,
                (
                    principal_key,
                    tier,
                    int(self._strikes.get(principal_key, 0)),
                    float(self._quarantined_until.get(principal_key, 0.0)),
                    now,
                ),
            )

    def effective_tier(self, principal_key: str, base_tier: str = "external", now: Optional[float] = None) -> str:
        ts = time.time() if now is None else float(now)
        with self._lock:
            q_until = self._quarantined_until.get(principal_key, 0.0)
            if q_until > ts:
                return "quarantined"
            if q_until > 0 and q_until <= ts:
                self._quarantined_until.pop(principal_key, None)
                self._strikes[principal_key] = 0
                self._persist_principal(principal_key, base_tier, ts)
            return base_tier if base_tier in self.tier_limits else "external"

    def record_strike(
        self,
        principal_key: str,
        base_tier: str = "external",
        quarantine_sec: float = 300.0,
        now: Optional[float] = None,
    ) -> Tuple[int, str]:
        ts = time.time() if now is None else float(now)
        limits = self.tier_limits.get(base_tier, self.tier_limits["external"])
        max_strikes = max(1, int(limits.get("max_strikes", 3)))
        with self._lock:
            strikes = self._strikes.get(principal_key, 0) + 1
            self._strikes[principal_key] = strikes
            tier = base_tier
            if strikes >= max_strikes:
                self._quarantined_until[principal_key] = ts + quarantine_sec
                tier = "quarantined"
            self._persist_principal(principal_key, tier, ts)
            return strikes, tier

    def consume_quota(
        self,
        principal_key: str,
        payload_bytes: int,
        base_tier: str = "external",
        quarantine_sec: float = 300.0,
        now: Optional[float] = None,
    ) -> Tuple[bool, str, Dict[str, int]]:
        ts = time.time() if now is None else float(now)
        eff_tier = self.effective_tier(principal_key, base_tier=base_tier, now=ts)
        limits = self.tier_limits.get(eff_tier, self.tier_limits["external"])
        window = float(limits["window_sec"])
        max_req = int(limits["max_requests"])
        max_bytes = int(limits["max_bytes"])

        with self._lock:
            dq = self._events.setdefault(principal_key, deque())
            cutoff = ts - window
            while dq and dq[0].ts < cutoff:
                dq.popleft()

            used_req = len(dq)
            used_bytes = sum(e.num_bytes for e in dq)

            if eff_tier == "quarantined":
                return False, "peer_quarantined", {
                    "used_requests": used_req,
                    "max_requests": max_req,
                    "used_bytes": used_bytes,
                    "max_bytes": max_bytes,
                }

            if used_req + 1 > max_req:
                strikes, new_tier = self.record_strike(
                    principal_key, base_tier=base_tier, quarantine_sec=quarantine_sec, now=ts
                )
                return False, f"request_quota_exceeded(strikes={strikes},tier={new_tier})", {
                    "used_requests": used_req,
                    "max_requests": max_req,
                    "used_bytes": used_bytes,
                    "max_bytes": max_bytes,
                }

            if used_bytes + max(0, int(payload_bytes)) > max_bytes:
                strikes, new_tier = self.record_strike(
                    principal_key, base_tier=base_tier, quarantine_sec=quarantine_sec, now=ts
                )
                return False, f"byte_quota_exceeded(strikes={strikes},tier={new_tier})", {
                    "used_requests": used_req,
                    "max_requests": max_req,
                    "used_bytes": used_bytes,
                    "max_bytes": max_bytes,
                }

            dq.append(_UsageEvent(ts=ts, num_bytes=max(0, int(payload_bytes))))
            return True, "ok", {
                "used_requests": used_req + 1,
                "max_requests": max_req,
                "used_bytes": used_bytes + max(0, int(payload_bytes)),
                "max_bytes": max_bytes,
            }
