from quadtree import Boundary, QuadtreeNode
from swarm_rag import SwarmRAGNode
from spore_sync import SimpleBloomFilter
from verlet_topology import VerletMeshSimulation


def test_quadtree_spatial_query():
    domain = Boundary(500, 500, 500, 500)
    qtree = QuadtreeNode(domain, capacity=2)
    qtree.insert({"id": "peer_alpha", "x": 120, "y": 150})
    qtree.insert({"id": "peer_beta", "x": 850, "y": 900})
    qtree.insert({"id": "peer_gamma", "x": 140, "y": 160})

    neighbors = qtree.query(Boundary(150, 150, 100, 100))
    ids = [p["id"] for p in neighbors]
    assert "peer_alpha" in ids
    assert "peer_gamma" in ids
    assert "peer_beta" not in ids


def test_swarm_rag_hmac_and_search():
    secret = "mycelium-mesh-shared-secret"
    node_alpha = SwarmRAGNode("node_alpha", secret_key=secret)
    node_beta = SwarmRAGNode("node_beta", secret_key=secret)

    node_beta.add_knowledge(
        chunk_id="chunk_01",
        text="Verlet integration is ideal for real-time physics sandboxes on mobile browsers.",
        embedding=[0.85, 0.12, 0.03],
    )

    signed_packet = node_alpha.sign_query({"query_vector": [0.80, 0.15, 0.05], "max_results": 1})
    response = node_beta.verify_and_search(
        signed_packet, query_vector=[0.80, 0.15, 0.05], threshold=0.7
    )
    assert response is not None


def test_spore_bloom_diff():
    node_a = SimpleBloomFilter(size=64, hash_count=2)
    node_b = SimpleBloomFilter(size=64, hash_count=2)

    node_a.add("spore_chunk_99")
    node_a.add("spore_chunk_102")
    node_b.add("spore_chunk_102")

    diff = node_a.get_diff(node_b.bit_array)
    assert len(diff) > 0


def test_verlet_mesh_simulation_steps():
    sim = VerletMeshSimulation()
    sim.add_peer("bridge_laptop", 500, 300, pinned=True)
    sim.add_peer("mobile_node_a", 400, 150)
    sim.add_peer("mobile_node_b", 600, 450)
    sim.connect_peers("bridge_laptop", "mobile_node_a", latency_ms=25.0, packet_loss=0.02)
    sim.connect_peers("bridge_laptop", "mobile_node_b", latency_ms=120.0, packet_loss=0.15)

    for _ in range(10):
        sim.step()

    state = sim.get_state()
    assert "nodes" in state
    assert "links" in state
