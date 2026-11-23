from verlet_topology import VerletMeshSimulation

sim = VerletMeshSimulation()

sim.add_peer('bridge_laptop', 500, 300, pinned=True)
sim.add_peer('mobile_node_a', 400, 150)
sim.add_peer('mobile_node_b', 600, 450)

sim.connect_peers('bridge_laptop', 'mobile_node_a', latency_ms=25.0, packet_loss=0.02)
sim.connect_peers('bridge_laptop', 'mobile_node_b', latency_ms=120.0, packet_loss=0.15)

print("Running simulation...")
for i in range(10):
    sim.step()

state = sim.get_state()
print("Simulation step 10 node positions:", state['nodes'])
print("Link stresses:", state['links'])
