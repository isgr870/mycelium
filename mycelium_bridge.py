import socket
import threading
import json
import time
import struct
import hashlib
import base64
import http.server
import socketserver
import sys

HTTP_PORT = 8095
WS_PORT = 8096
UDP_PORT = 9999
BUFFER_SIZE = 4096

ws_clients = set()
ws_clients_lock = threading.Lock()

def encode_ws_frame(payload_str):
    payload_bytes = payload_str.encode('utf-8')
    length = len(payload_bytes)
    frame = bytearray([0x81])
    if length <= 125:
        frame.append(length)
    elif length <= 65535:
        frame.append(126)
        frame.extend(struct.pack(">H", length))
    else:
        frame.append(127)
        frame.extend(struct.pack(">Q", length))
    frame.extend(payload_bytes)
    return bytes(frame)

def decode_ws_frame(data):
    if len(data) < 2:
        return None
    second_byte = data[1]
    length = second_byte & 127
    index = 2
    if length == 126:
        length = struct.unpack(">H", data[2:4])[0]
        index = 4
    elif length == 127:
        length = struct.unpack(">Q", data[2:10])[0]
        index = 10
    masks = data[index:index+4]
    index += 4
    raw_payload = data[index:index+length]
    return bytearray(b ^ masks[i % 4] for i, b in enumerate(raw_payload)).decode('utf-8', errors='ignore')

def broadcast_to_websockets(data_dict):
    payload = json.dumps(data_dict)
    frame = encode_ws_frame(payload)
    with ws_clients_lock:
        dead_clients = set()
        for client in ws_clients:
            try:
                client.sendall(frame)
            except Exception:
                dead_clients.add(client)
        ws_clients.difference_update(dead_clients)

def handle_ws_client(conn, addr, udp_sock):
    try:
        request = conn.recv(2048).decode('utf-8', errors='ignore')
        key = None
        for line in request.split("\r\n"):
            if line.startswith("Sec-WebSocket-Key:"):
                key = line.split(":")[1].strip()
                break
        if not key:
            conn.close()
            return
        MAGIC_STRING = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        accept_key = base64.b64encode(hashlib.sha1((key + MAGIC_STRING).encode('utf-8')).digest()).decode('utf-8')
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key}\r\n\r\n"
        )
        conn.sendall(response.encode('utf-8'))
        with ws_clients_lock:
            ws_clients.add(conn)
        while True:
            data = conn.recv(BUFFER_SIZE)
            if not data:
                break
            msg_str = decode_ws_frame(data)
            if msg_str:
                try:
                    msg_obj = json.loads(msg_str)
                    udp_sock.sendto(json.dumps(msg_obj).encode('utf-8'), ('127.0.0.1', UDP_PORT))
                except Exception:
                    pass
    except Exception:
        pass
    finally:
        with ws_clients_lock:
            ws_clients.discard(conn)
        conn.close()

def start_websocket_server(udp_sock):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', WS_PORT))
    server.listen(10)
    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_ws_client, args=(conn, addr, udp_sock), daemon=True).start()

def start_udp_listener(udp_sock):
    while True:
        try:
            data, addr = udp_sock.recvfrom(BUFFER_SIZE)
            packet = json.loads(data.decode('utf-8'))
            
            # Broadcast CONTROL packets to connected WebSockets
            if packet.get('type') == 'CONTROL':
                broadcast_to_websockets({
                    "event": "CONTROL",
                    "command": packet.get("command")
                })
                continue

            telemetry_event = {
                "event": "UDP_PACKET",
                "sender": packet.get("sender", f"node_{addr[1]}"),
                "hops": packet.get("hops", 0),
                "payload": packet.get("payload", ""),
                "type": packet.get("type", "DATA"),
                "addr": f"{addr[0]}:{addr[1]}",
                "timestamp": time.strftime("%H:%M:%S")
            }
            broadcast_to_websockets(telemetry_event)
        except Exception:
            pass

HTML_CANVAS_APP = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VERLET HYPHAE MESH // v7.12 BRIDGE</title>
    <style>
        * { box-sizing: border-box; }
        body { margin: 0; padding: 12px; background: #06090e; color: #22d3ee; font-family: monospace; }
        .header { display: flex; justify-content: space-between; margin-bottom: 8px; color: #20dbad; }
        .canvas-container { width: 100%; height: 380px; background: #080d14; border: 1px solid #13383a; border-radius: 4px; overflow: hidden; }
        canvas { width: 100%; height: 100%; display: block; }
        .status-bar { display: flex; justify-content: space-between; font-size: 11px; margin: 8px 0; color: #64748b; }
        .btn-row { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 6px; margin-top: 8px; }
        button { background: #071518; border: 1px solid #13383a; color: #20dbad; padding: 10px 4px; font-weight: bold; border-radius: 4px; cursor: pointer; font-size: 11px; }
        input { flex: 1; background: #060a10; border: 1px solid #13383a; padding: 10px; color: #22d3ee; }
        .ws-indicator { font-weight: bold; }
        .ws-connected { color: #4ade80; }
        .ws-disconnected { color: #f43f5e; }
    </style>
</head>
<body>
    <div class="header">
        <div>VERLET HYPHAE MESH // v7.12</div>
        <div id="ws-status" class="ws-indicator ws-disconnected">WS: OFF</div>
    </div>
    <div class="canvas-container">
        <canvas id="meshCanvas"></canvas>
    </div>
    <div class="status-bar">
        <div>MY OWN INTERNET // WS BRIDGE</div>
        <div>ACTIVE PEERS: <span id="peer-count" style="color:#20dbad;">0</span></div>
    </div>
    <div style="display:flex; gap:8px;">
        <input type="text" id="msg-input" placeholder="Type message to broadcast...">
        <button style="background:#072622; border-color:#20dbad;" onclick="sendBroadcast()">BROADCAST</button>
    </div>
    <div class="btn-row">
        <button onclick="sendControl('SPORE')">+ SPORE</button>
        <button onclick="sendControl('MUTATE')">MUTATE</button>
        <button onclick="sendControl('HIBERNATE')">HIBERNATE</button>
        <button style="color:#f43f5e; border-color:#581c2d;" onclick="sendControl('FLUSH')">FLUSH</button>
    </div>

    <script>
        const canvas = document.getElementById('meshCanvas');
        const ctx = canvas.getContext('2d');
        let width = canvas.width = canvas.clientWidth;
        let height = canvas.height = canvas.clientHeight;

        let spores = {};
        let pulses = [];
        let ws;
        let isHibernating = false;

        function connectWS() {
            ws = new WebSocket('ws://' + location.hostname + ':8096');
            ws.onopen = () => {
                const el = document.getElementById('ws-status');
                el.innerText = 'WS: LIVE';
                el.className = 'ws-indicator ws-connected';
            };
            ws.onclose = () => {
                const el = document.getElementById('ws-status');
                el.innerText = 'WS: OFF';
                el.className = 'ws-indicator ws-disconnected';
                setTimeout(connectWS, 2000);
            };
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.event === "UDP_PACKET") {
                    handleUDPTelemetry(data);
                } else if (data.event === "CONTROL") {
                    handleControlCommand(data.command);
                }
            };
        }

        function handleUDPTelemetry(pkt) {
            let id = pkt.sender;
            if (!spores[id]) {
                spores[id] = {
                    x: Math.random() * (width - 40) + 20,
                    y: Math.random() * (height - 40) + 20,
                    vx: (Math.random() - 0.5) * 2,
                    vy: (Math.random() - 0.5) * 2,
                    color: '#' + Math.floor(Math.random()*16777215).toString(16)
                };
            }
            pulses.push({
                x: spores[id].x,
                y: spores[id].y,
                r: 4,
                maxR: 40,
                alpha: 1.0,
                color: spores[id].color
            });
            document.getElementById('peer-count').innerText = Object.keys(spores).length;
        }

        function handleControlCommand(cmd) {
            if (cmd === "SPORE") {
                const id = "spore_" + Math.random().toString(16).substring(2, 6);
                spores[id] = {
                    x: Math.random() * (width - 40) + 20,
                    y: Math.random() * (height - 40) + 20,
                    vx: (Math.random() - 0.5) * 3,
                    vy: (Math.random() - 0.5) * 3,
                    color: '#' + Math.floor(Math.random()*16777215).toString(16)
                };
                pulses.push({
                    x: spores[id].x,
                    y: spores[id].y,
                    r: 4,
                    maxR: 50,
                    alpha: 1.0,
                    color: '#20dbad'
                });
            } else if (cmd === "MUTATE") {
                for (let id in spores) {
                    spores[id].vx = (Math.random() - 0.5) * 5;
                    spores[id].vy = (Math.random() - 0.5) * 5;
                    spores[id].color = '#' + Math.floor(Math.random()*16777215).toString(16);
                }
            } else if (cmd === "HIBERNATE") {
                isHibernating = !isHibernating;
                for (let id in spores) {
                    if (isHibernating) {
                        spores[id].savedVx = spores[id].vx;
                        spores[id].savedVy = spores[id].vy;
                        spores[id].vx = 0;
                        spores[id].vy = 0;
                    } else {
                        spores[id].vx = spores[id].savedVx || (Math.random() - 0.5) * 2;
                        spores[id].vy = spores[id].savedVy || (Math.random() - 0.5) * 2;
                    }
                }
            } else if (cmd === "FLUSH") {
                spores = {};
                pulses = [];
            }
            document.getElementById('peer-count').innerText = Object.keys(spores).length;
        }

        function sendBroadcast() {
            const input = document.getElementById('msg-input');
            if (ws && input.value) {
                ws.send(JSON.stringify({ type: "DATA", sender: "WEB_VISUALIZER", payload: input.value }));
                input.value = '';
            }
        }

        function sendControl(cmd) {
            if (ws) {
                ws.send(JSON.stringify({ type: "CONTROL", command: cmd }));
            }
        }

        function render() {
            ctx.clearRect(0, 0, width, height);
            let keys = Object.keys(spores);
            for (let i = 0; i < keys.length; i++) {
                for (let j = i + 1; j < keys.length; j++) {
                    let s1 = spores[keys[i]];
                    let s2 = spores[keys[j]];
                    let dist = Math.hypot(s2.x - s1.x, s2.y - s1.y);
                    if (dist < 120) {
                        ctx.beginPath();
                        ctx.moveTo(s1.x, s1.y);
                        ctx.lineTo(s2.x, s2.y);
                        ctx.strokeStyle = '#13383a';
                        ctx.stroke();
                    }
                }
            }
            for (let id in spores) {
                let s = spores[id];
                s.x += s.vx; s.y += s.vy;
                if (s.x < 10 || s.x > width - 10) s.vx *= -1;
                if (s.y < 10 || s.y > height - 10) s.vy *= -1;
                ctx.beginPath();
                ctx.arc(s.x, s.y, 6, 0, Math.PI * 2);
                ctx.fillStyle = s.color || '#20dbad';
                ctx.fill();
                ctx.fillStyle = '#94a3b8';
                ctx.fillText(id, s.x + 10, s.y + 3);
            }
            for (let i = pulses.length - 1; i >= 0; i--) {
                let p = pulses[i];
                p.r += 1.5;
                p.alpha -= 0.02;
                if (p.alpha <= 0) { pulses.splice(i, 1); continue; }
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
                ctx.strokeStyle = p.color;
                ctx.globalAlpha = p.alpha;
                ctx.stroke();
                ctx.globalAlpha = 1.0;
            }
            requestAnimationFrame(render);
        }

        connectWS();
        render();
    </script>
</body>
</html>
"""

class HTTPHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(HTML_CANVAS_APP.encode("utf-8"))
    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_sock.bind(('0.0.0.0', UDP_PORT))

    threading.Thread(target=start_udp_listener, args=(udp_sock,), daemon=True).start()
    threading.Thread(target=start_websocket_server, args=(udp_sock,), daemon=True).start()

    print(f"==================================================")
    print(f" 🍄 MYCELIUM WEBSOCKET TELEMETRY BRIDGE ONLINE")
    print(f" --------------------------------------------------")
    print(f" Visualizer Dashboard: http://localhost:{HTTP_PORT}")
    print(f" WebSocket Stream:    ws://localhost:{WS_PORT}")
    print(f" UDP Mesh Interface:  0.0.0.0:{UDP_PORT}")
    print(f"==================================================")

    httpd = socketserver.TCPServer(('0.0.0.0', HTTP_PORT), HTTPHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Bridge offline.")
        sys.exit(0)
