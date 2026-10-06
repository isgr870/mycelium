import socket
import threading
import json
import time
import uuid
import sys
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

BROADCAST_PORT = 9999
BUFFER_SIZE = 4096
PEER_TIMEOUT = 10

class MyceliumMesh:
    def __init__(self, port=9999):
        self.node_id = str(uuid.uuid4())[:8]
        self.peers = {}
        self.seen_messages = set()
        self.messages_log = []
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0', port))
        self.local_port = self.sock.getsockname()[1]
        self.running = True

    def start(self):
        threading.Thread(target=self._listen_loop, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        threading.Thread(target=self._reap_peers_loop, daemon=True).start()

    def _listen_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(BUFFER_SIZE)
                packet = json.loads(data.decode('utf-8'))
                sender_id = packet.get("sender")
                
                if sender_id == self.node_id:
                    continue
                
                sender_port = packet.get("port", addr[1])
                self.peers[sender_id] = {
                    "address": f"{addr[0]}:{sender_port}",
                    "ip": addr[0],
                    "port": sender_port,
                    "last_seen": time.time()
                }

                if packet.get("type") == "DATA":
                    self._handle_data(packet)
            except Exception:
                pass

    def _heartbeat_loop(self):
        while self.running:
            payload = {"type": "HEARTBEAT", "sender": self.node_id, "port": self.local_port}
            try:
                self.sock.sendto(json.dumps(payload).encode('utf-8'), ('<broadcast>', BROADCAST_PORT))
            except Exception:
                pass
            time.sleep(3)

    def _reap_peers_loop(self):
        while self.running:
            now = time.time()
            expired = [pid for pid, info in self.peers.items() if now - info["last_seen"] > PEER_TIMEOUT]
            for pid in expired:
                del self.peers[pid]
            time.sleep(5)

    def _handle_data(self, packet):
        msg_id = packet.get("msg_id")
        if msg_id in self.seen_messages:
            return
        
        self.seen_messages.add(msg_id)
        hops = packet.get("hops", 1)
        
        entry = {
            "id": msg_id,
            "sender": packet.get("sender"),
            "hops": hops,
            "payload": packet.get("payload"),
            "timestamp": time.strftime("%H:%M:%S")
        }
        self.messages_log.append(entry)
        
        packet["hops"] = hops + 1
        self._flood(packet)

    def _flood(self, packet):
        encoded = json.dumps(packet).encode('utf-8')
        for pid, peer in list(self.peers.items()):
            try:
                self.sock.sendto(encoded, (peer["ip"], peer["port"]))
            except Exception:
                pass

    def broadcast(self, message):
        msg_id = str(uuid.uuid4())[:8]
        self.seen_messages.add(msg_id)
        
        packet = {
            "type": "DATA",
            "msg_id": msg_id,
            "sender": self.node_id,
            "hops": 1,
            "payload": message
        }
        
        entry = {
            "id": msg_id,
            "sender": f"{self.node_id} (You)",
            "hops": 0,
            "payload": message,
            "timestamp": time.strftime("%H:%M:%S")
        }
        self.messages_log.append(entry)
        
        self._flood(packet)
        try:
            self.sock.sendto(json.dumps(packet).encode('utf-8'), ('<broadcast>', BROADCAST_PORT))
        except Exception:
            pass

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Mycelium Web Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: monospace; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }
        .grid { display: grid; grid-template-columns: 1fr 2fr; gap: 20px; max-width: 1000px; margin: 0 auto; }
        .card { background: #1e293b; padding: 20px; border-radius: 8px; border: 1px solid #334155; }
        h2 { color: #38bdf8; margin-top: 0; font-size: 1.1rem; text-transform: uppercase; }
        .peer-item { padding: 8px; background: #0f172a; margin-bottom: 8px; border-radius: 4px; border-left: 3px solid #4ade80; }
        .msg-item { padding: 10px; background: #0f172a; margin-bottom: 8px; border-radius: 4px; }
        .msg-sender { color: #f43f5e; font-weight: bold; }
        .msg-self { color: #38bdf8; font-weight: bold; }
        input[type=text] { width: 70%; padding: 10px; background: #0f172a; border: 1px solid #334155; color: #fff; border-radius: 4px; }
        button { padding: 10px 18px; background: #0284c7; color: white; border: none; border-radius: 4px; cursor: pointer; }
        button:hover { background: #0369a1; }
        @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <div style="max-width: 1000px; margin: 0 auto 20px auto;">
        <h1 style="color:#4ade80; margin:0;">🍄 MYCELIUM MESH NODE</h1>
        <p style="margin: 5px 0 0 0; color:#94a3b8;">Node ID: <b id="node-id">...</b> | Port: <b id="node-port">...</b></p>
    </div>
    <div class="grid">
        <div class="card">
            <h2>Active Peers (<span id="peer-count">0</span>)</h2>
            <div id="peers-list"></div>
        </div>
        <div class="card">
            <h2>Mesh Feed</h2>
            <div id="msg-list" style="height: 300px; overflow-y: auto; margin-bottom: 15px;"></div>
            <div style="display:flex; gap:10px;">
                <input type="text" id="msg-input" placeholder="Broadcast message to mesh..." onkeydown="if(event.key==='Enter') sendMsg()">
                <button onclick="sendMsg()">Send</button>
            </div>
        </div>
    </div>
    <script>
        async function update() {
            const res = await fetch('/api/status');
            const data = await res.json();
            document.getElementById('node-id').innerText = data.node_id;
            document.getElementById('node-port').innerText = data.port;
            document.getElementById('peer-count').innerText = Object.keys(data.peers).length;
            
            let phtml = '';
            for (let pid in data.peers) {
                phtml += `<div class="peer-item"><b>[${pid}]</b><br><small>${data.peers[pid].address}</small></div>`;
            }
            document.getElementById('peers-list').innerHTML = phtml || '<div style="color:#64748b">No active peers found...</div>';

            let mhtml = '';
            data.messages.forEach(m => {
                let isSelf = m.sender.includes('(You)');
                let sClass = isSelf ? 'msg-self' : 'msg-sender';
                mhtml += `<div class="msg-item"><span class="${sClass}">${m.sender}</span> <small style="color:#64748b">[Hops: ${m.hops} | ${m.timestamp}]</small><br>${m.payload}</div>`;
            });
            const mdiv = document.getElementById('msg-list');
            mdiv.innerHTML = mhtml || '<div style="color:#64748b">No messages transmitted yet...</div>';
            mdiv.scrollTop = mdiv.scrollHeight;
        }

        async function sendMsg() {
            const input = document.getElementById('msg-input');
            const text = input.value.trim();
            if (!text) return;
            await fetch('/api/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message: text})
            });
            input.value = '';
            update();
        }

        setInterval(update, 1500);
        update();
    </script>
</body>
</html>"""

class WebHandler(BaseHTTPRequestHandler):
    mesh_node = None

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode('utf-8'))
        elif self.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            status = {
                "node_id": self.mesh_node.node_id,
                "port": self.mesh_node.local_port,
                "peers": self.mesh_node.peers,
                "messages": self.mesh_node.messages_log
            }
            self.wfile.write(json.dumps(status).encode('utf-8'))
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/api/send':
            length = int(self.headers.get('content-length', 0))
            body = self.rfile.read(length)
            data = json.loads(body.decode('utf-8'))
            msg = data.get("message")
            if msg:
                self.mesh_node.broadcast(msg)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

    def log_message(self, format, *args):
        return  # Suppress default HTTP server logs

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mycelium Web Node")
    parser.add_argument("--port", type=int, default=9999, help="UDP Mesh Port")
    parser.add_argument("--web-port", type=int, default=8000, help="Web Dashboard Port")
    args = parser.parse_args()

    mesh = MyceliumMesh(port=args.port)
    mesh.start()

    WebHandler.mesh_node = mesh
    httpd = HTTPServer(('0.0.0.0', args.web_port), WebHandler)
    
    print(f"\n==================================================")
    print(f" 🍄 MYCELIUM MESH NODE RUNNING")
    print(f" --------------------------------------------------")
    print(f" Mesh UDP Port: {mesh.local_port}")
    print(f" Web Interface: http://localhost:{args.web_port}")
    print(f"==================================================\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Shutting down node.")
