import urllib.error
import urllib.request
def get_active_db_path() -> str:
    current_db = globals().get("DB_PATH")
    initial_db = globals().get("_INITIAL_DB_PATH")
    if isinstance(current_db, str) and current_db and current_db != initial_db:
        p = Path(current_db).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        return str(p)
    explicit = os.environ.get("MYCELIUM_DB_PATH", "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        return str(p)
    data_dir = os.environ.get("MYCELIUM_DATA_DIR", "").strip()
    if data_dir:
        p = Path(data_dir).expanduser() / "ledger.db"
        p.parent.mkdir(parents=True, exist_ok=True)
        return str(p)
    if "get_db_path" in globals() and callable(globals()["get_db_path"]):
        return str(globals()["get_db_path"]("ledger.db"))
    default_db = os.path.join(os.path.expanduser("~/mycelium"), "ledger.db")
    return str(Path(current_db or default_db).expanduser())

def recommended_bloom_config(spore_count: int) -> tuple[int, int]:
    if spore_count <= 64:
        return 512, 3
    bits = min(16384, max(512, int(spore_count * 10)))
    # Round up to multiple of 64 for clean bit arrays
    bits = ((bits + 63) // 64) * 64
    hashes = 5 if bits >= 2048 else 4
    return bits, hashes

def get_node_role_info() -> dict:
    role = os.environ.get("MYCELIUM_ROLE", "worker").strip() or "worker"
    raw_caps = os.environ.get("MYCELIUM_CAPABILITIES", "general,sync")
    caps = [c.strip() for c in raw_caps.split(",") if c.strip()]
    node_id = os.environ.get("MYCELIUM_NODE_ID") or f"{role}-{os.uname().nodename}"
    return {"node_id": node_id, "role": role, "capabilities": caps}

from pathlib import Path
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
_INITIAL_DB_PATH = DB_PATH
MAX_CLOCK_SKEW_SECONDS = 120


def _enable_wal(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(get_active_db_path(), timeout=15.0)
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
        try:
            local_bloom = build_local_bloom(bf_size, hash_count)
        except TypeError:
            local_bloom = build_local_bloom()
        local_bits = local_bloom.get("bit_array", []) if isinstance(local_bloom, dict) else []
        try:
            diff_indices = peer_bf.get_diff(local_bits)
        except TypeError:
            other_bf = SimpleBloomFilter(size=bf_size, hash_count=hash_count)
            if isinstance(local_bits, list) and len(local_bits) == bf_size:
                other_bf.bit_array = [int(b) for b in local_bits]
            diff_indices = peer_bf.get_diff(other_bf)
        has_spore = False
        if hasattr(peer_bf, "might_contain"):
            has_spore = bool(peer_bf.might_contain(sp["spore_id"]))
        elif hasattr(peer_bf, "contains"):
            has_spore = bool(peer_bf.contains(sp["spore_id"]))
        if (not has_spore) or len(diff_indices) > 0:
                missing.append(sp)

    return {
        "count": len(missing),
        "spores": missing[:50],
    }


def _extract_job_envelope(spore: Dict[str, Any]) -> Dict[str, Any]:
    content = spore.get("content")
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}

def create_job_spore(
    goal_id: str,
    job_type: str,
    task_payload: Dict[str, Any],
    author_node: str = "coordinator",
    lease_seconds: int = 120,
) -> Dict[str, Any]:
    now = int(time.time())
    job_id = f"job-{now}-{hashlib.sha256(f'{goal_id}:{job_type}:{now}:{json.dumps(task_payload, sort_keys=True)}'.encode()).hexdigest()[:12]}"
    body = {
        "kind": "job",
        "job_id": job_id,
        "goal_id": goal_id,
        "job_type": job_type,
        "status": "queued",
        "lease_owner": None,
        "lease_expires_at": 0,
        "task": task_payload,
        "created_at": now,
    }
    return store_spore(topic=f"job.{job_type}", content=body, author_node=author_node)

def list_jobs(job_type: str | None = None, include_expired: bool = True) -> list[dict[str, Any]]:
    now = int(time.time())
    spores = sorted(
        list_spores(limit=1000),
        key=lambda s: (float(s.get("created_at", 0)), str(s.get("spore_id", ""))),
    )
    jobs_by_id: dict[str, dict[str, Any]] = {}
    for sp in spores:
        data = _extract_job_envelope(sp)
        if data.get("kind") != "job":
            continue
        jid = data.get("job_id")
        if not jid:
            continue
        if job_type and data.get("job_type") != job_type:
            continue
        current = dict(data)
        current["spore_id"] = sp.get("spore_id")
        expired = bool(current.get("lease_expires_at") and int(current["lease_expires_at"]) <= now)
        if current.get("status") == "claimed" and expired and include_expired:
            current["status"] = "queued"
            current["lease_owner"] = None
            current["lease_expires_at"] = 0
        jobs_by_id[jid] = current
    return list(jobs_by_id.values())

def claim_job_spore(job_id: str, worker_id: str, lease_seconds: int = 120) -> dict[str, Any]:
    now = int(time.time())
    jobs = {j["job_id"]: j for j in list_jobs(include_expired=True)}
    job = jobs.get(job_id)
    if not job:
        return {"claimed": False, "reason": "job_not_found", "job_id": job_id}
    if job.get("status") == "completed":
        return {"claimed": False, "reason": "already_completed", "job_id": job_id}
    if job.get("status") == "claimed" and int(job.get("lease_expires_at") or 0) > now:
        return {
            "claimed": False,
            "reason": "leased_by_another_worker",
            "job_id": job_id,
            "lease_owner": job.get("lease_owner"),
            "lease_expires_at": job.get("lease_expires_at"),
        }
    updated = dict(job)
    updated.pop("spore_id", None)
    updated["status"] = "claimed"
    updated["lease_owner"] = worker_id
    updated["lease_expires_at"] = now + max(15, int(lease_seconds))
    updated["claimed_at"] = now
    rec = store_spore(topic=f"job.{updated['job_type']}", content=updated, author_node=worker_id)
    return {"claimed": True, "job_id": job_id, "job": updated, "spore_id": rec.get("spore_id")}

def complete_job_spore(job_id: str, worker_id: str, result_payload: dict[str, Any]) -> dict[str, Any]:
    now = int(time.time())
    jobs = {j["job_id"]: j for j in list_jobs(include_expired=True)}
    job = jobs.get(job_id)
    if not job:
        return {"completed": False, "reason": "job_not_found", "job_id": job_id}
    updated = dict(job)
    updated.pop("spore_id", None)
    updated["status"] = "completed"
    updated["completed_by"] = worker_id
    updated["completed_at"] = now
    updated["result"] = result_payload
    rec = store_spore(topic=f"job.{updated['job_type']}", content=updated, author_node=worker_id)
    return {"completed": True, "job_id": job_id, "job": updated, "spore_id": rec.get("spore_id")}

@router.get("/role")
async def mesh_role_status():
    info = get_node_role_info()
    spores = list_spores(limit=1000)
    bits, hashes = recommended_bloom_config(len(spores))
    return {
        **info,
        "db_path": get_active_db_path(),
        "spore_count": len(spores),
        "recommended_bloom": {"size": bits, "hash_count": hashes},
    }

@router.get("/jobs")
async def mesh_list_jobs(job_type: str | None = None):
    info = get_node_role_info()
    jobs = list_jobs(job_type=job_type)
    matching = [j for j in jobs if j.get("job_type") in info["capabilities"] or "general" in info["capabilities"]]
    return {"node": info, "jobs": jobs, "matching_jobs": matching}

@router.post("/jobs/create")
async def mesh_create_job(request: Request):
    raw_body = await request.body()
    sig = request.headers.get("X-Mycelium-Signature", "")
    payload = _verify_signed_request(raw_body, sig)
    goal_id = str(payload.get("goal_id", "mycelium-core-goal"))
    job_type = str(payload.get("job_type", "general"))
    task = payload.get("task", {})
    author = str(payload.get("author_node", get_node_role_info()["node_id"]))
    lease_sec = int(payload.get("lease_seconds", 120))
    rec = create_job_spore(goal_id=goal_id, job_type=job_type, task_payload=task, author_node=author, lease_seconds=lease_sec)
    created_jobs = [j for j in list_jobs(job_type=job_type) if j.get("spore_id") == rec.get("spore_id")]
    if created_jobs:
        job_obj = created_jobs[-1]
    else:
        job_obj = {
            "kind": "job",
            "job_id": rec.get("spore_id", "")[:16],
            "goal_id": goal_id,
            "job_type": job_type,
            "status": "queued",
            "lease_owner": None,
            "lease_expires_at": 0,
            "task": task,
            "spore_id": rec.get("spore_id"),
        }
    return {"status": "queued", "spore_id": rec.get("spore_id"), "job": job_obj}

@router.post("/jobs/claim")
async def mesh_claim_job(request: Request):
    raw_body = await request.body()
    sig = request.headers.get("X-Mycelium-Signature", "")
    payload = _verify_signed_request(raw_body, sig)
    job_id = str(payload.get("job_id", ""))
    worker_id = str(payload.get("worker_id", get_node_role_info()["node_id"]))
    lease_sec = int(payload.get("lease_seconds", 120))
    return claim_job_spore(job_id=job_id, worker_id=worker_id, lease_seconds=lease_sec)

@router.post("/jobs/complete")
async def mesh_complete_job(request: Request):
    raw_body = await request.body()
    sig = request.headers.get("X-Mycelium-Signature", "")
    payload = _verify_signed_request(raw_body, sig)
    job_id = str(payload.get("job_id", ""))
    worker_id = str(payload.get("worker_id", get_node_role_info()["node_id"]))
    result = payload.get("result", {})
    return complete_job_spore(job_id=job_id, worker_id=worker_id, result_payload=result)

import random as _random

_PEER_TABLE: Dict[str, Dict[str, Any]] = {}
_SEEN_GOSSIP_IDS: set[str] = set()

def _seed_peers_from_env() -> None:
    raw = os.environ.get("MYCELIUM_BOOTSTRAP_PEERS", "")
    for item in raw.split(","):
        url = item.strip().rstrip("/")
        if url and url not in _PEER_TABLE:
            _PEER_TABLE[url] = {
                "url": url,
                "role": "bootstrap",
                "last_seen": int(time.time()),
            }

def register_peer(url: str, role: str = "peer", node_id: str | None = None) -> Dict[str, Any]:
    clean = url.strip().rstrip("/")
    now = int(time.time())
    entry = _PEER_TABLE.get(clean, {"url": clean, "role": role})
    entry["role"] = role or entry.get("role", "peer")
    if node_id:
        entry["node_id"] = node_id
    entry["last_seen"] = now
    _PEER_TABLE[clean] = entry
    return entry


def prune_stale_peers(max_age_seconds: float | None = None) -> int:
    ttl_sec = max_age_seconds
    if ttl_sec is None:
        try:
            ttl_sec = float(os.environ.get("MYCELIUM_PEER_TTL_SEC", "300.0"))
        except ValueError:
            ttl_sec = 300.0
    if ttl_sec <= 0:
        return 0
    now = time.time()
    stale_keys = [
        key
        for key, meta in _PEER_TABLE.items()
        if isinstance(meta, dict) and (now - float(meta.get("last_seen", now))) > ttl_sec
    ]
    for key in stale_keys:
        _PEER_TABLE.pop(key, None)
    return len(stale_keys)

def select_gossip_peers(fanout: int = 6) -> List[Dict[str, Any]]:
    prune_stale_peers()
    _seed_peers_from_env()
    effective_k = max(1, min(int(os.environ.get("MYCELIUM_GOSSIP_FANOUT", fanout)), 16))
    peers = list(_PEER_TABLE.values())
    if len(peers) <= effective_k:
        return peers
    return _random.sample(peers, effective_k)

def should_forward_gossip(gossip_id: str, ttl: int = 8) -> bool:
    if not gossip_id or ttl <= 0:
        return False
    if gossip_id in _SEEN_GOSSIP_IDS:
        return False
    if len(_SEEN_GOSSIP_IDS) > 20000:
        # Trim oldest quarter when cap is reached to bound memory at 1,000+ nodes
        trimmed = list(_SEEN_GOSSIP_IDS)[5000:]
        _SEEN_GOSSIP_IDS.clear()
        _SEEN_GOSSIP_IDS.update(trimmed)
    _SEEN_GOSSIP_IDS.add(gossip_id)
    return True

def compute_gossip_jitter_seconds(base_interval: float = 15.0, jitter_ratio: float = 0.25) -> float:
    delta = base_interval * jitter_ratio
    return max(0.5, base_interval + _random.uniform(-delta, delta))

@router.get("/peers")
async def mesh_list_peers():
    _seed_peers_from_env()
    peers = list(_PEER_TABLE.values())
    return {
        "node": get_node_role_info(),
        "fanout_k": max(1, min(int(os.environ.get("MYCELIUM_GOSSIP_FANOUT", 6)), 16)),
        "peer_count": len(peers),
        "peers": peers[:200],
    }

@router.post("/peers/register")
async def mesh_register_peer(request: Request):
    raw_body = await request.body()
    sig = request.headers.get("X-Mycelium-Signature", "")
    payload = _verify_signed_request(raw_body, sig)
    url = str(payload.get("url", "")).strip()
    if not url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing peer url.")
    entry = register_peer(
        url=url,
        role=str(payload.get("role", "peer")),
        node_id=payload.get("node_id"),
    )
    incoming_peers = payload.get("peers", [])
    if isinstance(incoming_peers, list):
        for p in incoming_peers[:50]:
            if isinstance(p, dict) and p.get("url"):
                register_peer(str(p["url"]), role=str(p.get("role", "peer")), node_id=p.get("node_id"))
    return {"status": "registered", "peer": entry, "peer_count": len(_PEER_TABLE)}

@router.post("/gossip/tick")
async def mesh_gossip_tick(request: Request):
    raw_body = await request.body()
    sig = request.headers.get("X-Mycelium-Signature", "")
    payload = _verify_signed_request(raw_body, sig)
    gossip_id = str(payload.get("gossip_id", ""))
    ttl = int(payload.get("ttl", 8))
    hop = int(payload.get("hop", 0))
    if not gossip_id:
        gossip_id = hashlib.sha256(raw_body).hexdigest()[:16]
    forward = should_forward_gossip(gossip_id=gossip_id, ttl=ttl)
    sampled = select_gossip_peers(fanout=int(payload.get("fanout", 6)))
    active_forward = bool(payload.get("active_forward", False))
    dispatch_report = None
    if forward and active_forward:
        dispatch_report = forward_gossip_to_peers(
            gossip_id=gossip_id,
            ttl=ttl,
            hop=hop,
            fanout=int(payload.get("fanout", 6)),
            data=payload.get("data") if isinstance(payload.get("data"), dict) else {},
        )
    return {
        "gossip_id": gossip_id,
        "accepted_for_forward": forward,
        "ttl_remaining": max(0, ttl - 1),
        "hop": hop + 1,
        "sampled_fanout": len(sampled),
        "sampled_peers": [p.get("url") for p in sampled],
        "next_jitter_seconds": round(compute_gossip_jitter_seconds(), 2),
        "dispatch": dispatch_report,
    }


def forward_gossip_to_peers(
    gossip_id: str,
    ttl: int = 8,
    hop: int = 0,
    fanout: int = 6,
    data: Dict[str, Any] | None = None,
    timeout_sec: float = 1.5,
) -> Dict[str, Any]:
    next_ttl = int(ttl) - 1
    next_hop = int(hop) + 1
    sampled = select_gossip_peers(fanout=fanout)
    if next_ttl <= 0 or not sampled:
        return {
            "gossip_id": gossip_id,
            "forwarded_count": 0,
            "failed_count": 0,
            "targets": [],
            "next_ttl": max(0, next_ttl),
            "next_hop": next_hop,
        }

    secret = os.environ.get("MYCELIUM_SECRET_KEY", "")
    child_payload = {
        "gossip_id": gossip_id,
        "ttl": next_ttl,
        "hop": next_hop,
        "fanout": fanout,
        "data": data or {},
    }
    envelope = {"ts": int(time.time()), "payload": child_payload}
    raw = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret:
        _sign_fn = globals().get("sign_packet")
        if not callable(_sign_fn):
            from core.security_hardening import sign_packet as _sign_fn
        headers["X-Mycelium-Signature"] = _sign_fn(raw, secret)

    forwarded: List[str] = []
    failed: List[Dict[str, str]] = []
    for peer in sampled:
        base_url = str(peer.get("url", "")).rstrip("/")
        if not base_url:
            continue
        target = f"{base_url}/mesh/spores/gossip/tick"
        try:
            req = urllib.request.Request(target, data=raw, method="POST", headers=headers)
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                if 200 <= getattr(resp, "status", 200) < 300:
                    forwarded.append(base_url)
                else:
                    failed.append({"url": base_url, "error": f"http_{resp.status}"})
        except Exception as exc:
            failed.append({"url": base_url, "error": str(exc)[:120]})

    return {
        "gossip_id": gossip_id,
        "forwarded_count": len(forwarded),
        "failed_count": len(failed),
        "forwarded_peers": forwarded,
        "failed_peers": failed,
        "next_ttl": next_ttl,
        "next_hop": next_hop,
    }


import math as _math

def recommend_bloom_params(expected_items: int, target_fp_rate: float = 0.01) -> Dict[str, int]:
    n = max(1, int(expected_items))
    p = min(max(float(target_fp_rate), 1e-5), 0.25)
    min_bits = max(512, int(os.environ.get("MYCELIUM_BLOOM_MIN_BITS", "512")))
    max_bits = max(min_bits, int(os.environ.get("MYCELIUM_BLOOM_MAX_BITS", "65536")))
    # Optimal bit count m = -(n * ln(p)) / (ln(2)^2), rounded up to a power of 2
    raw_bits = -(n * _math.log(p)) / (_math.log(2.0) ** 2)
    clamped = max(min_bits, min(max_bits, int(_math.ceil(raw_bits))))
    pow2 = 1 << (clamped - 1).bit_length()
    size_bits = max(min_bits, min(max_bits, pow2))
    optimal_k = int(round((size_bits / n) * _math.log(2.0)))
    hash_count = max(3, min(8, optimal_k if optimal_k > 0 else 4))
    return {
        "expected_items": n,
        "size_bits": size_bits,
        "size": size_bits,
        "hash_count": hash_count,
        "max_bits": max_bits,
    }


import threading as _threading

_GOSSIP_STOP_EVENT = _threading.Event()
_GOSSIP_THREAD: _threading.Thread | None = None

def _gossip_worker_loop(base_interval: float = 15.0) -> None:
    while not _GOSSIP_STOP_EVENT.is_set():
        wait_s = compute_gossip_jitter_seconds(base_interval=base_interval)
        if _GOSSIP_STOP_EVENT.wait(timeout=wait_s):
            break
        try:
            _seed_peers_from_env()
            if _PEER_TABLE:
                gossip_id = f"bg-{int(time.time())}-{_random.randint(1000, 9999)}"
                if should_forward_gossip(gossip_id=gossip_id, ttl=6):
                    forward_gossip_to_peers(
                        gossip_id=gossip_id,
                        ttl=6,
                        hop=0,
                        fanout=max(1, min(int(os.environ.get("MYCELIUM_GOSSIP_FANOUT", 6)), 16)),
                        data={"source": get_node_role_info().get("node_id", "node")},
                        timeout_sec=1.0,
                    )
        except Exception:
            # Keep background loop resilient to transient network/peer errors
            continue

def start_background_gossip_loop(base_interval: float | None = None) -> bool:
    global _GOSSIP_THREAD
    if _GOSSIP_THREAD is not None and _GOSSIP_THREAD.is_alive():
        return False
    interval = base_interval
    if interval is None:
        interval = float(os.environ.get("MYCELIUM_GOSSIP_INTERVAL_SEC", "15.0"))
    _GOSSIP_STOP_EVENT.clear()
    t = _threading.Thread(target=_gossip_worker_loop, args=(max(1.0, interval),), daemon=True, name="mycelium-gossip-loop")
    t.start()
    _GOSSIP_THREAD = t
    return True

def stop_background_gossip_loop(timeout: float = 1.0) -> None:
    _GOSSIP_STOP_EVENT.set()
    if _GOSSIP_THREAD is not None and _GOSSIP_THREAD.is_alive():
        _GOSSIP_THREAD.join(timeout=timeout)

from contextlib import asynccontextmanager as _asynccontextmanager

@_asynccontextmanager
async def _mesh_router_lifespan(_router):
    flag = os.environ.get("MYCELIUM_AUTO_GOSSIP", "0").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        start_background_gossip_loop()
    yield
    stop_background_gossip_loop(timeout=1.0)

router.lifespan_context = _mesh_router_lifespan
