INDEX_PATH = "index.html"

with open(INDEX_PATH, "r") as f:
    html = f.read()

# Update overlay logic to draw an active bridge link between tab spores and cluster nodes
old_code = "overlayClusterNodes();"
new_code = """
            // Connect local browser spore nodes to node_gamma
            if (window.nodes && Array.isArray(window.nodes)) {
                const gammaPos = positions['node_gamma'];
                if (gammaPos) {
                    window.nodes.forEach(spore => {
                        ctx.beginPath();
                        ctx.strokeStyle = "rgba(0, 200, 255, 0.4)";
                        ctx.setLineDash([4, 4]);
                        ctx.lineWidth = 1.5;
                        ctx.moveTo(spore.x, spore.y);
                        ctx.lineTo(gammaPos.x, gammaPos.y);
                        ctx.stroke();
                        ctx.setLineDash([]);
                    });
                }
            }
            overlayClusterNodes();
"""

if "setLineDash" not in html:
    html = html.replace(old_code, new_code)
    with open(INDEX_PATH, "w") as f:
        f.write(html)
    print("[+] Edge link added between browser tab spores and cluster nodes!")
else:
    print("[*] Spore-to-cluster edge link is already active.")
