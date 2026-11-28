import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core import hyphal_sync, wan_mesh
from core.security_hardening import sign_packet


def test_gossip_accepts_https_peers_and_excludes_self_url(monkeypatch):
    wan_mesh.PEER_REGISTRY.clear()
    secret = "a" * 64
    monkeypatch.setenv("MYCELIUM_SECRET_KEY", secret)
    monkeypatch.setenv("MYCELIUM_PUBLIC_URL", "https://ug-relay.example.org")

    envelope = wan_mesh.build_signed_envelope(
        {
            "self_url": "https://ug-relay.example.org",
            "known_peers": [
                "https://ug-relay.example.org",
                "https://us-relay.example.org",
                "ftp://ignored.example.org",
            ],
        },
        secret,
    )
    sig = sign_packet(envelope, secret)

    class DummyRequest:
        def __init__(self, body: bytes, signature: str):
            self._body = body
            self.headers = {"X-Mycelium-Signature": signature}
            self.client = type("Client", (), {"host": "127.0.0.1"})()

        async def body(self) -> bytes:
            return self._body

    res = asyncio.run(wan_mesh.receive_gossip(DummyRequest(envelope, sig)))
    assert res["status"] == "accepted"
    assert "https://ug-relay.example.org" not in wan_mesh.PEER_REGISTRY
    assert "https://us-relay.example.org" in wan_mesh.PEER_REGISTRY
    assert "ftp://ignored.example.org" not in wan_mesh.PEER_REGISTRY


def test_hyphal_sync_filters_self_and_replicates_over_http(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_SELF_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv(
        "MYCELIUM_PEER_URLS",
        "http://127.0.0.1:9999,https://remote-relay.example.org,http://127.0.0.1:9998",
    )

    filtered = hyphal_sync._default_peer_urls()
    assert "http://127.0.0.1:9999" not in filtered
    assert "https://remote-relay.example.org" in filtered
    assert "http://127.0.0.1:9998" in filtered

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, format, *args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            _ = self.rfile.read(length)
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            body = b'{"peers": []}' if self.path.startswith("/mesh/names/peers") else b'{"messages": []}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        db_file = str(tmp_path / "sync_test.db")
        _ = hyphal_sync.NamingDiscoveryStore(db_file)
        _ = hyphal_sync.MailboxStore(db_file)

        report = hyphal_sync.replicate_once(
            db_path=db_file,
            peer_urls=[f"http://127.0.0.1:{port}"],
            timeout=2.0,
        )
        assert len(report["peers"]) == 1
        assert report["peers"][0]["peer"] == f"http://127.0.0.1:{port}"
        assert isinstance(report["peers"][0]["errors"], list)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
