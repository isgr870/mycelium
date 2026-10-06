import re

INDEX_PATH = "index.html"

with open(INDEX_PATH, "r") as f:
    content = f.read()

# Script to inject for fetching live backend topology
topology_script = """
<script>
// --- LIVE BACKEND MESH TELEMETRY BRIDGE ---
async function syncBackendTopology() {
    try {
        const response = await fetch('/topology.json?t=' + Date.now());
        if (!response.ok) return;
        const data = await response.json();
        
        if (!data || !data.nodes) return;
        
        // Update header metrics
        const peerCountEl = document.querySelector('.peer-count') || document.getElementById('peerCount');
        if (peerCountEl) {
            peerCountEl.innerText = `PEERS: ${data.nodes.length} | HOPS: ${data.links ? data.links.length : 0}`;
        }
        
        // Render or push backend nodes into mesh graph visualizer
        if (window.nodes && Array.isArray(window.nodes)) {
            data.nodes.forEach(bNode => {
                let existing = window.nodes.find(n => n.id === bNode.id);
                if (!existing) {
                    window.nodes.push({
                        id: bNode.id,
                        label: bNode.label || bNode.id,
                        x: Math.random() * (window.innerWidth || 800) * 0.6 + 100,
                        y: Math.random() * (window.innerHeight || 600) * 0.4 + 100,
                        vx: 0,
                        vy: 0,
                        status: bNode.status
                    });
                }
            });
        }
    } catch (e) {
        console.log("Waiting for backend topology stream...", e);
    }
}

setInterval(syncBackendTopology, 2000);
syncBackendTopology();
</script>
</body>
"""

if "syncBackendTopology" not in content:
    content = content.replace("</body>", topology_script)
    with open(INDEX_PATH, "w") as f:
        f.write(content)
    print("[+] Successfully unified index.html with live backend topology telemetry!")
else:
    print("[*] index.html is already patched.")
