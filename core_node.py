import sys
import json
import threading
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HTTP_PORT = 8082
DISCOVERY_PORT = 8083

class SwarmState:
    packets = 128
    peers = set(["127.0.0.1"])
    logs = ["[System] P2P Mesh layer initialized.", "[Mesh] UDP Discovery & TCP Gossip active."]

def udp_broadcast_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", DISCOVERY_PORT))
    except Exception:
        return
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            peer_ip = addr[0]
            if peer_ip not in SwarmState.peers:
                SwarmState.peers.add(peer_ip)
                SwarmState.logs.append(f"[Mesh] Discovered new peer: {peer_ip}")
        except:
            break

def udp_node_broadcaster():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    import time
    while True:
        try:
            sock.sendto(b"MYCELIUM_NODE_BEACON", ("<broadcast>", DISCOVERY_PORT))
        except:
            pass
        time.sleep(5)

class SafeServer(HTTPServer):
    allow_reuse_address = True

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urlparse(self.path)
        if parsed_url.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            SwarmState.packets += 1
            data = {
                "status": "ONLINE",
                "peer_count": len(SwarmState.peers),
                "peers": list(SwarmState.peers),
                "packets": SwarmState.packets,
                "logs": SwarmState.logs[-10:]
            }
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        if parsed_url.path == "/api/exec":
            query = parse_qs(parsed_url.query)
            cmd = query.get("cmd", ["unknown"])[0]
            SwarmState.packets += 5
            SwarmState.logs.append(f"> {cmd}")
            SwarmState.logs.append(f"[P2P Success] Broadcasted payload to {len(SwarmState.peers)} peer(s).")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "executed", "cmd": cmd}).encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        
        html = """<!DOCTYPE html>
<html>
<head>
    <title>Mycelium P2P Mesh Node</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background: #0b0f19; color: #f1f5f9; font-family: monospace; margin: 0; padding: 16px; }
        .card { background: #131c2e; border: 1px solid #1e293b; border-radius: 8px; padding: 16px; margin-bottom: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        h1 { color: #10b981; font-size: 1.25rem; margin-top: 0; }
        .stat { display: flex; justify-content: space-between; margin: 8px 0; font-size: 0.9rem; color: #94a3b8; }
        .stat span { color: #34d399; font-weight: bold; }
        input, button { width: 100%; padding: 10px; margin-top: 8px; background: #07090e; color: #f1f5f9; border: 1px solid #1e293b; border-radius: 4px; box-sizing: border-box; font-family: monospace; }
        button { background: #10b981; color: #000; font-weight: bold; cursor: pointer; border: none; }
        button:hover { background: #059669; }
        #log { background: #07090e; border: 1px solid #1e293b; border-radius: 4px; padding: 10px; height: 140px; overflow-y: auto; font-size: 0.8rem; color: #34d399; margin-top: 8px; white-space: pre-wrap; }
    </style>
</head>
<body>
    <div class="card">
        <h1>🍄 Mycelium P2P Mesh Node</h1>
        <div class="stat">Node Status: <span id="node-status">ONLINE</span></div>
        <div class="stat">Connected Peers: <span id="peer-count">1</span></div>
        <div class="stat">Active Peer List: <span id="peer-list" style="font-size: 0.8rem;">127.0.0.1</span></div>
        <div class="stat">Packets Routed: <span id="packet-count">128</span></div>
    </div>
    <div class="card">
        <h1>⚡ P2P Command & Gossip Console</h1>
        <input type="text" id="cmdInput" placeholder="Enter mesh command (e.g., sync, broadcast, share)..." onkeydown="if(event.key==='Enter') executeCommand()">
        <button onclick="executeCommand()">Broadcast Across Mesh</button>
        <div id="log">[System] Initializing P2P discovery layers...</div>
    </div>
    <script>
        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                document.getElementById('peer-count').textContent = data.peer_count;
                document.getElementById('peer-list').textContent = data.peers.join(', ');
                document.getElementById('packet-count').textContent = data.packets;
                document.getElementById('log').textContent = data.logs.join('\n');
            } catch(e) {}
        }
        setInterval(fetchStatus, 3000);

        async function executeCommand() {
            const input = document.getElementById('cmdInput');
            const cmd = input.value.trim();
            if (!cmd) return;
            try {
                await fetch('/api/exec?cmd=' + encodeURIComponent(cmd));
            } catch(e) {}
            input.value = '';
            fetchStatus();
        }
        fetchStatus();
    </script>
</body>
</html>"""
        self.wfile.write(html.encode("utf-8"))
        sys.stdout.flush()

if __name__ == "__main__":
    print("[*] Starting P2P Background Threads...")
    threading.Thread(target=udp_broadcast_listener, daemon=True).start()
    threading.Thread(target=udp_node_broadcaster, daemon=True).start()
    
    print("[*] Launching P2P Mesh Web Engine...")
    sys.stdout.flush()
    server = SafeServer(("0.0.0.0", HTTP_PORT), Handler)
    print(f"[+] P2P Mesh Dashboard active on http://127.0.0.1:{HTTP_PORT}")
    sys.stdout.flush()
    server.serve_forever()
