import http.server
import socketserver
import sys
import os

PORT = 8090
for i, arg in enumerate(sys.argv):
    if arg == '--port' and i + 1 < len(sys.argv):
        PORT = int(sys.argv[i + 1])

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>X9 // DUAL-TRACK VAULT</title>
    <style>
        :root {
            --bg: #0a0a0c;
            --panel: #121215;
            --orange: #ff5500;
            --green: #00ff66;
            --red: #ff2233;
            --border: #ff5500;
            --text-dim: #8a8a93;
        }
        body {
            background-color: var(--bg);
            color: #d1d1d6;
            font-family: 'Courier New', Courier, monospace;
            margin: 0;
            padding: 12px;
            box-sizing: border-box;
        }
        .header {
            border-bottom: 2px solid var(--orange);
            padding-bottom: 8px;
            margin-bottom: 16px;
        }
        .header h1 {
            color: var(--orange);
            margin: 0;
            font-size: 1.2rem;
            letter-spacing: 1px;
        }
        .header .subtitle {
            color: var(--green);
            font-size: 0.75rem;
            margin-top: 2px;
        }
        .card {
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 4px;
            padding: 12px;
            margin-bottom: 14px;
            position: relative;
        }
        .card-title {
            color: var(--orange);
            font-size: 0.85rem;
            font-weight: bold;
            letter-spacing: 0.5px;
            margin-bottom: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .badge {
            background: rgba(0, 255, 102, 0.1);
            color: var(--green);
            border: 1px solid var(--green);
            padding: 2px 6px;
            font-size: 0.65rem;
            border-radius: 2px;
        }
        .select-box, .btn {
            width: 100%;
            background: #1a1a20;
            border: 1px solid var(--orange);
            color: var(--orange);
            padding: 8px;
            font-family: inherit;
            font-size: 0.8rem;
            font-weight: bold;
            box-sizing: border-box;
            cursor: pointer;
            text-align: center;
        }
        .btn-action {
            background: var(--orange);
            color: #000;
            margin-top: 8px;
        }
        .btn-action:hover {
            background: #e64c00;
        }
        .btn-green {
            background: var(--green);
            color: #000;
            border-color: var(--green);
        }
        .btn-danger {
            background: var(--red);
            color: #fff;
            border-color: var(--red);
            padding: 12px;
            font-size: 0.9rem;
        }
        .btn-group {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }
        .telemetry-row {
            color: var(--green);
            font-size: 0.75rem;
            margin-bottom: 8px;
        }
        .nodes-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 6px;
        }
        .node-btn {
            background: rgba(0, 255, 102, 0.05);
            border: 1px solid var(--green);
            color: var(--green);
            font-size: 0.7rem;
            padding: 6px;
            text-align: center;
            border-radius: 2px;
        }
        .drop-zone {
            border: 1px dashed var(--orange);
            padding: 20px;
            text-align: center;
            color: var(--orange);
            font-size: 0.8rem;
            margin-bottom: 8px;
        }
        .drop-zone span {
            display: block;
            color: var(--text-dim);
            font-size: 0.7rem;
            margin-top: 4px;
        }
    </style>
</head>
<body>

    <div class="header">
        <h1>X9 // DUAL-TRACK VAULT</h1>
        <div class="subtitle">TACTICAL & ENTERPRISE ENGINE</div>
    </div>

    <div class="card">
        <div class="card-title">ACTIVE ROLE</div>
        <select class="select-box">
            <option>ADMINISTRATOR (FULL CONTROL)</option>
            <option>OPERATOR (RESTRICTED)</option>
        </select>
    </div>

    <div class="card">
        <div class="card-title">
            TACTICAL DEADMAN & ZEROIZATION
            <span class="badge">ARMED (51S)</span>
        </div>
        <div class="btn-group">
            <button class="btn">ARM DEADMAN (2M)</button>
            <button class="btn">PING HEARTBEAT</button>
        </div>
    </div>

    <div class="card">
        <div class="card-title">
            SUBNET MESH TELEMETRY
            <span class="badge">AUTONOMOUS HEALING</span>
        </div>
        <div class="telemetry-row">
            RAM: 0.00 MB | SOCKETS: 10 | DEADMAN: ARMED<br>
            v2 Burst Engine: PORT 9200 (&gt;110 MB/s) | Radio: PORT 9201
        </div>
        <div class="nodes-grid">
            <div class="node-btn">NODE 9101 &#9679;</div>
            <div class="node-btn">NODE 9102 &#9679;</div>
            <div class="node-btn">NODE 9103 &#9679;</div>
            <div class="node-btn">NODE 9104 &#9679;</div>
        </div>
    </div>

    <div class="card">
        <div class="card-title">BINARY SHARDING ENGINE</div>
        <div class="drop-zone">
            DROP FILE TO SHARD & PROPAGATE
            <span>Click here or drop files to dynamically shard into RAM</span>
        </div>
        <button class="btn btn-action">START WEBRTC MESH PEER</button>
        <div style="color: var(--orange); font-size: 0.7rem; text-align: center; margin-top: 6px;">
            WebRTC State: BROADCASTING OFFER...
        </div>
    </div>

    <div class="card">
        <div class="card-title">
            VAULT OBJECTS & LINEAGE
            <button class="btn btn-green" style="width: auto; padding: 2px 8px; font-size: 0.65rem;">SYNC MESH</button>
        </div>
        <div style="color: var(--text-dim); font-size: 0.75rem; text-align: center; padding: 10px;">
            NO ACTIVE OBJECTS IN VOLATILE RAM
        </div>
    </div>

    <button class="btn btn-danger">ZEROIZE & PURGE ALL RAM</button>

</body>
</html>
"""

class DualTrackHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(HTML.encode('utf-8'))

with socketserver.TCPServer(("0.0.0.0", PORT), DualTrackHandler) as httpd:
    print(f"[+] X9 Dual-Track Tactical Server online at http://127.0.0.1:{PORT}")
    httpd.serve_forever()
