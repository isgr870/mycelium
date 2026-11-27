# Mycelium Pre-Audit & Global Readiness Checklist

Use this checklist before external security/legal review or wider multi-region tester rollout.

## 1. Transport & Cryptographic Security
- [ ] All non-loopback and cross-region links run over **WireGuard** or **HTTPS/TLS** (never unencrypted HTTP over public WAN).
- [ ] Every node uses a high-entropy `MYCELIUM_SECRET_KEY` (and `MYCELIUM_SECONDARY_SECRET_KEY` during rotations), with documented key-rotation and compromise-response steps.
- [ ] Replay protection (`seen_nonces` in SQLite WAL) and `MYCELIUM_MAX_CLOCK_SKEW_SECONDS` are verified across node restarts.

## 2. Self-Defense & Resilience
- [ ] `MycelialDefense` strike thresholds, exponential quarantine windows, alarm advisories, and healthy-streak recovery match expected WAN behavior without false-locking healthy high-latency peers.
- [ ] Offline store-and-forward queue (`resilience_queue`) and Bloom manifest spore sync handle temporary peer partitions and recovery cleanly.

## 3. Observability & Operations
- [ ] Logs avoid leaking secret keys, raw tokens, or sensitive payload contents.
- [ ] Health checks, peer status (`/mesh/peers`), and `systemd` (or process supervisor) restart policies are verified on target Linux hosts.

## 4. Legal, Privacy & Cross-Border Data
- [ ] Confirm what data is placed inside replicated spores—avoid sensitive personal data or regulated records unless cross-border transfer, retention, and deletion requirements for involved jurisdictions are addressed.
- [ ] Keep [LICENSE](LICENSE) (`MIT`) and [SECURITY.md](SECURITY.md) accurate as features and threat boundaries evolve.
