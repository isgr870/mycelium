import subprocess
import time
import urllib.request
import json
import os

nodes = [
    {"tcp": 9001, "http": 8081, "id": "node_alpha"},
    {"tcp": 9002, "http": 8082, "id": "node_beta"},
    {"tcp": 9003, "http": 8083, "id": "node_gamma"},
    {"tcp": 9004, "http": 8084, "id": "node_delta"}
]

print("[*] Terminating existing Mycelium processes...")
subprocess.run(["pkill", "-f", "mycelium_core.py"], stderr=subprocess.DEVNULL)
subprocess.run(["pkill", "-f", "mesh_daemon.py"], stderr=subprocess.DEVNULL)
time.sleep(1)

print("[*] Launching 4-Node v8 Unified Cluster...")
for n in nodes:
    cmd = [
        "python3", "mycelium_core.py",
        "--tcp", str(n["tcp"]),
        "--http", str(n["http"]),
        "--id", n["id"]
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f" [+] Launched {n['id']} on TCP {n['tcp']} / HTTP {n['http']} (PID: {proc.pid})")

time.sleep(2)
print("\n[*] Auditing Cluster HTTP Status Endpoints:")
for n in nodes:
    try:
        url = f"http://127.0.0.1:{n['http']}/api/status"
        res = urllib.request.urlopen(url, timeout=2)
        data = json.loads(res.read().decode())
        print(f"  -> HTTP {n['http']} [OK] ID: {data['node_id']} | Peers: {len(data['known_peers'])}")
    except Exception as e:
        print(f"  -> HTTP {n['http']} [FAIL] ({e})")

print("\n[+] 4-Node v8 Unified Engine active!")
