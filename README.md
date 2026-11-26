# Mycelium (`rddm`)

Gossip-based mesh networking, spore vault synchronization, and resilient local job orchestration built with FastAPI and SQLite (WAL mode), designed and tested on Termux/Android.[span_1](start_span)[span_1](end_span)

## Overview

Mycelium (`rddm`) coordinates distributed node roles (`relay`, `storage`, and `worker`) with bounded gossip propagation (`k=6` fanout, `ttl` decrement, and `gossip_id` deduplication), adaptive Bloom filter sizing, HMAC-signed packet envelopes, rate limiting, stale peer eviction, and WAL-backed SQLite persistence.[span_2](start_span)[span_2](end_span)

## Quickstart (Termux)

cd ~/mycelium
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

Set a strong secret key in your environment or local `.env` (never commit `.env` or private keys such as `.mycelium/node.key`):[span_3](start_span)[span_3](end_span)

export MYCELIUM_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"

## Cluster Control & Observability

Lifecycle and inspection scripts live in `scripts/`:[span_4](start_span)[span_4](end_span)

- `./scripts/mycewake` — Acquires a Termux wake-lock (when `termux-api` is available), starts `relay` (`:8021`), `storage` (`:8022`), and `worker` (`:8023`) bound to `127.0.0.1`, and cross-registers cluster peers.[span_5](start_span)[span_5](end_span)
- `./scripts/mycensus` — Reports live node health (`[UP]` / `[DOWN]`), role, capabilities, peer counts, and job counts (`q` queued, `c` claimed, `d` done).[span_6](start_span)[span_6](end_span)
- `./scripts/myceoff` — Stops cluster processes and releases the Termux wake-lock.[span_7](start_span)[span_7](end_span)

## Environment Variables

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `MYCELIUM_SECRET_KEY` | *(required / generated)* | HMAC signing secret (`X-Mycelium-Signature`) for packet envelopes.[span_8](start_span)[span_8](end_span) |
| `MYCELIUM_GOSSIP_FANOUT` | `6` | Bounded peer sample size (`k`) per gossip round.[span_9](start_span)[span_9](end_span) |
| `MYCELIUM_BLOOM_MAX_BITS` | `65536` | Upper bit-size cap for adaptive Bloom filter scaling.[span_10](start_span)[span_10](end_span) |
| `MYCELIUM_PEER_TTL_SEC` | `300.0` | Stale peer expiration threshold in seconds (`prune_stale_peers`).[span_11](start_span)[span_11](end_span) |

## Running Tests

cd ~/mycelium
source venv/bin/activate
PYTHONPATH=. python -m pytest -v

## Security & Licensing

- See [SECURITY.md](SECURITY.md) for current defensive controls, untrusted vs. trusted peer threat boundaries, and pre-production / audit hardening items (TLS/mTLS, replay/nonce windowing, and role authorization).[span_12](start_span)[span_12](end_span)
- See [LICENSE](LICENSE) for licensing terms.[span_13](start_span)[span_13](end_span)
