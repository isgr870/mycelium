#!/usr/bin/env python3
import base64
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Request, Response
from pydantic import BaseModel

from core.chunk_store import ChunkStore
from core.e2ee_mailbox import MailboxStore


router = APIRouter(prefix="/mesh", tags=["slices"])


def _default_db_path() -> str:
    env_db = os.environ.get("MYCELIUM_DB_PATH", "").strip()
    if env_db:
        return env_db
    prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    region = os.environ.get("MYCELIUM_REGION", "default").strip() or "default"
    return str(Path(prefix) / "tmp/mycelium_regions" / region / f"{region}.db")


def _default_blob_dir() -> str:
    env_blobs = os.environ.get("MYCELIUM_BLOB_DIR", "").strip()
    if env_blobs:
        return env_blobs
    db_parent = Path(_default_db_path()).resolve().parent
    return str(db_parent / "blobs")


def get_mailbox_store() -> MailboxStore:
    return MailboxStore(_default_db_path())


def get_chunk_store() -> ChunkStore:
    return ChunkStore(_default_blob_dir())


class MailboxAckRequest(BaseModel):
    msg_id: str


@router.post("/mailbox/enqueue")
def mailbox_enqueue(envelope: dict = Body(...)) -> dict:
    required = ("msg_id", "sender_id", "recipient_id", "ciphertext_b64", "created_at", "expires_at")
    missing = [k for k in required if k not in envelope]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing fields: {missing}")
    mbox = get_mailbox_store()
    mbox.prune_expired()
    inserted = mbox.enqueue(envelope)
    return {
        "status": "queued",
        "inserted": inserted,
        "msg_id": envelope["msg_id"],
        "recipient_id": envelope["recipient_id"],
    }


@router.get("/mailbox/{recipient_id}")
def mailbox_fetch(recipient_id: str) -> dict:
    mbox = get_mailbox_store()
    mbox.prune_expired()
    messages = mbox.fetch_pending(recipient_id)
    return {
        "recipient_id": recipient_id,
        "count": len(messages),
        "messages": messages,
    }


@router.post("/mailbox/ack")
def mailbox_ack(req: MailboxAckRequest) -> dict:
    mbox = get_mailbox_store()
    acked = mbox.ack(req.msg_id)
    return {"msg_id": req.msg_id, "acked": acked}


@router.post("/chunks/manifest")
def chunks_manifest(manifest: dict = Body(...)) -> dict:
    mhash = str(manifest.get("manifest_hash", "")).strip()
    chunks = manifest.get("chunks")
    if not mhash or not isinstance(chunks, list):
        raise HTTPException(status_code=400, detail="Invalid manifest: requires manifest_hash and chunks[]")
    cstore = get_chunk_store()
    cstore.save_manifest(manifest)
    missing = cstore.missing_chunks(manifest)
    return {
        "status": "manifest_stored",
        "manifest_hash": mhash,
        "total_chunks": len(chunks),
        "missing_chunks": missing,
    }


@router.get("/chunks/{chunk_hash}")
def chunk_get(chunk_hash: str) -> Response:
    cstore = get_chunk_store()
    try:
        data = cstore.get_chunk(chunk_hash)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if data is None:
        raise HTTPException(status_code=404, detail="Chunk not found")
    return Response(content=data, media_type="application/octet-stream")


@router.put("/chunks/{chunk_hash}")
async def chunk_put(chunk_hash: str, request: Request) -> dict:
    body = await request.body()
    # Allow optional base64 JSON wrapper if client sends JSON instead of raw bytes
    ctype = request.headers.get("content-type", "")
    raw_bytes = body
    if "application/json" in ctype:
        import json
        parsed = json.loads(body.decode("utf-8"))
        if "data_b64" in parsed:
            raw_bytes = base64.b64decode(parsed["data_b64"])

    cstore = get_chunk_store()
    try:
        stored_hash = cstore.put_chunk(raw_bytes, expected_hash=chunk_hash)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "stored", "chunk_hash": stored_hash, "bytes": len(raw_bytes)}
