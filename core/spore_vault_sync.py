import os
import json
import time
import sqlite3
import hashlib
from typing import Dict, Any, List
from fastapi import APIRouter, Request, HTTPException, status
from core.security_hardening import verify_packet
from spore_sync import SimpleBloomFilter

router = APIRouter(prefix="/mesh/spores", tags=["spores"])

DIR = os.path.expanduser("~/mycelium")
DB_PATH = os.path.join(DIR, "ledger.db")
MAX_CLOCK_SKEW_SECONDS = 120


def _enable_wal(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    _enable_wal(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS spores (
            spore_id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            author_node TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL,
            title TEXT,
            content TEXT,
            embedding_json TEXT
        )
        """
    )
    conn.commit()
    return conn


def compute_spore_id(topic: str, content: Any, author_node: str) -> str:
    canonical = json.dumps(
        {"topic": topic, "content": content, "author": author_node},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def store_spore(topic: str, content: Any, author_node: str = "local") -> Dict[str, Any]:
    spore_id = compute_spore_id(topic, content, author_node)
    now = time.time()
    payload_str = json.dumps(content, ensure_ascii=False)
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO spores (spore_id, topic, payload_json, author_node, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (spore_id, topic, payload_str, author_node, now),
        )
        conn.execute(
            """
            INSERT INTO knowledge (timestamp, title, content, embedding_json)
            VALUES (?, ?, ?, ?)
            """,
            (now, f"spore:{topic}:{spore_id[:12]}", payload_str, "[]"),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "spore_id": spore_id,
        "topic": topic,
        "author_node": author_node,
        "created_at": now,
    }


def list_spores(limit: int = 200) -> List[Dict[str, Any]]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT spore_id, topic, payload_json, author_node, created_at
            FROM spores
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()

    items: List[Dict[str, Any]] = []
    for spore_id, topic, payload_json, author_node, created_at in rows:
        try:
            content = json.loads(payload_json)
        except Exception:
            content = payload_json
        items.append(
            {
                "spore_id": spore_id,
                "topic": topic,
                "content": content,
                "author_node": author_node,
                "created_at": created_at,
            }
        )
    return items


def build_local_bloom(size: int = 512, hash_count: int = 3) -> Dict[str, Any]:
    bf = SimpleBloomFilter(size=size, hash_count=hash_count)
    spores = list_spores(limit=1000)
    for sp in spores:
        bf.add(sp["spore_id"])
    return {
        "size": size,
        "hash_count": hash_count,
        "bit_array": bf.bit_array,
        "spore_ids": [sp["spore_id"] for sp in spores],
    }


def _verify_signed_request(raw_body: bytes, signature: str) -> Dict[str, Any]:
    secret = os.environ.get("MYCELIUM_SECRET_KEY", "")
    if not signature or not verify_packet(raw_body, signature, secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing HMAC packet signature.",
        )
    try:
        envelope = json.loads(raw_body.decode("utf-8"))
        ts = int(envelope.get("ts", 0))
        payload = envelope.get("payload", {})
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed signed spore envelope.",
        )
    if abs(int(time.time()) - ts) > MAX_CLOCK_SKEW_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Spore envelope timestamp expired.",
        )
    return payload


@router.get("/manifest")
async def get_spore_manifest():
    bloom = build_local_bloom()
    return {
        "count": len(bloom["spore_ids"]),
        "bloom": {
            "size": bloom["size"],
            "hash_count": bloom["hash_count"],
            "bit_array": bloom["bit_array"],
        },
        "spore_ids": bloom["spore_ids"],
    }


@router.post("/push")
async def push_spores(request: Request):
    raw_body = await request.body()
    sig = request.headers.get("X-Mycelium-Signature", "")
    payload = _verify_signed_request(raw_body, sig)

    incoming = payload.get("spores", [])
    if not isinstance(incoming, list):
        raise HTTPException(status_code=400, detail="spores must be a list")

    stored_ids: List[str] = []
    for item in incoming:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic", "general"))
        content = item.get("content", "")
        author_node = str(item.get("author_node", "remote-peer"))
        rec = store_spore(topic=topic, content=content, author_node=author_node)
        stored_ids.append(rec["spore_id"])

    return {
        "status": "replicated",
        "accepted_count": len(stored_ids),
        "spore_ids": stored_ids,
    }


@router.post("/pull")
async def pull_missing_spores(request: Request):
    raw_body = await request.body()
    sig = request.headers.get("X-Mycelium-Signature", "")
    payload = _verify_signed_request(raw_body, sig)

    remote_bits = payload.get("bit_array", [])
    bf_size = int(payload.get("size", 512))
    hash_count = int(payload.get("hash_count", 3))

    peer_bf = SimpleBloomFilter(size=bf_size, hash_count=hash_count)
    if isinstance(remote_bits, list) and len(remote_bits) == bf_size:
        peer_bf.bit_array = [int(b) for b in remote_bits]

    all_spores = list_spores(limit=500)
    missing: List[Dict[str, Any]] = []
    for sp in all_spores:
        # If peer bloom filter does not confirm presence, include spore in sync batch
        diff_indices = peer_bf.get_diff(build_local_bloom(bf_size, hash_count)["bit_array"])
        if not peer_bf.might_contain(sp["spore_id"]) or len(diff_indices) > 0:
            missing.append(sp)

    return {
        "count": len(missing),
        "spores": missing[:50],
    }
