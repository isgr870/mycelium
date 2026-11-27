#!/usr/bin/env python3
import base64
import hashlib
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def generate_x25519_keypair() -> Dict[str, str]:
    priv = x25519.X25519PrivateKey.generate()
    pub = priv.public_key()
    priv_b64 = base64.b64encode(
        priv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode("ascii")
    pub_b64 = base64.b64encode(
        pub.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    return {"private_key_b64": priv_b64, "public_key_b64": pub_b64}


def _derive_aes_key(
    priv_key: x25519.X25519PrivateKey,
    peer_pub_b64: str,
    eph_pub_raw: bytes,
    recipient_pub_raw: bytes,
) -> bytes:
    peer_pub = x25519.X25519PublicKey.from_public_bytes(base64.b64decode(peer_pub_b64))
    shared = priv_key.exchange(peer_pub)
    salt = hashlib.sha256(eph_pub_raw + recipient_pub_raw).digest()
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"mycelium-e2ee-v1",
    ).derive(shared)


def encrypt_for_recipient(
    plaintext: str,
    sender_id: str,
    recipient_id: str,
    recipient_x25519_pub_b64: str,
    ttl_seconds: int = 86400,
) -> dict:
    now = int(time.time())
    msg_id = uuid.uuid4().hex
    eph_priv = x25519.X25519PrivateKey.generate()
    eph_pub_raw = eph_priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    recipient_pub_raw = base64.b64decode(recipient_x25519_pub_b64)
    key = _derive_aes_key(eph_priv, recipient_x25519_pub_b64, eph_pub_raw, recipient_pub_raw)

    nonce = os.urandom(12)
    aad = f"{msg_id}:{sender_id}:{recipient_id}".encode("utf-8")
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad)

    return {
        "msg_id": msg_id,
        "sender_id": sender_id,
        "recipient_id": recipient_id,
        "eph_pub_b64": base64.b64encode(eph_pub_raw).decode("ascii"),
        "nonce_b64": base64.b64encode(nonce).decode("ascii"),
        "ciphertext_b64": base64.b64encode(ct).decode("ascii"),
        "created_at": now,
        "expires_at": now + max(1, int(ttl_seconds)),
    }


def decrypt_for_recipient(envelope: dict, recipient_x25519_priv_b64: str) -> str:
    rec_priv = x25519.X25519PrivateKey.from_private_bytes(base64.b64decode(recipient_x25519_priv_b64))
    rec_pub_raw = rec_priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    eph_pub_b64 = envelope["eph_pub_b64"]
    eph_pub_raw = base64.b64decode(eph_pub_b64)
    key = _derive_aes_key(rec_priv, eph_pub_b64, eph_pub_raw, rec_pub_raw)

    nonce = base64.b64decode(envelope["nonce_b64"])
    ct = base64.b64decode(envelope["ciphertext_b64"])
    aad = f"{envelope['msg_id']}:{envelope['sender_id']}:{envelope['recipient_id']}".encode("utf-8")
    pt = AESGCM(key).decrypt(nonce, ct, aad)
    return pt.decode("utf-8")


@dataclass
class MailboxStore:
    db_path: str

    def __post_init__(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS e2ee_mailbox (
                    msg_id TEXT PRIMARY KEY,
                    sender_id TEXT NOT NULL,
                    recipient_id TEXT NOT NULL,
                    envelope_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    delivered INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mailbox_recipient ON e2ee_mailbox(recipient_id, delivered, expires_at)"
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10.0)

    def enqueue(self, envelope: dict) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO e2ee_mailbox
                (msg_id, sender_id, recipient_id, envelope_json, created_at, expires_at, delivered)
                VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    envelope["msg_id"],
                    envelope["sender_id"],
                    envelope["recipient_id"],
                    json.dumps(envelope, sort_keys=True),
                    int(envelope["created_at"]),
                    int(envelope["expires_at"]),
                ),
            )
            return cur.rowcount > 0

    def fetch_pending(self, recipient_id: str, now: Optional[int] = None) -> List[dict]:
        ts = int(time.time()) if now is None else int(now)
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT envelope_json FROM e2ee_mailbox
                WHERE recipient_id = ? AND delivered = 0 AND expires_at > ?
                ORDER BY created_at ASC
                """,
                (recipient_id, ts),
            ).fetchall()
            return [json.loads(r[0]) for r in rows]

    def ack(self, msg_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE e2ee_mailbox SET delivered = 1 WHERE msg_id = ?",
                (msg_id,),
            )
            return cur.rowcount > 0

    def prune_expired(self, now: Optional[int] = None) -> int:
        ts = int(time.time()) if now is None else int(now)
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM e2ee_mailbox WHERE expires_at <= ? OR delivered = 1",
                (ts,),
            )
            return cur.rowcount
