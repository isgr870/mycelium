import os
import json
import time
import asyncio
import sqlite3
import httpx
from typing import Dict, Any, List
from fastapi import APIRouter
from core.security_hardening import sign_packet, ensure_wal_mode
from core.wan_mesh import PEER_REGISTRY, prune_stale_peers

router = APIRouter(prefix="/mesh/resilience", tags=["resilience"])

DIR = os.path.expanduser("~/mycelium")
DB_PATH = os.path.join(DIR, "ledger.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    ensure_wal_mode(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS outbound_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_url TEXT NOT NULL,
            endpoint_path TEXT NOT NULL,
            envelope_json TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            last_attempt_at REAL
        )
        """
    )
    conn.commit()
    return conn


def enqueue_outbound(target_url: str, endpoint_path: str, payload: Dict[str, Any]) -> int:
    secret = os.environ.get("MYCELIUM_SECRET_KEY", "")
    envelope_obj = {"ts": int(time.time()), "payload": payload}
    raw_bytes = json.dumps(envelope_obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = sign_packet(raw_bytes, secret)

    record = json.dumps(
        {
            "body": raw_bytes.decode("utf-8"),
            "signature": sig,
        }
    )
    conn = _get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO outbound_queue (target_url, endpoint_path, envelope_json, attempts, created_at)
            VALUES (?, ?, ?, 0, ?)
            """,
            (target_url.rstrip("/"), endpoint_path, record, time.time()),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def queue_depth() -> int:
    conn = _get_conn()
    try:
        row = conn.execute("SELECT COUNT(*) FROM outbound_queue").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


async def flush_outbound_queue(max_batch: int = 25) -> Dict[str, int]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, target_url, endpoint_path, envelope_json, attempts
            FROM outbound_queue
            ORDER BY id ASC
            LIMIT ?
            """,
            (max_batch,),
        ).fetchall()
    finally:
        conn.close()

    delivered = 0
    deferred = 0

    async with httpx.AsyncClient(timeout=4.0) as client:
        for row_id, target_url, endpoint_path, envelope_json, attempts in rows:
            try:
                parsed = json.loads(envelope_json)
                body_bytes = parsed["body"].encode("utf-8")
                sig = parsed["signature"]
                url = f"{target_url}{endpoint_path}"
                resp = await client.post(
                    url,
                    content=body_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-Mycelium-Signature": sig,
                    },
                )
                if 200 <= resp.status_code < 300:
                    c = _get_conn()
                    try:
                        c.execute("DELETE FROM outbound_queue WHERE id = ?", (row_id,))
                        c.commit()
                    finally:
                        c.close()
                    delivered += 1
                    continue
            except Exception:
                pass

            c = _get_conn()
            try:
                c.execute(
                    """
                    UPDATE outbound_queue
                    SET attempts = ?, last_attempt_at = ?
                    WHERE id = ?
                    """,
                    (attempts + 1, time.time(), row_id),
                )
                c.commit()
            finally:
                c.close()
            deferred += 1

    return {"delivered": delivered, "deferred": deferred}


async def resilience_flush_loop() -> None:
    while True:
        await asyncio.sleep(10)
        prune_stale_peers()
        if queue_depth() > 0:
            await flush_outbound_queue()


@router.get("/status")
async def resilience_status():
    prune_stale_peers()
    return {
        "mode": "offline-first-mesh",
        "active_peers": len(PEER_REGISTRY),
        "queued_packets": queue_depth(),
    }
