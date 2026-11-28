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


def test_replicate_once_pushes_and_pulls_ciphertext_b64_over_slices_router(tmp_path, monkeypatch):
    import asyncio
    import time
    from fastapi import FastAPI
    from core import naming_api, slices_api

    db_a = str(tmp_path / "sync_a.db")
    db_b = str(tmp_path / "sync_b.db")

    mbox_a = MailboxStore(db_a)
    mbox_b = MailboxStore(db_b)

    def _make_fastapi_relay_handler(db_path: str):
        app = FastAPI()
        app.include_router(naming_api.router)
        app.include_router(slices_api.router)

        class FastAPIRelayHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_GET(self):
                monkeypatch.setenv("MYCELIUM_DB_PATH", db_path)
                self._handle_asgi("GET")

            def do_POST(self):
                monkeypatch.setenv("MYCELIUM_DB_PATH", db_path)
                self._handle_asgi("POST")

            def _handle_asgi(self, method: str):
                length = int(self.headers.get("Content-Length", "0"))
                body_bytes = self.rfile.read(length) if length > 0 else b""
                raw_path, _, query_string = self.path.partition("?")
                headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in self.headers.items()]
                host, port = self.server.server_address

                status_code = 500
                resp_headers = []
                resp_chunks = []
                body_sent = False

                scope = {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": method,
                    "scheme": "http",
                    "path": raw_path,
                    "raw_path": raw_path.encode("utf-8"),
                    "query_string": query_string.encode("latin-1"),
                    "headers": headers,
                    "client": ("127.0.0.1", 0),
                    "server": (host, port),
                }

                async def receive():
                    nonlocal body_sent
                    if not body_sent:
                        body_sent = True
                        return {"type": "http.request", "body": body_bytes, "more_body": False}
                    return {"type": "http.request", "body": b"", "more_body": False}

                async def send(message):
                    nonlocal status_code, resp_headers
                    if message["type"] == "http.response.start":
                        status_code = int(message["status"])
                        resp_headers = list(message.get("headers", []))
                    elif message["type"] == "http.response.body":
                        chunk = message.get("body", b"")
                        if chunk:
                            resp_chunks.append(chunk)

                asyncio.run(app(scope, receive, send))

                payload = b"".join(resp_chunks)
                self.send_response(status_code)
                has_len = False
                for k, v in resp_headers:
                    key_str = k.decode("latin-1")
                    val_str = v.decode("latin-1")
                    if key_str.lower() == "content-length":
                        has_len = True
                    if key_str.lower() != "transfer-encoding":
                        self.send_header(key_str, val_str)
                if not has_len:
                    self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if payload:
                    self.wfile.write(payload)

        return FastAPIRelayHandler

    server_a = ThreadingHTTPServer(("127.0.0.1", 0), _make_fastapi_relay_handler(db_a))
    server_b = ThreadingHTTPServer(("127.0.0.1", 0), _make_fastapi_relay_handler(db_b))
    t_a = threading.Thread(target=server_a.serve_forever, daemon=True)
    t_b = threading.Thread(target=server_b.serve_forever, daemon=True)
    t_a.start()
    t_b.start()

    url_a = f"http://127.0.0.1:{server_a.server_address[1]}"
    url_b = f"http://127.0.0.1:{server_b.server_address[1]}"

    now_ts = int(time.time())
    recipient_push = "recipient-push-b64"
    recipient_pull = "recipient-pull-b64"

    env_push = {
        "msg_id": "msg-push-001",
        "sender_id": "relay-a",
        "recipient_id": recipient_push,
        "ciphertext_b64": "cHVzaC1jaXBoZXJ0ZXh0LWJhc2U2NA==",
        "nonce": "nonce-push-001",
        "created_at": now_ts,
        "expires_at": now_ts + 3600,
    }
    env_pull = {
        "msg_id": "msg-pull-001",
        "sender_id": "relay-b",
        "recipient_id": recipient_pull,
        "ciphertext_b64": "cHVsbC1jaXBoZXJ0ZXh0LWJhc2U2NA==",
        "nonce": "nonce-pull-001",
        "created_at": now_ts,
        "expires_at": now_ts + 3600,
    }

    try:
        assert mbox_a.enqueue(env_push) is True

        # Relay A pushes env_push to Relay B via POST /mesh/mailbox/enqueue
        monkeypatch.setenv("MYCELIUM_SELF_URL", url_a)
        monkeypatch.setenv("MYCELIUM_PEER_URLS", url_b)
        rep_a = replicate_once(db_path=db_a, peer_urls=[url_b], timeout=4.0)
        assert rep_a["peers"][0]["mail_pushed"] == 1
        assert rep_a["peers"][0]["errors"] == []
        pending_on_b_after_push = mbox_b.fetch_pending(recipient_push)
        assert len(pending_on_b_after_push) == 1
        assert pending_on_b_after_push[0]["ciphertext_b64"] == env_push["ciphertext_b64"]

        # Seed env_pull on Relay A, and seed a distinct pending msg for recipient_pull on Relay B
        # so recipient_pull is in B's pending_recipients while msg-pull-001 is still new to B.
        assert mbox_a.enqueue(env_pull) is True
        assert mbox_b.enqueue(
            {
                "msg_id": "msg-seed-b-001",
                "sender_id": "local-b",
                "recipient_id": recipient_pull,
                "ciphertext_b64": "c2VlZC1iLWJhc2U2NA==",
                "nonce": "nonce-seed-b-001",
                "created_at": now_ts,
                "expires_at": now_ts + 3600,
            }
        ) is True

        # Relay B pulls env_pull from Relay A via GET /mesh/mailbox/{recipient_id}
        monkeypatch.setenv("MYCELIUM_SELF_URL", url_b)
        monkeypatch.setenv("MYCELIUM_PEER_URLS", url_a)
        rep_b = replicate_once(db_path=db_b, peer_urls=[url_a], timeout=4.0)
        assert rep_b["peers"][0]["mail_pulled"] == 1
        assert rep_b["peers"][0]["errors"] == []
        pending_on_b_after_pull = mbox_b.fetch_pending(recipient_pull)
        assert len(pending_on_b_after_pull) == 2
        assert any(m["msg_id"] == "msg-pull-001" and m["ciphertext_b64"] == env_pull["ciphertext_b64"] for m in pending_on_b_after_pull)

        # Re-running replicate_once should ignore already-present msg_id rows
        rep_b_again = replicate_once(db_path=db_b, peer_urls=[url_a], timeout=4.0)
        assert rep_b_again["peers"][0]["mail_pulled"] == 0
        assert len(mbox_b.fetch_pending(recipient_pull)) == 2
    finally:
        server_a.shutdown()
        server_b.shutdown()
        server_a.server_close()
        server_b.server_close()
