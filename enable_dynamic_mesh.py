import re

INDEX_PATH = "index.html"

with open(INDEX_PATH, "r") as f:
    html = f.read()

# 1. Clean out the static 4-node overlay script if present
html = re.sub(r'<script>\s*// --- DIRECT CANVAS CLUSTER NODE RENDERER ---.*?</script>', '', html, flags=re.DOTALL)
html = re.sub(r'<script>\s*// --- CLUSTER TOPOLOGY CANVAS INJECTOR ---.*?</script>', '', html, flags=re.DOTALL)

dynamic_mesh_engine = """
<script>
// --- SELF-ORGANIZING DYNAMIC VERLET MESH ---
(function() {
    window.nodes = window.nodes || [];
    window.links = window.links || [];

    // K-Nearest Neighbor Auto-Connect Rule
    const MAX_PEER_CONNECTIONS = 3;
    const CONNECT_RADIUS = 280;

    function autoConnectNode(newNode) {
        let candidates = window.nodes.filter(n => n.id !== newNode.id);
        
        // Sort by Euclidean distance in canvas space
        candidates.sort((a, b) => {
            let distA = Math.hypot(a.x - newNode.x, a.y - newNode.y);
            let distB = Math.hypot(b.x - newNode.x, b.y - newNode.y);
            return distA - distB;
        });

        let connected = 0;
        for (let target of candidates) {
            if (connected >= MAX_PEER_CONNECTIONS) break;
            
            let dist = Math.hypot(target.x - newNode.x, target.y - newNode.y);
            if (dist <= CONNECT_RADIUS) {
                // Add bilateral link if not already existing
                let exists = window.links.some(l => 
                    (l.source === newNode.id && l.target === target.id) ||
                    (l.source === target.id && l.target === newNode.id)
                );
                
                if (!exists) {
                    window.links.push({
                        source: newNode.id,
                        target: target.id,
                        length: 110,
                        stiffness: 0.05
                    });
                    connected++;
                }
            }
        }
    }

    // Dynamic Live Discovery polling (removes hardcoded nodes, ingests real active peers)
    async function syncDynamicPeers() {
        try {
            const res = await fetch('/api/status?t=' + Date.now());
            if (!res.ok) return;
            const data = await res.json();
            
            // Ingest active nodes dynamically detected by local scanner/cluster
            if (data.peers && Array.isArray(data.peers)) {
                data.peers.forEach(peerId => {
                    let existing = window.nodes.find(n => n.id === peerId);
                    if (!existing) {
                        let newN = {
                            id: peerId,
                            label: peerId,
                            x: (canvas.width / 2) + (Math.random() - 0.5) * 150,
                            y: (canvas.height / 2) + (Math.random() - 0.5) * 150,
                            vx: (Math.random() - 0.5) * 2,
                            vy: (Math.random() - 0.5) * 2,
                            type: 'dynamic_peer'
                        };
                        window.nodes.push(newN);
                        autoConnectNode(newN);
                    }
                });
            }
        } catch (e) {}
    }

    // Auto-mesh local browser tabs as they spin up
    window.addEventListener('storage', function(e) {
        if (e.key === 'mycelium_active_spores') {
            try {
                let activeSpores = JSON.parse(e.newValue || '[]');
                activeSpores.forEach(sporeId => {
                    let n = window.nodes.find(x => x.id === sporeId);
                    if (!n) {
                        let newSpore = {
                            id: sporeId,
                            label: sporeId,
                            x: Math.random() * (window.innerWidth || 360),
                            y: Math.random() * (window.innerHeight || 300),
                            vx: 0, vy: 0,
                            type: 'browser_spore'
                        };
                        window.nodes.push(newSpore);
                        autoConnectNode(newSpore);
                    }
                });
            } catch(err){}
        }
    });

    setInterval(syncDynamicPeers, 2500);
})();
</script>
</body>
"""

html = html.replace("</body>", dynamic_mesh_engine)

with open(INDEX_PATH, "w") as f:
    f.write(html)

print("[+] Hardcoded nodes purged. Dynamic auto-meshing physics engine active!")
