import json
import time
import socket
import urllib.request
import urllib.error
from pathlib import Path

import packet_mesh

CLUSTER_NODES = [
    {"http": 8081, "tcp": 9001, "id": "node_alpha"},
    {"http": 8082, "tcp": 9002, "id": "node_beta"},
    {"http": 8083, "tcp": 9003, "id": "node_gamma"},
    {"http": 8084, "tcp": 9004, "id": "node_delta"},
]

OUTPUT_FILE = Path("topology.json")

def send_binary_handshake(target_tcp, source_id):
    """Sends a binary frame handshake over TCP to register peers."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        s.connect(("127.0.0.1", target_tcp))
        
        frame = packet_mesh.pack_packet(
            packet_mesh.TYPE_HANDSHAKE,
            {"source": source_id, "action": "ping"}
        )
        s.sendall(frame)
        s.close()
    except Exception:
        pass

def poll_and_bridge():
    graph = {"nodes": [], "links": []}
    seen_links = set()

    # Trigger mesh inter-node binary handshakes to connect all nodes
    for i, src in enumerate(CLUSTER_NODES):
        for dst in CLUSTER_NODES:
            if src["tcp"] != dst["tcp"]:
                send_binary_handshake(dst["tcp"], src["id"])

    # Query HTTP telemetry APIs for updated state
    for node in CLUSTER_NODES:
        url = f"http://127.0.0.1:{node['http']}/api/status"
        try:
            req = urllib.request.urlopen(url, timeout=1.5)
            data = json.loads(req.read().decode())
            
            node_id = data.get("node_id", node["id"])
            known_peers = data.get("known_peers", [])

            graph["nodes"].append({
                "id": node_id,
                "label": f"{node_id} (Port {node['tcp']})",
                "status": "active",
                "tcp_port": node["tcp"],
                "http_port": node["http"]
            })

            for peer in known_peers:
                link_key = tuple(sorted([node_id, peer]))
                if link_key not in seen_links:
                    seen_links.add(link_key)
                    graph["links"].append({"source": node_id, "target": peer})

        except urllib.error.URLError:
            graph["nodes"].append({
                "id": node["id"],
                "label": f"{node['id']} (Offline)",
                "status": "offline"
            })

    with open(OUTPUT_FILE, "w") as f:
        json.dump(graph, f, indent=2)

    print(f"[*] Topology updated: {len(graph['nodes'])} active nodes | {len(graph['links'])} connections mapped.")

if __name__ == "__main__":
    print("[*] Starting Mycelium Telemetry & Handshake Engine...")
    while True:
        poll_and_bridge()
        time.sleep(5)
