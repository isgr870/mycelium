from quadtree import Boundary, QuadtreeNode
from verlet_topology import VerletMeshSimulation
from swarm_rag import SwarmRAGNode
from spore_sync import SimpleBloomFilter

class MyceliumNode:
    def __init__(self, node_id, x, y, secret_key):
        self.node_id = node_id
        # 1. Spatial Routing Engine
        self.world_boundary = Boundary(500, 500, 500, 500)
        self.spatial_index = QuadtreeNode(self.world_boundary, capacity=4)
        self.spatial_index.insert({'id': node_id, 'x': x, 'y': y})

        # 2. Verlet Topology Simulation
        self.physics = VerletMeshSimulation()
        self.physics.add_peer(node_id, x, y, pinned=False)

        # 3. Decentralized Swarm RAG
        self.rag = SwarmRAGNode(node_id, secret_key)

        # 4. Spore Sync Bloom Filter
        self.spore_filter = SimpleBloomFilter(size=128, hash_count=3)

    def register_peer_telemetry(self, peer_id, px, py, latency_ms, packet_loss):
        # Add to spatial index & physics engine
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
    node = MyceliumNode('node_alpha', 150, 150, secret_key='mesh-secret')
    node.register_peer_telemetry('node_beta', 300, 300, latency_ms=45.0, packet_loss=0.01)
    node.rag.add_knowledge('chunk_alpha_1', 'Autonomous mesh active.', [0.9, 0.1, 0.0])
    
    print("Unified Mycelium Node initialized successfully:", node.status())
