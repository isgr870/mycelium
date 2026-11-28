#!/usr/bin/env python3
import os
from pathlib import Path
from typing import Optional, Tuple

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from core.edge_defense import EdgeQuotaEngine


def _default_edge_db_path() -> str:
    env_db = os.environ.get("MYCELIUM_EDGE_DB_PATH", "").strip()
    if env_db:
        return env_db
    relay_db = os.environ.get("MYCELIUM_DB_PATH", "").strip()
    if relay_db:
        parent = Path(relay_db).resolve().parent
        return str(parent / "edge_quota.db")
    prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    region = os.environ.get("MYCELIUM_REGION", "default").strip() or "default"
    return str(Path(prefix) / "tmp/mycelium_regions" / region / "edge_quota.db")


def _build_default_engine() -> EdgeQuotaEngine:
    # Allow fast overrides via env vars for testing or regional tuning
    ext_req = int(os.environ.get("MYCELIUM_EXT_MAX_REQ", "30"))
    ext_bytes = int(os.environ.get("MYCELIUM_EXT_MAX_BYTES", str(1024 * 1024)))
    ext_strikes = int(os.environ.get("MYCELIUM_EXT_MAX_STRIKES", "3"))
    pow_bits = int(os.environ.get("MYCELIUM_SYBIL_POW_BITS", "12"))

    tier_limits = {
        "operator": {
            "window_sec": 60,
            "max_requests": int(os.environ.get("MYCELIUM_OP_MAX_REQ", "600")),
            "max_bytes": int(os.environ.get("MYCELIUM_OP_MAX_BYTES", str(50 * 1024 * 1024))),
            "max_strikes": 10,
        },
        "external": {
            "window_sec": 60,
            "max_requests": ext_req,
            "max_bytes": ext_bytes,
            "max_strikes": ext_strikes,
        },
        "quarantined": {
            "window_sec": 60,
            "max_requests": 0,
            "max_bytes": 0,
            "max_strikes": 0,
        },
    }
    return EdgeQuotaEngine(
        db_path=_default_edge_db_path(),
        tier_limits=tier_limits,
        sybil_pow_bits=pow_bits,
    )


_SHARED_ENGINE: Optional[EdgeQuotaEngine] = None


def get_edge_quota_engine() -> EdgeQuotaEngine:
    global _SHARED_ENGINE
    if _SHARED_ENGINE is None:
        _SHARED_ENGINE = _build_default_engine()
    return _SHARED_ENGINE


def _resolve_principal_and_tier(request: Request) -> Tuple[str, str]:
    client_ip = request.client.host if request.client and request.client.host else "unknown"
    peer_id = (
        request.headers.get("x-mycelium-peer-id")
        or request.headers.get("x-peer-id")
        or ""
    ).strip()

    principal_key = f"peer:{peer_id}" if peer_id else f"ip:{client_ip}"

    # Only grant operator tier when an explicit matching operator key is supplied
    op_key = os.environ.get("MYCELIUM_OPERATOR_KEY", "").strip()
    supplied_op = request.headers.get("x-mycelium-operator-key", "").strip()
    requested_tier = (request.headers.get("x-mycelium-tier") or "external").strip().lower()
    if op_key and supplied_op == op_key and requested_tier == "operator":
        return principal_key, "operator"

    return principal_key, "external"


async def enforce_edge_quota(
    request: Request,
    engine: EdgeQuotaEngine = Depends(get_edge_quota_engine),
) -> dict:
    """FastAPI route dependency for explicit per-route quota enforcement."""
    body = await request.body()
    principal_key, base_tier = _resolve_principal_and_tier(request)
    ok, reason, usage = engine.consume_quota(
        principal_key=principal_key,
        payload_bytes=len(body),
        base_tier=base_tier,
    )
    if not ok:
        status_code = 403 if ("quarantined" in reason or engine.effective_tier(principal_key, base_tier) == "quarantined") else 429
        headers = {"Retry-After": "60"} if status_code == 429 else {}
        raise HTTPException(
            status_code=status_code,
            detail={
                "error": "edge_quota_rejected",
                "reason": reason,
                "principal": principal_key,
                "quota": usage,
            },
            headers=headers,
        )
    return {"principal": principal_key, "quota": usage}


class EdgeQuotaMiddleware(BaseHTTPMiddleware):
    """Enforces EdgeQuotaEngine rate/byte limits and quarantine on /mesh routes."""

    def __init__(
        self,
        app: ASGIApp,
        engine: Optional[EdgeQuotaEngine] = None,
        protected_prefix: str = "/mesh",
    ) -> None:
        super().__init__(app)
        self.engine = engine or get_edge_quota_engine()
        self.protected_prefix = protected_prefix

    async def dispatch(self, request: Request, call_next):
        path = request.url.path or ""
        if not path.startswith(self.protected_prefix):
            return await call_next(request)

        body = await request.body()
        principal_key, base_tier = _resolve_principal_and_tier(request)
        ok, reason, usage = self.engine.consume_quota(
            principal_key=principal_key,
            payload_bytes=len(body),
            base_tier=base_tier,
        )

        eff_tier = self.engine.effective_tier(principal_key, base_tier=base_tier)
        if not ok:
            status_code = 403 if (eff_tier == "quarantined" or "quarantined" in reason) else 429
            headers = {"X-Mycelium-Quota-Tier": eff_tier}
            if status_code == 429:
                headers["Retry-After"] = "60"
            return JSONResponse(
                status_code=status_code,
                content={
                    "error": "edge_quota_rejected",
                    "reason": reason,
                    "principal": principal_key,
                    "tier": eff_tier,
                    "quota": usage,
                },
                headers=headers,
            )

        response = await call_next(request)
        response.headers["X-Mycelium-Quota-Tier"] = eff_tier
        response.headers["X-Mycelium-Quota-Used-Req"] = str(usage["used_requests"])
        response.headers["X-Mycelium-Quota-Max-Req"] = str(usage["max_requests"])
        return response
