import socket
import json
import urllib.request
import concurrent.futures

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()
TARGET_PORTS = [8081, 8082, 8083, 8084]

def check_endpoint(target):
    ip, port = target
    url = f"http://{ip}:{port}/api/status"
    try:
        req = urllib.request.urlopen(url, timeout=0.3)
        data = json.loads(req.read().decode())
        return (ip, port, data.get("node_id", "unknown"))
    except Exception:
        return None

def discover_lan():
    print(f"[*] Detected Host IP: {LOCAL_IP}")
    
    targets = []
    # Always scan loopback endpoints
    for port in TARGET_PORTS:
        targets.append(("127.0.0.1", port))
    
    # Scan active LAN IP subnet if connected to Wi-Fi
    if LOCAL_IP != "127.0.0.1":
        subnet_prefix = ".".join(LOCAL_IP.split(".")[:-1]) + "."
        print(f"[*] Probing subnet range {subnet_prefix}1-254 on ports {TARGET_PORTS}...")
        for octet in range(1, 255):
            ip = f"{subnet_prefix}{octet}"
            for port in TARGET_PORTS:
                targets.append((ip, port))

    discovered = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=60) as executor:
        results = executor.map(check_endpoint, targets)
        for res in results:
            if res and res not in discovered:
                discovered.append(res)
    
    print(f"\n[+] Scan Complete. Discovered {len(discovered)} active Mycelium endpoints:")
    for ip, port, node_id in discovered:
        print(f"    -> {node_id} @ {ip}:{port}")

if __name__ == "__main__":
    discover_lan()
