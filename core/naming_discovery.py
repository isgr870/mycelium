#!/usr/bin/env python3
import base64
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

import hashlib
from core.peer_identity import sign_ed25519_b64

def derive_node_id(ed25519_pub_b64: str) -> str:
    raw = base64.b64decode(ed25519_pub_b64.strip())
    return hashlib.sha256(raw).hexdigest()[:24]



def canonical_name_payload(record: Dict[str, Any]) -> bytes:
    body = {
        "name": str(record["name"]).strip().lower(),
        "node_id": str(record["node_id"]).strip(),
        "ed25519_pub_b64": str(record["ed25519_pub_b64"]).strip(),
        "x25519_pub_b64": str(record.get("x25519_pub_b64", "")).strip(),
        "endpoints": list(record.get("endpoints") or []),
        "region": str(record.get("region", "")).strip(),
        "issued_at": int(record["issued_at"]),
        "expires_at": int(record["expires_at"]),
    }
    return json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sign_name_record(
    name: str,
    ed25519_priv_b64: str,
    ed25519_pub_b64: str,
    endpoints: List[Dict[str, Any]],
    x25519_pub_b64: str = "",
    region: str = "",
    ttl_seconds: int = 3600,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    ts = int(time.time()) if now is None else int(now)
    node_id = derive_node_id(ed25519_pub_b64)
    rec: Dict[str, Any] = {
        "name": name.strip().lower(),
        "node_id": node_id,
        "ed25519_pub_b64": ed25519_pub_b64.strip(),
        "x25519_pub_b64": x25519_pub_b64.strip(),
        "endpoints": endpoints,
        "region": region.strip(),
        "issued_at": ts,
        "expires_at": ts + max(1, int(ttl_seconds)),
    }
    rec["sig_ed25519_b64"] = sign_ed25519_b64(ed25519_priv_b64, canonical_name_payload(rec))
    return rec


def verify_name_record(record: Dict[str, Any], now: Optional[int] = None) -> tuple[bool, str]:
    ts = int(time.time()) if now is None else int(now)
    required = ("name", "node_id", "ed25519_pub_b64", "issued_at", "expires_at", "sig_ed25519_b64")
    for field_name in required:
        if field_name not in record or record[field_name] in (None, ""):
            return False, f"missing_{field_name}"

    name = str(record["name"]).strip().lower()
    if len(name) < 2 or len(name) > 128:
        return False, "invalid_name_length"

    if int(record["expires_at"]) <= ts:
        return False, "expired_record"

    if int(record["issued_at"]) > ts + 120:
        return False, "issued_in_future"

    pub_b64 = str(record["ed25519_pub_b64"]).strip()
    expected_node_id = derive_node_id(pub_b64)
    if str(record["node_id"]).strip() != expected_node_id:
        return False, "node_id_pubkey_mismatch"

    try:
        pub_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64))
        sig_bytes = base64.b64decode(str(record["sig_ed25519_b64"]).strip())
        pub_key.verify(sig_bytes, canonical_name_payload(record))
    except Exception as exc:
        return False, f"bad_signature:{exc}"

    return True, "ok"


@dataclass
class NamingDiscoveryStore:
    db_path: str

    def __post_init__(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS name_records (
                    name TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    ed25519_pub_b64 TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    issued_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_names_node ON name_records(node_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_names_exp ON name_records(expires_at)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10.0)

    def prune_expired(self, now: Optional[int] = None) -> int:
        ts = int(time.time()) if now is None else int(now)
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM name_records WHERE expires_at <= ?", (ts,))
            return cur.rowcount

    def register_or_update(self, record: Dict[str, Any], now: Optional[int] = None) -> tuple[bool, str]:
        ts = int(time.time()) if now is None else int(now)
        self.prune_expired(ts)

        ok, reason = verify_name_record(record, now=ts)
        if not ok:
            return False, reason

        name = str(record["name"]).strip().lower()
        new_node = str(record["node_id"]).strip()
        new_issued = int(record["issued_at"])
        new_exp = int(record["expires_at"])

        with self._conn() as conn:
            row = conn.execute(
                "SELECT node_id, issued_at FROM name_records WHERE name = ?",
                (name,),
            ).fetchone()
            if row is not None:
                existing_node, existing_issued = row[0], int(row[1])
                if existing_node != new_node:
                    return False, "name_owned_by_another_node"
                if new_issued < existing_issued:
                    return False, "stale_issued_at"

            conn.execute(
                """
                INSERT INTO name_records (name, node_id, ed25519_pub_b64, record_json, issued_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    node_id = excluded.node_id,
                    ed25519_pub_b64 = excluded.ed25519_pub_b64,
                    record_json = excluded.record_json,
                    issued_at = excluded.issued_at,
                    expires_at = excluded.expires_at
                """,
                (
                    name,
                    new_node,
                    str(record["ed25519_pub_b64"]).strip(),
                    json.dumps(record, sort_keys=True),
                    new_issued,
                    new_exp,
                ),
            )
            return True, "stored"

    def resolve(self, name: str, now: Optional[int] = None) -> Optional[Dict[str, Any]]:
        ts = int(time.time()) if now is None else int(now)
        self.prune_expired(ts)
        key = name.strip().lower()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT record_json FROM name_records WHERE name = ? AND expires_at > ?",
                (key, ts),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def list_peers(self, region: Optional[str] = None, now: Optional[int] = None) -> List[Dict[str, Any]]:
        ts = int(time.time()) if now is None else int(now)
        self.prune_expired(ts)
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT record_json FROM name_records WHERE expires_at > ? ORDER BY name ASC",
                (ts,),
            ).fetchall()
            out = []
            for (raw,) in rows:
                rec = json.loads(raw)
                if region and rec.get("region", "").lower() != region.strip().lower():
                    continue
                out.append(rec)
            return out
