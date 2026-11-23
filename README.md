# Mycelium

Decentralized spatial and swarm mesh framework with Verlet topology physics, quadtree spatial indexing, HMAC-SHA256 packet verification, and Bloom-filter spore synchronization.

## Quick Start

1. Copy `.env.example` to `.env` and generate a strong `MYCELIUM_SECRET_KEY`:
   cp .env.example .env
   python -c "import secrets; print(secrets.token_hex(32))"

2. Install dependencies and run tests:
   pip install -r requirements.txt
   PYTHONPATH=. python -m pytest tests/test_production_hardening.py -v

3. Start the node daemon:
   set -a && source .env && set +a
   python node.py
