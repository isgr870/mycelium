#!/usr/bin/env python3
import argparse
import hashlib
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Set


REGIONS = ("us", "ug", "asia")

# Base one-way / RTT latency profile (ms) by (src_region, dst_region)
REGION_RTT_MS: Dict[tuple[str, str], tuple[int, int]] = {
    ("us", "us"): (18, 45),
    ("ug", "ug"): (15, 40),
    ("asia", "asia"): (20, 50),
    ("us", "ug"): (175, 240),
    ("ug", "us"): (175, 240),
    ("ug", "asia"): (145, 210),
    ("asia", "ug"): (145, 210),
    ("us", "asia"): (160, 225),
    ("asia", "us"): (160, 225),
}


class FastBloom:
    def __init__(self, size: int = 2048, hash_count: int = 4):
        self.size = size
        self.hash_count = hash_count
        self.bits = bytearray(size)

    def _idxs(self, item: str) -> List[int]:
        out = []
        for h in range(self.hash_count):
            digest = hashlib.blake2b(f"{h}:{item}".encode("utf-8"), digest_size=8).digest()
            out.append(int.from_bytes(digest, "big") % self.size)
        return out

    def add(self, item: str) -> None:
        for idx in self._idxs(item):
            self.bits[idx] = 1

    def snapshot(self) -> bytes:
        return bytes(self.bits)


@dataclass
class SimNode:
    node_id: int
    region: str
    tier: str  # operator | external | quarantined
    spores: Dict[str, dict] = field(default_factory=dict)
    bloom: FastBloom = field(default_factory=lambda: FastBloom(size=2048, hash_count=4))

    def put_spore(self, spore: dict) -> bool:
        if self.tier == "quarantined":
            return False
        sid = spore["spore_id"]
        if sid in self.spores:
            return False
        self.spores[sid] = spore
        self.bloom.add(sid)
        return True


def sample_rtt_ms(rng: random.Random, src_region: str, dst_region: str, tier: str) -> float:
    lo, hi = REGION_RTT_MS[(src_region, dst_region)]
    base = rng.uniform(lo, hi)
    # External tier gets slight queuing overhead; operators have fast lane
    factor = 0.85 if tier == "operator" else 1.15
    return base * factor


def main() -> None:
    ap = argparse.ArgumentParser(description="1,000-node Mycelium mesh simulator with US/UG/Asia latency")
    ap.add_argument("--nodes", type=int, default=1000)
    ap.add_argument("--seed-spores", type=int, default=25)
    ap.add_argument("--fanout", type=int, default=6)
    ap.add_argument("--max-rounds", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    t_start = time.perf_counter()

    mesh: List[SimNode] = []
    for i in range(args.nodes):
        region = REGIONS[i % len(REGIONS)]
        if i < 24:
            tier = "operator"
        elif i % 50 == 0:
            tier = "quarantined"
        else:
            tier = "external"
        mesh.append(SimNode(node_id=i, region=region, tier=tier))

    active_nodes = [n for n in mesh if n.tier != "quarantined"]
    all_spore_ids: Set[str] = set()

    for s in range(args.seed_spores):
        origin = active_nodes[s % len(active_nodes)]
        sid = hashlib.sha256(f"mesh1000-region-spore-{s}".encode("utf-8")).hexdigest()
        spore = {
            "spore_id": sid,
            "topic": f"mesh.region.{origin.region}",
            "seq": s,
            "origin_region": origin.region,
        }
        origin.put_spore(spore)
        all_spore_ids.add(sid)

    total_transfers = 0
    quarantined_blocked = 0
    total_sim_rtt_ms = 0.0
    rounds_run = 0

    for rnd in range(1, args.max_rounds + 1):
        rounds_run = rnd
        round_transfers = 0
        round_rtt_ms = 0.0

        for src in active_nodes:
            if not src.spores:
                continue
            peers = rng.sample(mesh, k=min(args.fanout, len(mesh)))
            for dst in peers:
                if dst.node_id == src.node_id:
                    continue
                if dst.tier == "quarantined":
                    quarantined_blocked += 1
                    continue

                rtt = sample_rtt_ms(rng, src.region, dst.region, src.tier)
                dst_bits = dst.bloom.snapshot()
                for sid, sp in src.spores.items():
                    if not all(
                        dst_bits[
                            int.from_bytes(
                                hashlib.blake2b(f"{h}:{sid}".encode("utf-8"), digest_size=8).digest(),
                                "big",
                            )
                            % dst.bloom.size
                        ]
                        == 1
                        for h in range(dst.bloom.hash_count)
                    ):
                        if dst.put_spore(sp):
                            round_transfers += 1
                            round_rtt_ms += rtt

        total_transfers += round_transfers
        total_sim_rtt_ms += round_rtt_ms
        converged = sum(1 for n in active_nodes if len(n.spores) == len(all_spore_ids))
        avg_rtt = (round_rtt_ms / round_transfers) if round_transfers else 0.0
        print(
            f"ROUND {rnd:02d}: transfers={round_transfers:5d}  "
            f"converged={converged}/{len(active_nodes)}  "
            f"avg_rtt={avg_rtt:6.1f}ms  blocked_q={quarantined_blocked}"
        )
        if converged == len(active_nodes):
            break

    elapsed = time.perf_counter() - t_start
    overall_avg_rtt = (total_sim_rtt_ms / total_transfers) if total_transfers else 0.0
    print(
        f"SUMMARY nodes={args.nodes} active={len(active_nodes)} spores={len(all_spore_ids)} "
        f"rounds={rounds_run} transfers={total_transfers} avg_rtt={overall_avg_rtt:.1f}ms "
        f"cum_rtt={total_sim_rtt_ms/1000:.2f}s wall={elapsed:.2f}s"
    )


if __name__ == "__main__":
    main()
