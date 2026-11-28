#!/usr/bin/env python3
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from core.e2ee_mailbox import MailboxStore
from core.naming_discovery import NamingDiscoveryStore


def _default_db_path() -> str:
    env_db = os.environ.get("MYCELIUM_DB_PATH", "").strip()
    if env_db:
        return env_db
    prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    region = os.environ.get("MYCELIUM_REGION", "").strip().lower()
    if not region:
        port_to_region = {"8101": "us", "8102": "ug", "8103": "asia"}
        region = port_to_region.get(os.environ.get("MYCELIUM_PORT", "").strip(), "default")
    return str(Path(prefix) / "tmp/mycelium_regions" / region / f"{region}.db")


def _default_self_url() -> str:
    explicit = os.environ.get("MYCELIUM_SELF_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    port = os.environ.get("MYCELIUM_PORT", "").strip()
    if port:
        return f"http://127.0.0.1:{port}"
    region = os.environ.get("MYCELIUM_REGION", "").strip().lower()
    region_ports = {"us": "8101", "ug": "8102", "asia": "8103"}
    if region in region_ports:
        return f"http://127.0.0.1:{region_ports[region]}"
    return "http://127.0.0.1:8000"


def _default_peer_urls() -> List[str]:
    raw = os.environ.get(
        "MYCELIUM_PEER_URLS",
        "http://127.0.0.1:8101,http://127.0.0.1:8102,http://127.0.0.1:8103",
    )
    self_url = _default_self_url()
    urls: List[str] = []
    for part in raw.split(","):
        u = part.strip().rstrip("/")
        if not u or u == self_url:
            continue
        if u not in urls:
            urls.append(u)
    return urls


def _http_json(method: str, url: str, payload: Optional[dict] = None, timeout: float = 4.0) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return int(resp.status), json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") or "{}"
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"detail": raw}
        return int(exc.code), parsed
    except Exception as exc:
        return 0, {"error": str(exc)}


def list_pending_recipient_ids(db_path: str) -> List[str]:
    import sqlite3
    with sqlite3.connect(db_path, timeout=10.0) as conn:
        rows = conn.execute(
            "SELECT DISTINCT recipient_id FROM e2ee_mailbox WHERE delivered = 0"
        ).fetchall()
        return [str(r[0]) for r in rows if r and r[0]]


def replicate_once(
    db_path: Optional[str] = None,
    peer_urls: Optional[List[str]] = None,
    timeout: float = 4.0,
) -> Dict[str, object]:
    resolved_db = db_path or _default_db_path()
    peers = peer_urls if peer_urls is not None else _default_peer_urls()

    naming = NamingDiscoveryStore(resolved_db)
    mbox = MailboxStore(resolved_db)

    local_names = naming.list_peers()
    pending_recipients = list_pending_recipient_ids(resolved_db)
    local_envelopes: List[dict] = []
    for rec_id in pending_recipients:
        local_envelopes.extend(mbox.fetch_pending(rec_id))

    peer_reports: List[dict] = []
    for peer in peers:
        names_pushed = 0
        names_pulled = 0
        mail_pushed = 0
        mail_pulled = 0
        errors: List[str] = []

        # 1. Push local signed name records -> peer (with PoW header if required)
        from core.edge_defense import compute_pow_nonce
        pow_bits = int(os.environ.get("MYCELIUM_NAME_POW_BITS", "10"))
        for rec in local_names:
            subj = f"{str(rec.get('name', '')).strip().lower()}:{str(rec.get('node_id', '')).strip()}"
            nonce, digest = compute_pow_nonce(subj, difficulty_bits=pow_bits)
            headers = {
                "Content-Type": "application/json",
                "X-Mycelium-PoW": f"{nonce}:{digest}",
            }
            data = json.dumps(rec).encode("utf-8")
            req = urllib.request.Request(f"{peer}/mesh/names/register", data=data, method="POST", headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    code = int(resp.status)
            except urllib.error.HTTPError as exc:
                code = int(exc.code)
            except Exception:
                code = 0
            if code == 200:
                names_pushed += 1

        # 2. Pull remote signed name records <- peer
        code, data = _http_json("GET", f"{peer}/mesh/names/peers", None, timeout=timeout)
        if code == 200 and isinstance(data.get("peers"), list):
            for remote_rec in data["peers"]:
                ok, _ = naming.register_or_update(remote_rec)
                if ok:
                    names_pulled += 1
        elif code != 200:
            errors.append(f"names_pull:{code}")

        # 3. Push local undelivered E2EE envelopes -> peer
        for env in local_envelopes:
            code, _ = _http_json("POST", f"{peer}/mesh/mailbox/enqueue", env, timeout=timeout)
            if code == 200:
                mail_pushed += 1

        # 4. Pull undelivered E2EE envelopes for known recipients <- peer
        for rec_id in pending_recipients:
            code, data = _http_json("GET", f"{peer}/mesh/mailbox/{rec_id}", None, timeout=timeout)
            if code == 200 and isinstance(data.get("messages"), list):
                for remote_env in data["messages"]:
                    if mbox.enqueue(remote_env):
                        mail_pulled += 1
            elif code != 200 and code != 404:
                errors.append(f"mail_pull({rec_id}):{code}")

        peer_reports.append(
            {
                "peer": peer,
                "names_pushed": names_pushed,
                "names_pulled": names_pulled,
                "mail_pushed": mail_pushed,
                "mail_pulled": mail_pulled,
                "errors": errors,
            }
        )

    return {
        "db_path": resolved_db,
        "local_names_count": len(local_names),
        "local_pending_mail_count": len(local_envelopes),
        "peers": peer_reports,
    }


if __name__ == "__main__":
    print(json.dumps(replicate_once(), indent=2))
