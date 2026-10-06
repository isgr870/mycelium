import re

INDEX_PATH = "index.html"

with open(INDEX_PATH, "r") as f:
    content = f.read()

# JS snippet to hook into the UI broadcast input and forward to cluster HTTP API
bridge_script = """
<script>
// --- GOSSIP TO CLUSTER HTTP RELAY ---
document.addEventListener("DOMContentLoaded", () => {
    const chatInput = document.querySelector('input[placeholder*="Broadcast packet"]');
    const sendBtn = document.querySelector('button:has-text("SEND")') || document.querySelectorAll('button')[document.querySelectorAll('button').length - 1];

    async function relayToCluster(message) {
        try {
            await fetch('http://127.0.0.1:8081/api/gossip', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    payload: message,
                    sender: window.currentSporeId || 'ui_spore',
                    timestamp: Date.now()
                })
            });
        } catch (e) {
            console.log("Cluster relay pending...", e);
        }
    }

    if (chatInput) {
        chatInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && chatInput.value.trim()) {
                relayToCluster(chatInput.value.trim());
            }
        });
    }
});
</script>
</body>
"""

if "GOSSIP TO CLUSTER HTTP RELAY" not in content:
    content = content.replace("</body>", bridge_script)
    with open(INDEX_PATH, "w") as f:
        f.write(content)
    print("[+] UI Gossip feed linked to backend cluster endpoint!")
else:
    print("[*] UI Gossip relay already active.")
