# Security Posture & Threat Boundaries (Mycelium / rddm)

## Current Defensive Controls
- **HMAC Envelope Signing:** Signed packets carry `X-Mycelium-Signature` verified against `MYCELIUM_SECRET_KEY`.
- **Fail-Closed Secret Validation:** Weak or missing secrets are rejected when hardening checks are active.
- **Rate Limiting:** Endpoint request throttling mitigates burst flooding.
- **Bounded Gossip Propagation:** Fanout limits (`k=6` default), `ttl` decrement per hop, and `gossip_id` deduplication prevent unbounded amplification loops.
- **Loopback-First Defaults:** Cluster scripts default to `127.0.0.1` so nodes are not inadvertently exposed to untrusted networks without transport protection.

## Threat Boundaries: Untrusted vs. Trusted Peers
- **Untrusted / Unauthenticated Traffic:**
  - Cannot forge valid `X-Mycelium-Signature` packets without `MYCELIUM_SECRET_KEY`.
  - Cannot bypass rate limits or inject arbitrary unverified control state on protected endpoints.
- **Trusted / Authenticated Mesh Peers (Share `MYCELIUM_SECRET_KEY`):**
  - Can register peer entries, exchange gossip ticks, and coordinate jobs/spores within protocol rules.
  - Compromise of `MYCELIUM_SECRET_KEY` on any single node compromises packet authenticity across peers sharing that secret—rotate keys carefully and scope per environment/mesh.

## Gaps Before Production / Formal Audit
1. **Transport Encryption (TLS / mTLS):** Plain HTTP on `127.0.0.1` is suitable for local/loopback or WireGuard/VPN-protected links; do not expose raw HTTP directly to public WANs without TLS/mTLS or a reverse proxy.
2. **Replay & Nonce Windowing:** Ensure strict timestamp skew checks and nonce/ID tracking across restarts so captured signed packets cannot be replayed indefinitely.
3. **Role-Based Authorization:** Separate read/gossip relay permissions from privileged job/admin actions if multi-tenant roles are introduced.
