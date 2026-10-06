import sys, os, argparse, json, threading, socket, uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

class MeshDaemon:
    def __init__(self, tcp_port, http_port, data_dir, bootstrap_port=None):
        self.tcp_port = tcp_port
        self.http_port = http_port
        self.data_dir = os.path.expanduser(data_dir)
        self.bootstrap_port = bootstrap_port
        
        os.makedirs(self.data_dir, exist_ok=True)
        self.id_file = os.path.join(self.data_dir, "node_id.txt")
        if os.path.exists(self.id_file):
            with open(self.id_file, "r") as f:
                self.node_id = f.read().strip()
        else:
            self.node_id = uuid.uuid4().hex
            with open(self.id_file, "w") as f:
                f.write(self.node_id)
                
        self.known_nodes = []
        if self.bootstrap_port:
            self.known_nodes.append(f"127.0.0.1:{self.bootstrap_port}")

    def start_tcp_listener(self):
        def handle_tcp():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", self.tcp_port))
                s.listen(5)
                while True:
                    conn, addr = s.accept()
                    data = conn.recv(1024)
                    if data:
                        try:
                            msg = json.loads(data.decode())
                            if msg.get("type") == "gossip":
                                peer = msg.get("from")
                                if peer and peer not in self.known_nodes:
                                    self.known_nodes.append(peer)
                        except Exception:
                            pass
                    conn.close()
            except Exception as e:
                print(f"[TCP ERR] {e}")

        t = threading.Thread(target=handle_tcp, daemon=True)
        t.start()

    def start_http_server(self):
        daemon_self = self

        class RequestHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/api/status":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    resp = {
                        "node_id": daemon_self.node_id,
                        "known_nodes": daemon_self.known_nodes,
                        "tcp_port": daemon_self.tcp_port,
                        "http_port": daemon_self.http_port
                    }
                    self.wfile.write(json.dumps(resp).encode())
                elif parsed.path == "/api/send":
                    params = parse_qs(parsed.query)
                    msg = params.get("msg", [""])[0]
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    resp = {"status": "dispatched", "message": msg, "node_id": daemon_self.node_id}
                    self.wfile.write(json.dumps(resp).encode())
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                return

        server = HTTPServer(("127.0.0.1", self.http_port), RequestHandler)
        print(f"[*] Node {self.node_id[:8]} listening on TCP {self.tcp_port} & HTTP {self.http_port}")
        sys.stdout.flush()
        server.serve_forever()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mycelium Mesh Node Daemon")
    parser.add_argument("--tcp", type=int, required=True)
    parser.add_argument("--http", type=int, required=True)
    parser.add_argument("--dir", type=str, required=True)
    parser.add_argument("--bootstrap-port", type=int, default=None)
    
    args = parser.parse_args()
    
    daemon = MeshDaemon(
        tcp_port=args.tcp,
        http_port=args.http,
        data_dir=args.dir,
        bootstrap_port=args.bootstrap_port
    )
    daemon.start_tcp_listener()
    daemon.start_http_server()
