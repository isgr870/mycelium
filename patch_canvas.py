import re

INDEX_PATH = "index.html"

with open(INDEX_PATH, "r") as f:
    html = f.read()

canvas_bridge = """
<script>
// --- CLUSTER TOPOLOGY CANVAS INJECTOR ---
(function() {
    async function syncClusterToCanvas() {
        try {
            const res = await fetch('/topology.json?t=' + Date.now());
            if (!res.ok) return;
            const data = await res.json();
            if (!data.nodes) return;

            // Merge cluster nodes into the window's active node graph
            if (window.nodes && Array.isArray(window.nodes)) {
                data.nodes.forEach((clusterNode, i) => {
                    let existing = window.nodes.find(n => n.id === clusterNode.id);
                    if (!existing) {
                        const angle = (i / data.nodes.length) * Math.PI * 2;
                        const radius = 140;
                        const cx = (window.innerWidth || 400) / 2;
                        const cy = (window.innerHeight || 300) / 3;
                        
                        window.nodes.push({
                            id: clusterNode.id,
                            label: clusterNode.id,
                            x: cx + Math.cos(angle) * radius,
                            y: cy + Math.sin(angle) * radius,
                            vx: 0,
                            vy: 0,
                            pinned: false,
                            isClusterNode: true
                        });
                    }
                });
            }
        } catch (e) {
            // Silently wait for telemetry update
        }
    }
    setInterval(syncClusterToCanvas, 2000);
    syncClusterToCanvas();
})();
</script>
</body>
"""

if "CLUSTER TOPOLOGY CANVAS INJECTOR" not in html:
    html = html.replace("</body>", canvas_bridge)
    with open(INDEX_PATH, "w") as f:
        f.write(html)
    print("[+] Canvas renderer patched to display backend Python cluster nodes!")
else:
    print("[*] Canvas injector is already installed.")
