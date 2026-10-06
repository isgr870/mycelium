import socket
import threading
import json
import time
import uuid
import sys
import argparse

BROADCAST_PORT = 9999
BUFFER_SIZE = 4096
PEER_TIMEOUT = 10  # Seconds before marking a peer offline

class MyceliumNode:
    def __init__(self, port=0):
        self.node_id = str(uuid.uuid4())[:8]
        self.peers = {}  # {node_id: {"address": (ip, port), "last_seen": timestamp}}
        self.seen_messages = set()
        
        # Setup UDP socket for peer communication and broadcast
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0', port))
        self.local_port = self.sock.getsockname()[1]

        self.running = True

    def start(self):
        print(f"[*] Launching Mycelium Node [{self.node_id}] listening on port {self.local_port}...")
        
        # Start background threads
        threading.Thread(target=self._listen_loop, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        threading.Thread(target=self._reap_peers_loop, daemon=True).start()
        
        self._cli_loop()

    def _listen_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(BUFFER_SIZE)
                packet = json.loads(data.decode('utf-8'))
                sender_id = packet.get("sender")
                
                if sender_id == self.node_id:
                    continue  # Ignore self-broadcasts
                
                # Register or update peer location
                sender_port = packet.get("port", addr[1])
                self.peers[sender_id] = {
                    "address": (addr[0], sender_port),
                    "last_seen": time.time()
                }

                p_type = packet.get("type")
                if p_type == "HEARTBEAT":
                    pass  # Handled implicitly by updating last_seen
                elif p_type == "DATA":
                    self._handle_data_packet(packet)
            except Exception:
                pass

    def _heartbeat_loop(self):
        """Broadcasts presence periodically to local broadcast subnet."""
        while self.running:
            payload = {
                "type": "HEARTBEAT",
                "sender": self.node_id,
                "port": self.local_port
            }
            try:
                self.sock.sendto(json.dumps(payload).encode('utf-8'), ('<broadcast>', BROADCAST_PORT))
            except Exception:
                pass
            time.sleep(3)

    def _reap_peers_loop(self):
        """Prunes inactive nodes from local routing table."""
        while self.running:
            now = time.time()
            expired = [pid for pid, info in self.peers.items() if now - info["last_seen"] > PEER_TIMEOUT]
            for pid in expired:
                del self.peers[pid]
            time.sleep(5)

    def _handle_data_packet(self, packet):
        msg_id = packet.get("msg_id")
        if msg_id in self.seen_messages:
            return  # Drop duplicate packets to prevent loop storms

        self.seen_messages.add(msg_id)
        sender = packet.get("sender")
        payload = packet.get("payload")
        hops = packet.get("hops", 0)

        print(f"\n[RECEIVED via Hop #{hops}] From {sender}: {payload}\nMycelium> ", end="")

        # Forward / Flood packet to known peers
        packet["hops"] = hops + 1
        self._flood(packet)

    def _flood(self, packet):
        encoded = json.dumps(packet).encode('utf-8')
        for pid, peer in list(self.peers.items()):
            try:
                self.sock.sendto(encoded, peer["address"])
            except Exception:
                pass

    def broadcast_message(self, message):
        msg_id = str(uuid.uuid4())
        self.seen_messages.add(msg_id)
        
        packet = {
            "type": "DATA",
            "msg_id": msg_id,
            "sender": self.node_id,
            "hops": 1,
            "payload": message
        }
        self._flood(packet)
        # Also broadcast via UDP broadcast socket for undiscovered nodes on fixed port
        try:
            self.sock.sendto(json.dumps(packet).encode('utf-8'), ('<broadcast>', BROADCAST_PORT))
        except Exception:
            pass

    def _cli_loop(self):
        time.sleep(1)
        print("\n--- Mycelium Mesh Interactive Shell ---")
        print("Commands: /peers (list network), /send <msg>, /exit\n")
        
        while self.running:
            try:
                cmd = input("Mycelium> ").strip()
                if cmd == "/peers":
                    print(f"\nActive Mesh Peers ({len(self.peers)}):")
                    for pid, info in self.peers.items():
                        age = int(time.time() - info["last_seen"])
                        print(f"  - Node [{pid}] @ {info['address'][0]}:{info['address'][1]} (Last seen {age}s ago)")
                    print()
                elif cmd.startswith("/send "):
                    msg = cmd[6:].strip()
                    if msg:
                        self.broadcast_message(msg)
                        print(f"[*] Message flooded to mesh.")
                elif cmd == "/exit":
                    self.running = False
                    break
            except (KeyboardInterrupt, EOFError):
                self.running = False
                break

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mycelium Mesh Local Node")
    parser.add_argument("--port", type=int, default=BROADCAST_PORT, help="Port to listen on")
    args = parser.parse_args()
    
    node = MyceliumNode(port=args.port)
    node.start()
