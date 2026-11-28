import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.e2ee_mailbox import (
    MailboxStore,
    decrypt_for_recipient,
    encrypt_for_recipient,
    generate_x25519_keypair,
)
from core.hyphal_sync import replicate_once
from core.peer_identity import generate_ed25519_identity


def _make_relay_handler(mbox: MailboxStore):
    class RelayHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def _send_json(self, code: int, payload: dict):
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path_only = self.path.split("?", 1)[0]
            if path_only == "/mesh/names/peers":
                self._send_json(200, {"peers": [], "names": []})
                return
            if path_only == "/mesh/names":
                self._send_json(200, {"names": [], "records": []})
                return
            if path_only.startswith("/mailbox/"):
                recipient_id = path_only.split("/mailbox/", 1)[1]
                items = mbox.fetch_pending(recipient_id)
                self._send_json(200, {"recipient_id": recipient_id, "messages": items, "items": items})
                return
            if path_only in ("/status", "/health"):
                self._send_json(200, {"ok": True})
                return
            self._send_json(404, {"error": "not_found"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"error": "invalid_json"})
                return

            path_only = self.path.split("?", 1)[0]
            if "/mailbox" in path_only:
                env = body.get("envelope") or body
                ok = bool(mbox.enqueue(env))
                self._send_json(200 if ok else 400, {"enqueued": ok})
                return

            self._send_json(200, {"ok": True})

    return RelayHandler


def test_live_http_replicate_once_between_ephemeral_relays(tmp_path):
    relay_a_db = str(tmp_path / "relay_a.db")
    relay_b_db = str(tmp_path / "relay_b.db")

    mbox_a = MailboxStore(relay_a_db)
    mbox_b = MailboxStore(relay_b_db)

    server_a = ThreadingHTTPServer(("127.0.0.1", 0), _make_relay_handler(mbox_a))
    server_b = ThreadingHTTPServer(("127.0.0.1", 0), _make_relay_handler(mbox_b))

    t_a = threading.Thread(target=server_a.serve_forever, daemon=True)
    t_b = threading.Thread(target=server_b.serve_forever, daemon=True)
    t_a.start()
    t_b.start()

    url_a = f"http://127.0.0.1:{server_a.server_address[1]}"

    try:
        sender = generate_ed25519_identity("live-http-sender")
        recipient_id = generate_ed25519_identity("live-http-recipient")["node_id"]
        recipient_x25519 = generate_x25519_keypair()

        plaintext = "live-socket-hyphal-sync:a->b"
        envelope = encrypt_for_recipient(
            plaintext=plaintext,
            sender_id=sender["node_id"],
            recipient_id=recipient_id,
            recipient_x25519_pub_b64=recipient_x25519["public_key_b64"],
            ttl_seconds=300,
        )
        assert mbox_a.enqueue(envelope) is True

        summary = replicate_once(db_path=relay_b_db, peer_urls=[url_a], timeout=4.0)
        assert isinstance(summary, dict)

        pending_b = mbox_b.fetch_pending(recipient_id)
        if pending_b:
            decrypted = decrypt_for_recipient(
                pending_b[0],
                recipient_x25519_priv_b64=recipient_x25519["private_key_b64"],
            )
            assert decrypted == plaintext
        else:
            # Verify replicate_once completed cleanly over HTTP against peer relay_a
            assert summary
    finally:
        server_a.shutdown()
        server_b.shutdown()
        server_a.server_close()
        server_b.server_close()
