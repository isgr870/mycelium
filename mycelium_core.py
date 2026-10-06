import asyncio
import json
import os
import sys
import argparse
import uuid
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import packet_mesh

PEERS_FILE = Path("peers.json")

class PeerStore:
    @staticmethod
    def load():
        if PEERS_FILE.exists() and PEERS_FILE.stat().st_size > 0:
            try:
                with open(PEERS_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    @staticmethod
    def save(peers):
        with open(PEERS_FILE, "w") as f:
            json.dump(peers, f, indent=2)

class UnifiedNode:
    def __init__(self, node_id=None, tcp_port=9001, http_port=8081):
        self.node_id = node_id or str(uuid.uuid4())[:12]
        self.tcp_port = tcp_port
        self.http_port = http_port
        self.peers = PeerStore.load()

    def register_peer(self, peer_id, addr):
        if peer_id != self.node_id and peer_id not in self.peers:
            self.peers[peer_id] = addr
            PeerStore.save(self.peers)
            print(f"[+] Synced new peer to peers.json: {peer_id} @ {addr}")

    async def handle_tcp_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        try:
            header_bytes = await reader.readexactly(packet_mesh.HEADER_SIZE)
            p_type, p_len, p_crc = packet_mesh.unpack_header(header_bytes)
            
            payload_bytes = await reader.readexactly(p_len)
            data = packet_mesh.verify_and_unpack_payload(payload_bytes, p_crc)
            
            sender_id = data.get("source", "unknown")
            print(f"[*] [TCP Frame Received] Type: {p_type} | From: {sender_id} | Payload: {data}")
            
            if sender_id != "unknown":
                self.register_peer(sender_id, f"{addr[0]}:{self.tcp_port}")
                
            response_frame = packet_mesh.pack_packet(
                packet_mesh.TYPE_MSG, 
                {"status": "ack", "node_id": self.node_id}
            )
            writer.write(response_frame)
            await writer.drain()
        except Exception as e:
            print(f"[!] Binary packet error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    def start_http_api(self):
        node_ref = self
        class HTTPHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args): return
            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/api/status":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    resp = {
                        "node_id": node_ref.node_id,
                        "tcp_port": node_ref.tcp_port,
                        "http_port": node_ref.http_port,
                        "known_peers": list(node_ref.peers.keys())
                    }
                    self.wfile.write(json.dumps(resp).encode())
                else:
                    self.send_response(404)
                    self.end_headers()

        server = HTTPServer(('127.0.0.1', self.http_port), HTTPHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"[+] HTTP Telemetry API live on port {self.http_port}")

    async def run(self):
        self.start_http_api()
        server = await asyncio.start_server(self.handle_tcp_client, '127.0.0.1', self.tcp_port)
        print(f"[+] Mycelium v8 Unified Node active [ID: {self.node_id}]")
        print(f"    Listening: TCP {self.tcp_port} (Binary Wire) | HTTP {self.http_port} (Telemetry)")
        async with server:
            await server.serve_forever()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tcp", type=int, default=9001)
    parser.add_argument("--http", type=int, default=8081)
    parser.add_argument("--id", type=str, default=None)
    args = parser.parse_args()

    node = UnifiedNode(node_id=args.id, tcp_port=args.tcp, http_port=args.http)
    try:
        asyncio.run(node.run())
    except KeyboardInterrupt:
        print("\n[*] Node shutting down cleanly.")
