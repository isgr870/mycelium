INDEX_PATH = "index.html"

with open(INDEX_PATH, "r") as f:
    html = f.read()

cluster_draw_script = """
<script>
// --- DIRECT CANVAS CLUSTER NODE RENDERER ---
(function() {
    let clusterNodes = [];
    let clusterLinks = [];

    async function fetchCluster() {
        try {
            const res = await fetch('/topology.json?t=' + Date.now());
            if (!res.ok) return;
            const data = await res.json();
            clusterNodes = data.nodes || [];
            clusterLinks = data.links || [];
        } catch (e) {}
    }
    setInterval(fetchCluster, 2000);
    fetchCluster();

    const canvas = document.querySelector('canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    function overlayClusterNodes() {
        if (!clusterNodes.length) return;

        const cx = canvas.width / 2;
        const cy = canvas.height / 3;
        const radius = Math.min(canvas.width, canvas.height) * 0.22;

        // Position nodes in a fixed orbit
        const positions = {};
        clusterNodes.forEach((node, idx) => {
            const angle = (idx / clusterNodes.length) * Math.PI * 2 - Math.PI / 2;
            positions[node.id] = {
                x: cx + Math.cos(angle) * radius,
                y: cy + Math.sin(angle) * radius
            };
        });

        // Draw Links
        ctx.strokeStyle = "rgba(0, 255, 128, 0.35)";
        ctx.lineWidth = 1.5;
        clusterLinks.forEach(link => {
            const p1 = positions[link.source];
            const p2 = positions[link.target];
            if (p1 && p2) {
                ctx.beginPath();
                ctx.moveTo(p1.x, p1.y);
                ctx.lineTo(p2.x, p2.y);
                ctx.stroke();
            }
        });

        // Draw Nodes
        clusterNodes.forEach(node => {
            const pos = positions[node.id];
            if (!pos) return;

            // Glow
            ctx.beginPath();
            ctx.arc(pos.x, pos.y, 10, 0, Math.PI * 2);
            ctx.fillStyle = "rgba(0, 255, 128, 0.25)";
            ctx.fill();

            // Core
            ctx.beginPath();
            ctx.arc(pos.x, pos.y, 5, 0, Math.PI * 2);
            ctx.fillStyle = "#00ff80";
            ctx.fill();

            // Label
            ctx.fillStyle = "#a0ffa0";
            ctx.font = "11px monospace";
            ctx.fillText(node.id, pos.x + 10, pos.y + 4);
        });
    }

    // Inject into animation frame
    const origRequestAnimationFrame = window.requestAnimationFrame;
    window.requestAnimationFrame = function(callback) {
        return origRequestAnimationFrame(function(timestamp) {
            callback(timestamp);
            overlayClusterNodes();
        });
    };
})();
</script>
</body>
"""

if "DIRECT CANVAS CLUSTER NODE RENDERER" not in html:
    html = html.replace("</body>", cluster_draw_script)
    with open(INDEX_PATH, "w") as f:
        f.write(html)
    print("[+] Successfully attached direct canvas renderer overlay for backend cluster!")
else:
    print("[*] Overlay renderer is already active in index.html.")
