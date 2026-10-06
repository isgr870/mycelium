import os, sqlite3, hashlib

DB_FILE = os.path.expanduser("~/mycelium/knowledge.db")
VAULT_DIR = os.path.expanduser("~/mycelium/vault")

def compute_hash(t, c):
    return hashlib.sha256(f"{t}:{c}".encode()).hexdigest()

def ingest():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    os.makedirs(VAULT_DIR, exist_ok=True)
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS knowledge (id INTEGER PRIMARY KEY AUTOINCREMENT, hash TEXT UNIQUE, title TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        added = 0
        for root, _, files in os.walk(VAULT_DIR):
            for f in files:
                if f.endswith((".md", ".txt")):
                    p = os.path.join(root, f)
                    with open(p, "r", encoding="utf-8", errors="ignore") as file:
                        c = file.read().strip()
                    if not c: continue
                    t = os.path.splitext(f)[0].replace("_", " ").title()
                    h = compute_hash(t, c)
                    cur = conn.cursor()
                    cur.execute("INSERT OR IGNORE INTO knowledge (hash, title, content) VALUES (?, ?, ?)", (h, t, c))
                    if cur.rowcount > 0:
                        added += 1
                        print(f"[+] Ingested: {t}")
        print(f"[+] Complete. Ingested {added} doc(s) from ~/mycelium/vault")

if __name__ == "__main__":
    ingest()
