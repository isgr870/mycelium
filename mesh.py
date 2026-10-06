import os
import sys
import time
import json
import glob
import requests
from pathlib import Path

try:
    from cryptography.fernet import Fernet
except ImportError as e:
    print(f"[!] Import error: {e}", flush=True)
    sys.exit(1)

BASE_DIR = Path(__file__).parent.resolve()
VAULT_DIR = BASE_DIR / "vault"
VAULT_DIR.mkdir(exist_ok=True)
PEERS_FILE = BASE_DIR / "peers.json"
KEY_FILE = BASE_DIR / "secret.key"
LOG_FILE = BASE_DIR / "mesh.log"

TOR_PROXIES = {
    'http': 'socks5h://127.0.0.1:9050',
    'https': 'socks5h://127.0.0.1:9050'
}

def log(msg):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] [MESH] {msg}"
    print(entry, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(entry + "\n")

def get_or_create_key():
    if not KEY_FILE.exists():
        key = Fernet.generate_key()
        KEY_FILE.write_bytes(key)
        log("Generated new symmetric encryption key.")
    return KEY_FILE.read_bytes()

def load_peers():
    if not PEERS_FILE.exists():
        PEERS_FILE.write_text(json.dumps([]))
    try:
        return json.loads(PEERS_FILE.read_text())
    except Exception:
        return []

def encrypt_payload(data: str, key: bytes) -> str:
    f = Fernet(key)
    return f.encrypt(data.encode()).decode()

def broadcast_intel():
    key = get_or_create_key()
    peers = load_peers()
    files = glob.glob(str(VAULT_DIR / "*"))

    if not peers:
        log("No active peers configured in peers.json. Idle mode...")
        return

    for file_path in files:
        if file_path.endswith(".enc"):
            continue
        path = Path(file_path)
        try:
            content = path.read_text()
        except Exception:
            continue
        
        payload = {
            "node_id": "anon-node",
            "timestamp": time.time(),
            "filename": path.name,
            "data": encrypt_payload(content, key)
        }

        for peer in peers:
            try:
                log(f"Gossiping payload to peer: {peer}")
                res = requests.post(f"{peer}/api/gossip", json=payload, proxies=TOR_PROXIES, timeout=15)
                if res.status_code == 200:
                    log(f"[✓] Intel synced with {peer}")
            except Exception as e:
                log(f"[X] Peer sync failed ({peer}): {e}")

def main():
    log("Mycelium anonymous mesh node online.")
    while True:
        try:
            broadcast_intel()
        except Exception as e:
            log(f"[X] Loop exception: {e}")
        time.sleep(30)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Mesh node shutting down...")
        sys.exit(0)
