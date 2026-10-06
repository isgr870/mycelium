import sys, json, secrets, hashlib, urllib.request
from urllib.parse import urlencode

NODE_URL = "http://127.0.0.1:8081"
PRIME = 2305843009213693951
priv = secrets.randbelow(100000)
pub = pow(2, priv, PRIME)

def req(p, q={}):
    return json.loads(urllib.request.urlopen(f"{NODE_URL}{p}?{urlencode(q)}").read().decode())

print(f"=== MYCELIUM CLIENT ===\nPubKey: {pub}\n")
key = None

while True:
    try:
        cmd = input("mycelium-cli> ").strip().split(" ", 1)
        action = cmd[0].lower() if cmd else ""
        arg = cmd[1] if len(cmd) > 1 else ""
        if action in ["exit", "quit"]: break
        elif action in ["status", "nodes"]:
            r = req("/api/status")
            print(f"Node: {r.get("node_id")[:12]}... | Known: {r.get("known_nodes")}")
        elif action == "handshake":
            p = int(arg) if arg.isdigit() else 12345
            key = hashlib.sha256(str(pow(p, priv, PRIME)).encode()).hexdigest()
            print(f"[+] Key established: {key[:16]}...")
        elif action == "send":
            if not key: print("[!] Run handshake first"); continue
            r = req("/api/send", {"msg": f"[ENC:{key[:8]}] {arg}"})
            print(f"[+] Response: {r}")
        else: print("Commands: status, handshake <pub>, send <msg>, exit")
    except Exception as e: print(f"[!] Error: {e}")
