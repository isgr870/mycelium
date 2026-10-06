INDEX_PATH = "index.html"

with open(INDEX_PATH, "r") as f:
    html = f.read()

pulse_script = """
<script>
// --- PACKET PULSE ANIMATOR ---
(function() {
    window.activePulses = window.activePulses || [];

    window.triggerPulse = function(x1, y1, x2, y2, color="#00ffff") {
        window.activePulses.push({
            x1, y1, x2, y2,
            progress: 0,
            speed: 0.04,
            color
        });
    };

    const canvas = document.querySelector('canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    function drawPulses() {
        for (let i = window.activePulses.length - 1; i >= 0; i--) {
            const p = window.activePulses[i];
            p.progress += p.speed;
            
            const currentX = p.x1 + (p.x2 - p.x1) * p.progress;
            const currentY = p.y1 + (p.y2 - p.y1) * p.progress;

            ctx.beginPath();
            ctx.arc(currentX, currentY, 4, 0, Math.PI * 2);
            ctx.fillStyle = p.color;
            ctx.shadowColor = p.color;
            ctx.shadowBlur = 8;
            ctx.fill();
            ctx.shadowBlur = 0;

            if (p.progress >= 1) {
                window.activePulses.splice(i, 1);
            }
        }
    }

    const origReq = window.requestAnimationFrame;
    window.requestAnimationFrame = function(cb) {
        return origReq(function(ts) {
            cb(ts);
            drawPulses();
        });
    };
})();
</script>
</body>
"""

if "PACKET PULSE ANIMATOR" not in html:
    html = html.replace("</body>", pulse_script)
    with open(INDEX_PATH, "w") as f:
        f.write(html)
    print("[+] Edge packet pulse animations integrated into canvas!")
else:
    print("[*] Pulse animator is already installed.")
