"""Fungal-inspired self-defense primitives for Mycelium:
- Compartmentalization (peer quarantine with exponential backoff & recovery)
- Stress/anomaly tracking (signature, replay, skew, and flood strikes)
- Anastomosis routing (preferring non-quarantined peers during gossip/sync)
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List


@dataclass
class PeerDefenseState:
    strikes: int = 0
    quarantined_until: float = 0.0
    last_reason: str = ""
    healthy_streak: int = 0
    reasons_history: List[str] = field(default_factory=list)


class MycelialDefense:
    """Compartmentalizes hostile or faulty peers while allowing recovery."""

    def __init__(
        self,
        strike_threshold: int = 3,
        base_quarantine_seconds: float = 30.0,
        max_quarantine_seconds: float = 900.0,
        recovery_healthy_streak: int = 3,
    ) -> None:
        self.strike_threshold = max(1, strike_threshold)
        self.base_quarantine_seconds = max(1.0, base_quarantine_seconds)
        self.max_quarantine_seconds = max(self.base_quarantine_seconds, max_quarantine_seconds)
        self.recovery_healthy_streak = max(1, recovery_healthy_streak)
        self._peers: Dict[str, PeerDefenseState] = {}

    def _get_or_create(self, peer_key: str) -> PeerDefenseState:
        key = peer_key.strip()
        if key not in self._peers:
            self._peers[key] = PeerDefenseState()
        return self._peers[key]

    def record_violation(self, peer_key: str, reason: str, now: float | None = None) -> PeerDefenseState:
        ts = time.time() if now is None else now
        state = self._get_or_create(peer_key)
        state.strikes += 1
        state.healthy_streak = 0
        state.last_reason = reason
        state.reasons_history.append(f"{int(ts)}:{reason}")
        if len(state.reasons_history) > 25:
            state.reasons_history = state.reasons_history[-25:]

        if state.strikes >= self.strike_threshold:
            exponent = state.strikes - self.strike_threshold
            duration = min(
                self.max_quarantine_seconds,
                self.base_quarantine_seconds * (2 ** exponent),
            )
            state.quarantined_until = max(state.quarantined_until, ts + duration)
        return state

    def record_healthy(self, peer_key: str) -> PeerDefenseState:
        state = self._get_or_create(peer_key)
        state.healthy_streak += 1
        if state.healthy_streak >= self.recovery_healthy_streak:
            state.strikes = max(0, state.strikes - 1)
            state.healthy_streak = 0
        return state

    def is_quarantined(self, peer_key: str, now: float | None = None) -> bool:
        ts = time.time() if now is None else now
        state = self._peers.get(peer_key.strip())
        if not state:
            return False
        if ts < state.quarantined_until:
            return True
        # Quarantine window elapsed: lift block, keep partial strike memory
        state.quarantined_until = 0.0
        return False

    def route_peers(self, candidates: Iterable[str], now: float | None = None) -> List[str]:
        """Anastomosis rerouting: prefer non-quarantined peers; keep fallback if all are blocked."""
        ts = time.time() if now is None else now
        ordered: List[str] = []
        seen = set()
        for raw in candidates:
            p = raw.strip()
            if p and p not in seen:
                seen.add(p)
                ordered.append(p)

        healthy = [p for p in ordered if not self.is_quarantined(p, now=ts)]
        return healthy if healthy else ordered
