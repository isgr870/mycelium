import os
import sys
import time
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
LOG_FILE = BASE_DIR / "daemon.log"

env = os.environ.copy()
ld_path = str(BASE_DIR / "llama.cpp" / "build" / "bin")
env["LD_LIBRARY_PATH"] = f"{ld_path}:{env.get("LD_LIBRARY_PATH", "")}"

def log(msg):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] [DAEMON] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(entry)
    print(entry, end="", flush=True)

SERVICES = {
    "llama-server": [
        str(BASE_DIR / "llama.cpp" / "build" / "bin" / "llama-server"),
        "-m", str(BASE_DIR / "models" / "qwen2.5-0.5b-q4_k_m.gguf"),
        "--port", "8080", "-t", "2", "-c", "4096", "-np", "1"
    ],
    "node.py": [sys.executable, str(BASE_DIR / "node.py")],
    "server.py": [sys.executable, str(BASE_DIR / "server.py")],
    "vault_watcher.py": [sys.executable, str(BASE_DIR / "vault_watcher.py")],
    "mesh.py": [sys.executable, str(BASE_DIR / "mesh.py")]
}

processes = {}

def start_service(name):
    cmd = SERVICES[name]
    log_file_path = BASE_DIR / f"{name.replace(".py", "")}.log"
    log_file = open(log_file_path, "a")
    p = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, env=env)
    processes[name] = (p, log_file)
    log(f"[✓] Started {name} (PID: {p.pid})")

def stop_all():
    log("Stopping Mycelium mesh network services...")
    for name, (p, log_file) in processes.items():
        if p.poll() is None:
            p.terminate()
            log(f"[✓] Stopped {name} (PID: {p.pid})")
        log_file.close()

def main():
    log("Starting Mycelium mesh network supervisor...")
    subprocess.run(["pkill", "-f", "llama-server"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-f", "uvicorn"], stderr=subprocess.DEVNULL)
    time.sleep(1)

    for name in SERVICES:
        exec_path = Path(SERVICES[name][0])
        script_target = Path(SERVICES[name][1]) if name != "llama-server" else exec_path
        
        if script_target.exists() and script_target.stat().st_size > 0:
            start_service(name)
        else:
            log(f"[-] Skipping {name}: Target file missing or 0 bytes")

    try:
        while True:
            time.sleep(3)
            for name in list(processes.keys()):
                p, log_file = processes[name]
                retcode = p.poll()
                if retcode is not None:
                    log(f"[!] {name} (PID: {p.pid}) died with exit code {retcode}. Restarting...")
                    log_file.close()
                    start_service(name)
    except KeyboardInterrupt:
        stop_all()

if __name__ == "__main__":
    main()
