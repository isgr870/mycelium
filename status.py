import os, sys, glob, json, subprocess, urllib.request

def check_processes():
    services = ["daemon.py", "llama-server", "node.py", "server.py", "vault_watcher.py", "mesh.py"]
    print("\033[1;34m=== Mycelium Stack Process Health ===\033[0m")
    try:
        ps_output = subprocess.check_output(["ps", "aux"]).decode("utf-8")
    except Exception:
        ps_output = ""

    for service in services:
        pids = []
        rss_total = 0
        for line in ps_output.splitlines():
            if service in line and "status.py" not in line and "grep" not in line:
                parts = line.split()
                if len(parts) >= 6:
                    pids.append(parts[1])
                    try:
                        rss_total += int(parts[5])
                    except ValueError:
                        pass
        status = len(pids) > 0
        color = "\033[1;32m[RUNNING]\033[0m" if status else "\033[1;31m[OFFLINE]\033[0m"
        pid_str = f"(PID: {", ".join(pids)})" if status else ""
        mem_str = f"~{rss_total / 1024:.1f} MB RSS" if status else ""
        print(f"  • {service:<18} {color} {pid_str} {mem_str}")

def check_memory():
    print("\n\033[1;34m=== System Memory Overview ===\033[0m")
    if os.path.exists("/proc/meminfo"):
        try:
            meminfo = {}
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        meminfo[parts[0].strip()] = int(parts[1].strip().split()[0])
            total = meminfo.get("MemTotal", 0) / 1024
            avail = meminfo.get("MemAvailable", meminfo.get("MemFree", 0)) / 1024
            used = total - avail
            pct = (used / total * 100) if total else 0
            print(f"  • System RAM Usage: {used:.1f} MB / {total:.1f} MB ({pct:.1f}%)")
        except Exception as e:
            print(f"  • Memory Info: Unavailable ({e})")

def check_vault():
    print("\n\033[1;34m=== Vault & Knowledge Base ===\033[0m")
    vault_dir = os.path.expanduser("~/mycelium/vault")
    files = glob.glob(os.path.join(vault_dir, "*")) if os.path.exists(vault_dir) else []
    file_count = len([f for f in files if os.path.isfile(f)])
    print(f"  • Local Vault Files:   {file_count} document(s) in {vault_dir}")

    try:
        req = urllib.request.Request("http://localhost:8000/knowledge/list")
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.loads(response.read().decode())
            indexed_count = len(data) if isinstance(data, list) else 0
            print(f"  • Node Indexed Items:  {indexed_count} active RAG record(s)")
    except Exception:
        print("  • Node Indexed Items:  \033[1;31mUnable to query node API (:8000)\033[0m")

if __name__ == "__main__":
    check_processes()
    check_memory()
    check_vault()
    print()
