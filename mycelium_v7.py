import http.server
import socketserver
import json
import sys

PORT = 8095

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>VERLET HYPHAE MESH // v7.12</title>
    <style>
        * { box-sizing: border-box; user-select: none; -webkit-user-select: none; }
        body {
            margin: 0;
            padding: 12px;
            background-color: #06090e;
            color: #22d3ee;
            font-family: 'Courier New', Courier, monospace;
            display: flex;
            flex-direction: column;
            min-height: 100vh;
            justify-content: flex-start;
        }

        /* Top Bar */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 13px;
            font-weight: bold;
            letter-spacing: 1px;
            margin-bottom: 8px;
            color: #20dbad;
        }

        /* Canvas Container */
        .canvas-container {
            position: relative;
            width: 100%;
            height: 380px;
            background: #080d14;
            border: 1px solid #13383a;
            border-radius: 4px;
            overflow: hidden;
            margin-bottom: 10px;
            box-shadow: 0 0 15px rgba(19, 56, 58, 0.3);
        }

        canvas {
            display: block;
            width: 100%;
            height: 100%;
        }

        /* Node Inspector Card */
        .inspector-card {
            background: #080d14;
            border: 1px solid #1e3a3a;
            border-radius: 4px;
            padding: 10px 14px;
            margin-bottom: 10px;
            font-size: 12px;
            display: none;
        }
        .inspector-card.active { display: block; }
        .insp-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }
        .insp-id { color: #f43f5e; font-weight: bold; font-size: 13px; }
        .insp-close { color: #f43f5e; cursor: pointer; font-weight: bold; }
        .insp-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 6px 12px;
            color: #94a3b8;
        }
        .insp-val { color: #e2e8f0; }

        /* Sub Status Bar */
        .status-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 11px;
            color: #64748b;
            margin-bottom: 10px;
            letter-spacing: 1px;
        }

        /* Control Panel */
        .controls {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .input-row {
            display: flex;
            gap: 8px;
        }

        input[type="text"] {
            flex: 1;
            background: #060a10;
            border: 1px solid #13383a;
            border-radius: 4px;
            padding: 10px 12px;
            color: #22d3ee;
            font-family: inherit;
            font-size: 12px;
            outline: none;
        }
        input[type="text"]:focus { border-color: #20dbad; }

        .btn-row {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr 1fr;
            gap: 8px;
        }

        button {
            background: #071518;
            border: 1px solid #13383a;
            color: #20dbad;
            padding: 10px;
            font-family: inherit;
            font-size: 11px;
            font-weight: bold;
            border-radius: 4px;
            cursor: pointer;
            text-align: center;
            text-transform: uppercase;
            transition: all 0.15s ease;
        }
        button:active { transform: scale(0.96); background: #13383a; }
        
        .btn-broadcast { background: #072622; border-color: #20dbad; width: 120px; }
        .btn-flush { color: #f43f5e; border-color: #581c2d; background: #1a0a10; }
        .btn-flush:active { background: #581c2d; }
    </style>
</head>
<body>

    <!-- Header -->
    <div class="header">
        <div>VERLET HYPHAE MESH // v7.12</div>
        <div>FPS: <span id="fps-val">60</span></div>
    </div>

    <!-- Physics Canvas -->
    <div class="canvas-container" id="canvas-container">
        <canvas id="meshCanvas"></canvas>
    </div>

    <!-- Selected Node Inspector -->
    <div class="inspector-card" id="inspector">
        <div class="insp-top">
            <div class="insp-id" id="insp-id">SPORE_1084</div>
            <div class="insp-close" onclick="closeInspector()">[CLOSE]</div>
        </div>
        <div class="insp-grid">
            <div>Role: <span class="insp-val" id="insp-role">RELAY</span></div>
            <div>Root: <span class="insp-val" id="insp-root">shd_0x236feb...</span></div>
            <div>Storage: <span class="insp-val" id="insp-storage">27%</span></div>
            <div>Metrics: <span class="insp-val" id="insp-metrics">8ms / 39°C</span></div>
        </div>
    </div>

    <!-- Status Bar -->
    <div class="status-bar">
        <div>MY OWN INTERNET // v7.12</div>
        <div>ACTIVE PEERS: <span id="peer-count" style="color:#20dbad;">25</span></div>
    </div>

    <!-- Action Controls -->
    <div class="controls">
        <div class="input-row">
            <input type="text" id="msg-input" value="Syncing neural cluster bl..." placeholder="Type broadcast message...">
            <button class="btn-broadcast" onclick="triggerBroadcast()">BROADCAST</button>
        </div>
        <div class="btn-row">
            <button onclick="addSpore()">+ SPORE</button>
            <button onclick="mutateMesh()">MUTATE</button>
            <button class="btn-flush" onclick="flushMesh()">FLUSH</button>
            <button id="btn-hib" onclick="toggleHibernate()">HIBERNATE</button>
        </div>
    </div>

    <script>
        const canvas = document.getElementById('meshCanvas');
        const ctx = canvas.getContext('2d');
        const container = document.getElementById('canvas-container');

        let width, height;
        function resize() {
            width = canvas.width = container.clientWidth;
            height = canvas.height = container.clientHeight;
        }
        window.addEventListener('resize', resize);
        resize();

        // Node Palette
        const COLOR_PALETTE = ['#20dbad', '#f97316', '#a855f7', '#22d3ee', '#facc15'];
        const ROLES = ['RELAY', 'EDGE', 'GATEWAY', 'ROOT'];

        // Simulation State
        let spores = [];
        let pulses = [];
        let selectedSpore = null;
        let isHibernating = false;
        let maxConnectDist = 100;
        let lastTime = performance.now();
        let frameCount = 0;

        // Spore Class using Verlet Integration Physics
        class Spore {
            constructor(id, x, y) {
                this.id = id || 'spore_' + Math.floor(1000 + Math.random() * 9000);
                this.x = x !== undefined ? x : Math.random() * (width - 40) + 20;
                this.y = y !== undefined ? y : Math.random() * (height - 40) + 20;
                this.oldX = this.x + (Math.random() - 0.5) * 3;
                this.oldY = this.y + (Math.random() - 0.5) * 3;
                this.radius = 6 + Math.random() * 4;
                this.color = COLOR_PALETTE[Math.floor(Math.random() * COLOR_PALETTE.length)];
                
                // Telemetry Data
                this.role = ROLES[Math.floor(Math.random() * ROLES.length)];
                this.storage = Math.floor(Math.random() * 85 + 10) + '%';
                this.ping = Math.floor(Math.random() * 15 + 3) + 'ms';
                this.temp = Math.floor(Math.random() * 12 + 32) + '°C';
                this.root = 'shd_0x' + Math.random().toString(16).substr(2, 6) + '...';
            }

            update(damping) {
                if (isHibernating) return;

                let vx = (this.x - this.oldX) * damping;
                let vy = (this.y - this.oldY) * damping;

                this.oldX = this.x;
                this.oldY = this.y;

                this.x += vx;
                this.y += vy;

                // Canvas boundaries bounce
                const pad = this.radius + 4;
                if (this.x < pad) { this.x = pad; this.oldX = this.x + vx * 0.8; }
                if (this.x > width - pad) { this.x = width - pad; this.oldX = this.x + vx * 0.8; }
                if (this.y < pad) { this.y = pad; this.oldY = this.y + vy * 0.8; }
                if (this.y > height - pad) { this.y = height - pad; this.oldY = this.y + vy * 0.8; }
            }

            draw() {
                // Outer ring
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.radius + 3, 0, Math.PI * 2);
                ctx.strokeStyle = this.color;
                ctx.lineWidth = 1.2;
                ctx.globalAlpha = 0.6;
                ctx.stroke();

                // Inner core
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.radius - 2, 0, Math.PI * 2);
                ctx.fillStyle = this.color;
                ctx.globalAlpha = 1.0;
                ctx.fill();

                // Selected Highlight
                if (selectedSpore === this) {
                    ctx.beginPath();
                    ctx.arc(this.x, this.y, this.radius + 9, 0, Math.PI * 2);
                    ctx.strokeStyle = '#ffffff';
                    ctx.lineWidth = 2;
                    ctx.stroke();
                }

                // Label
                ctx.fillStyle = '#94a3b8';
                ctx.font = '9px monospace';
                ctx.globalAlpha = 0.85;
                ctx.fillText(this.id, this.x + this.radius + 5, this.y + 3);
            }
        }

        // Initialize default spores cluster
        function initCluster(count) {
            spores = [];
            for (let i = 0; i < count; i++) {
                spores.push(new Spore());
            }
            updatePeerCount();
        }

        function updatePeerCount() {
            document.getElementById('peer-count').innerText = spores.length;
        }

        // Connect hyphae & resolve distance constraints
        function resolveHyphae() {
            for (let i = 0; i < spores.length; i++) {
                for (let j = i + 1; j < spores.length; j++) {
                    let s1 = spores[i];
                    let s2 = spores[j];
                    let dx = s2.x - s1.x;
                    let dy = s2.y - s1.y;
                    let dist = Math.sqrt(dx * dx + dy * dy);

                    if (dist < maxConnectDist) {
                        // Draw Hyphae Link
                        ctx.beginPath();
                        ctx.moveTo(s1.x, s1.y);
                        ctx.lineTo(s2.x, s2.y);
                        ctx.strokeStyle = s1.color;
                        ctx.globalAlpha = (1 - dist / maxConnectDist) * 0.4;
                        ctx.lineWidth = 1;
                        ctx.stroke();

                        // Soft elastic distance constraint physics
                        if (!isHibernating) {
                            let targetDist = 60;
                            let delta = (dist - targetDist) * 0.005;
                            let nx = (dx / dist) * delta;
                            let ny = (dy / dist) * delta;

                            s1.x += nx;
                            s1.y += ny;
                            s2.x -= nx;
                            s2.y -= nx;
                        }
                    }
                }
            }
        }

        // Animate incoming data signal pulses across links
        function updatePulses() {
            for (let i = pulses.length - 1; i >= 0; i--) {
                let p = pulses[i];
                p.progress += 0.04;
                if (p.progress >= 1) {
                    pulses.splice(i, 1);
                    continue;
                }
                let currX = p.fromX + (p.toX - p.fromX) * p.progress;
                let currY = p.fromY + (p.toY - p.fromY) * p.progress;

                ctx.beginPath();
                ctx.arc(currX, currY, 4, 0, Math.PI * 2);
                ctx.fillStyle = '#ffffff';
                ctx.shadowColor = '#20dbad';
                ctx.shadowBlur = 8;
                ctx.fill();
                ctx.shadowBlur = 0;
            }
        }

        // Main Animation Loop
        function animate(now) {
            frameCount++;
            if (now - lastTime >= 1000) {
                document.getElementById('fps-val').innerText = frameCount;
                frameCount = 0;
                lastTime = now;
            }

            ctx.clearRect(0, 0, width, height);

            // Update & Render Hyphae Network
            resolveHyphae();

            // Update & Render Spores
            for (let spore of spores) {
                spore.update(0.98);
                spore.draw();
            }

            // Update Signals
            updatePulses();

            requestAnimationFrame(animate);
        }

        // Interaction Handler (Select Spore)
        canvas.addEventListener('pointerdown', (e) => {
            const rect = canvas.getBoundingClientRect();
            const clickX = e.clientX - rect.left;
            const clickY = e.clientY - rect.top;

            let found = null;
            for (let spore of spores) {
                let dist = Math.hypot(spore.x - clickX, spore.y - clickY);
                if (dist <= spore.radius + 10) {
                    found = spore;
                    break;
                }
            }

            selectedSpore = found;
            if (selectedSpore) {
                showInspector(selectedSpore);
            } else {
                closeInspector();
            }
        });

        function showInspector(spore) {
            document.getElementById('insp-id').innerText = spore.id.toUpperCase();
            document.getElementById('insp-role').innerText = spore.role;
            document.getElementById('insp-root').innerText = spore.root;
            document.getElementById('insp-storage').innerText = spore.storage;
            document.getElementById('insp-metrics').innerText = spore.ping + ' / ' + spore.temp;
            document.getElementById('inspector').classList.add('active');
        }

        function closeInspector() {
            selectedSpore = null;
            document.getElementById('inspector').classList.remove('active');
        }

        // Buttons & Mechanics
        function addSpore() {
            spores.push(new Spore());
            updatePeerCount();
        }

        function mutateMesh() {
            for (let spore of spores) {
                spore.oldX = spore.x + (Math.random() - 0.5) * 30;
                spore.oldY = spore.y + (Math.random() - 0.5) * 30;
                spore.role = ROLES[Math.floor(Math.random() * ROLES.length)];
            }
        }

        function flushMesh() {
            if (spores.length > 5) {
                spores = spores.slice(0, 5);
            } else {
                initCluster(20);
            }
            closeInspector();
            updatePeerCount();
        }

        function toggleHibernate() {
            isHibernating = !isHibernating;
            const btn = document.getElementById('btn-hib');
            if (isHibernating) {
                btn.innerText = "AWAKEN";
                btn.style.color = "#facc15";
            } else {
                btn.innerText = "HIBERNATE";
                btn.style.color = "#20dbad";
            }
        }

        function triggerBroadcast() {
            let src = selectedSpore || spores[Math.floor(Math.random() * spores.length)];
            if (!src) return;

            for (let target of spores) {
                if (target === src) continue;
                let dist = Math.hypot(target.x - src.x, target.y - src.y);
                if (dist < maxConnectDist) {
                    pulses.push({
                        fromX: src.x,
                        fromY: src.y,
                        toX: target.x,
                        toY: target.y,
                        progress: 0
                    });
                }
            }
        }

        // Launch with 25 nodes
        initCluster(25);
        requestAnimationFrame(animate);
    </script>
</body>
</html>
"""

class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(HTML_CONTENT.encode("utf-8"))

    def log_message(self, format, *args):
        return  # Suppress HTTP console spam

if __name__ == "__main__":
    server_address = ('', PORT)
    http = socketserver.TCPServer(server_address, RequestHandler)
    print(f"\n==================================================")
    print(f" VERLET HYPHAE MESH ENGINE v7.12 READY")
    print(f" URL: http://localhost:{PORT}")
    print(f"==================================================\n")
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Engine shut down.")
        sys.exit(0)
