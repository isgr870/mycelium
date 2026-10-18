import os
import argparse
import logging
from quadtree import Boundary, QuadtreeNode
from verlet_topology import VerletMeshSimulation
from swarm_rag import SwarmRAGNode
from spore_sync import SimpleBloomFilter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MyceliumNode:
    def __init__(self, node_id, x, y):
        secret_key = os.environ.get('MYCELIUM_SECRET_KEY')
        if not secret_key:
            raise ValueError("CRITICAL: MYCELIUM_SECRET_KEY environment variable is missing!")
            
        self.node_id = node_id
        self.world_boundary = Boundary(500, 500, 500, 500)
        self.spatial_index = QuadtreeNode(self.world_boundary, capacity=4)
        self.spatial_index.insert({'id': node_id, 'x': x, 'y': y})
        self.physics = VerletMeshSimulation()
        self.physics.add_peer(node_id, x, y, pinned=False)
        self.rag = SwarmRAGNode(node_id, secret_key)
        self.spore_filter = SimpleBloomFilter(size=128, hash_count=3)

    def register_peer_telemetry(self, peer_id, px, py, latency_ms, packet_loss):
        self.spatial_index.insert({'id': peer_id, 'x': px, 'y': py})
        self.physics.add_peer(peer_id, px, py)
        self.physics.connect_peers(self.node_id, peer_id, latency_ms, packet_loss)

    def status(self):
        return {
            'node_id': self.node_id,
            'physics_state': self.physics.get_state(),
            'rag_chunks_stored': len(self.rag.local_vector_store)
        }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mycelium Mesh Node")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    parser.add_argument("--peer", type=str, default="", help="Initial peer address")
    args, unknown = parser.parse_known_args()

    # Provide safe fallback or enforce env var
    if 'MYCELIUM_SECRET_KEY' not in os.environ:
        os.environ['MYCELIUM_SECRET_KEY'] = 'default-development-key-changeme'

    node = MyceliumNode('node_alpha', 150, 150)
    if args.peer:
        logger.info("Connecting to initial peer: %s", args.peer)
        node.register_peer_telemetry('peer_remote', 300, 300, latency_ms=30.0, packet_loss=0.0)
    
    logger.info("Unified Mycelium Node initialized successfully: %s", node.status())
