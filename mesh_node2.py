import os, sys, json, asyncio, base64, socket
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.stdout.write("[*] Initializing Full Node 2 Daemon...\n")
sys.stdout.flush()

IDENTITY_DIR = os.path.expanduser("~/.mycelium_node2")
os.makedirs(IDENTITY_DIR, exist_ok=True)
SIGN_KEY_PATH = os.path.join(IDENTITY_DIR, "node.key")
ENC_KEY_PATH = os.path.join(IDENTITY_DIR, "node_enc.key")

if os.path.exists(SIGN_KEY_PATH):
    with open(SIGN_KEY_PATH, "rb") as f:
        priv_key = serialization.load_pem_private_key(f.read(), password=None)
else:
    priv_key = ed25519.Ed25519PrivateKey.generate()
    with open(SIGN_KEY_PATH, "wb") as f:
        f.write(priv_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

pub_key = priv_key.public_key()
pub_bytes = pub_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
node2_id = pub_bytes.hex()

if os.path.exists(ENC_KEY_PATH):
    with open(ENC_KEY_PATH, "rb") as f:
        enc_priv_key = serialization.load_pem_private_key(f.read(), password=None)
else:
    enc_priv_key = x25519.X25519PrivateKey.generate()
    with open(ENC_KEY_PATH, "wb") as f:
        f.write(enc_priv_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

enc_pub_key = enc_priv_key.public_key()
enc_pub_bytes = enc_pub_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

CONNECTED_PEERS = {}
DISCOVERY_PORT = 9005

async def udp_beacon_broadcaster():
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setblocking(False)
    
    beacon_payload = json.dumps({
        "node_id": node2_id,
        "tcp_port": 9001,
        "enc_pub": base64.b64encode(enc_pub_bytes).decode("utf-8")
    }).encode("utf-8")
    
    while True:
        try:
            await loop.sock_sendto(sock, beacon_payload, ("<broadcast>", DISCOVERY_PORT))
        except Exception:
            pass
        await asyncio.sleep(5)

async def handle_connection(reader, writer):
    peer_addr = writer.get_extra_info("peername")
    sys.stdout.write(f"[*] Node 2 incoming connection from {peer_addr}\n")
    sys.stdout.flush()
    peer_id = None
    
    try:
        nonce = os.urandom(32)
        writer.write(nonce)
        await writer.drain()
        
        data = await reader.readexactly(128)
        peer_sign_pub_bytes = data[:32]
        peer_enc_pub_bytes = data[32:64]
        peer_sig = data[64:]
        
        peer_sign_pub = ed25519.Ed25519PublicKey.from_public_bytes(peer_sign_pub_bytes)
        peer_sign_pub.verify(peer_sig, nonce)
        
        peer_id = peer_sign_pub_bytes.hex()
        CONNECTED_PEERS[peer_id] = {
            "writer": writer, 
            "reader": reader, 
            "enc_pub": x25519.X25519PublicKey.from_public_bytes(peer_enc_pub_bytes),
            "addr": peer_addr
        }
        
        sys.stdout.write(f"[+] Node 2 E2EE Handshake SUCCESS with Peer: {peer_id[:12]}...\n")
        sys.stdout.flush()
        
        writer.write(enc_pub_bytes)
        await writer.drain()
        
        while True:
            raw_length = await reader.readexactly(4)
            pkt_length = int.from_bytes(raw_length, "big")
            pkt_data = await reader.readexactly(pkt_length)
            pkt_json = json.loads(pkt_data.decode("utf-8"))
            
            sys.stdout.write(f"[+] Node 2 received packet from mesh: {pkt_json.get("source_id", "")[:12]}\n")
            sys.stdout.flush()
            writer.write(b"E2EE_DELIVERED_ACK")
            await writer.drain()
            
    except Exception as e:
        sys.stdout.write(f"[-] Node 2 Connection Error: {e}\n")
        sys.stdout.flush()
    finally:
        if peer_id and peer_id in CONNECTED_PEERS:
            del CONNECTED_PEERS[peer_id]
        writer.close()
        await writer.wait_closed()

async def main():
    server = await asyncio.start_server(handle_connection, "0.0.0.0", 9001)
    sys.stdout.write(f"[+] Node 2 active [ID: {node2_id[:12]}...] on TCP 9001 & UDP beacon\n")
    sys.stdout.flush()
    
    asyncio.create_task(udp_beacon_broadcaster())
    
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.stdout.write("\n[!] Node 2 stopped.\n")
        sys.stdout.flush()
