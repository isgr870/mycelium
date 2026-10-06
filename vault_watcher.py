import os
import time
import glob
import httpx

VAULT_DIR = os.path.expanduser("~/mycelium/vault")
INGEST_URL = "http://localhost:8000/knowledge/ingest"
PROCESSED_LOG = os.path.join(VAULT_DIR, ".processed.txt")

def load_processed():
    if os.path.exists(PROCESSED_LOG):
        with open(PROCESSED_LOG, "r") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def mark_processed(filepath):
    with open(PROCESSED_LOG, "a") as f:
        f.write(filepath + "\n")

print(f"[*] Mycelium Vault Watcher active. Monitoring: {VAULT_DIR}")

processed = load_processed()

while True:
    files = glob.glob(f"{VAULT_DIR}/*.md") + glob.glob(f"{VAULT_DIR}/*.txt")
    for filepath in files:
        if filepath not in processed:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                
                if not content:
                    continue

                title = os.path.basename(filepath)
                res = httpx.post(INGEST_URL, json={"title": title, "content": content}, timeout=10.0)
                
                if res.status_code == 200:
                    print(f"[+] Successfully ingested: {title}")
                    processed.add(filepath)
                    mark_processed(filepath)
                else:
                    print(f"[!] Failed to ingest {title}: HTTP {res.status_code}")
            except Exception as e:
                print(f"[!] Error processing {filepath}: {e}")
                
    time.sleep(5)
