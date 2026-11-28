#!/usr/bin/env python3
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException

from core.edge_defense import verify_pow_token
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


def _pow_required() -> bool:
    return os.environ.get("MYCELIUM_REQUIRE_NAME_POW", "1").strip().lower() in ("1", "true", "yes", "on")


def _pow_bits() -> int:
    try:
        return max(1, int(os.environ.get("MYCELIUM_NAME_POW_BITS", "10")))
    except ValueError:
        return 10


@router.post("/register")
def register_name(
    record: dict = Body(...),
    x_mycelium_pow: Optional[str] = Header(default=None, alias="X-Mycelium-PoW"),
) -> dict:
    name = str(record.get("name", "")).strip().lower()
    node_id = str(record.get("node_id", "")).strip()
    pow_token = (x_mycelium_pow or str(record.get("pow_token", ""))).strip()

    if _pow_required():
        bits = _pow_bits()
        subject = f"{name}:{node_id}"
        if not verify_pow_token(subject, pow_token, difficulty_bits=bits):
            raise HTTPException(
                status_code=428,
                detail={
                    "status": "pow_required",
                    "reason": "missing_or_invalid_pow",
                    "subject": subject,
                    "difficulty_bits": bits,
                },
            )

    store = get_naming_store()
    ok, reason = store.register_or_update(record)
    if not ok:
        raise HTTPException(status_code=400, detail={"status": "rejected", "reason": reason})
    return {
        "status": "registered",
        "name": name,
        "node_id": node_id,
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
