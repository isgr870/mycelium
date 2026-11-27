#!/usr/bin/env python3
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, HTTPException

from core.naming_discovery import NamingDiscoveryStore


router = APIRouter(prefix="/mesh/names", tags=["naming"])


def _default_db_path() -> str:
    env_db = os.environ.get("MYCELIUM_DB_PATH", "").strip()
    if env_db:
        return env_db
    prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    region = os.environ.get("MYCELIUM_REGION", "default").strip() or "default"
    return str(Path(prefix) / "tmp/mycelium_regions" / region / f"{region}.db")


def get_naming_store() -> NamingDiscoveryStore:
    return NamingDiscoveryStore(_default_db_path())


@router.post("/register")
def register_name(record: dict = Body(...)) -> dict:
    store = get_naming_store()
    ok, reason = store.register_or_update(record)
    if not ok:
        raise HTTPException(status_code=400, detail={"status": "rejected", "reason": reason})
    return {
        "status": "registered",
        "name": str(record["name"]).strip().lower(),
        "node_id": str(record["node_id"]).strip(),
        "expires_at": int(record["expires_at"]),
    }


@router.get("/resolve/{name}")
def resolve_name(name: str) -> dict:
    store = get_naming_store()
    rec = store.resolve(name)
    if not rec:
        raise HTTPException(status_code=404, detail="Name not found or expired")
    return {"status": "resolved", "record": rec}


@router.get("/peers")
def list_named_peers(region: Optional[str] = None) -> dict:
    store = get_naming_store()
    peers = store.list_peers(region=region)
    return {"count": len(peers), "peers": peers}
