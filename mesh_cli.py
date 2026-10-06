import sys
sys.stdout.write("DEBUG: 1. Python started execution\n")
sys.stdout.flush()

import os
import json
import asyncio
import base64
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.stdout.write("DEBUG: 2. Imports loaded successfully\n")
sys.stdout.flush()

IDENTITY_DIR = os.path.expanduser("~/.mycelium")
SIGN_KEY_PATH = os.path.join(IDENTITY_DIR, "node.key")
ENC_KEY_PATH = os.path.join(IDENTITY_DIR, "node_enc.key")
os.makedirs(IDENTITY_DIR, exist_ok=True)

if os.path.exists(SIGN_KEY_PATH):
    with open(SIGN_KEY_PATH, "rb") as f:
        priv_key = serialization.load_pem_private_key(f.read(), password=None)
else:
    priv_key = ed25519.Ed25519PrivateKey.generate()
    with open(SIGN_KEY_PATH, "wb") as f:
        f.write(priv_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

pub_key = priv_key.public_key()
pub_bytes = pub_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
node_id = pub_bytes.hex()

if os.path.exists(ENC_KEY_PATH):
    with open(ENC_KEY_PATH, "rb") as f:
        enc_priv_key = serialization.load_pem_private_key(f.read(), password=None)
else:
    enc_priv_key = x25519.X25519PrivateKey.generate()
    with open(ENC_KEY_PATH, "wb") as f:
        f.write(enc_priv_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

enc_pub_key = enc_priv_key.public_key()
enc_pub_bytes = enc_pub_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

sys.stdout.write("DEBUG: 3. Keys loaded/generated successfully\n")
sys.stdout.flush()

async def run_e2ee_cli():
    sys.stdout.write("[*] Connecting to E2EE Daemon (127.0.0.1:9000)...\n")
    sys.stdout.flush()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", 9000)
        sys.stdout.write("DEBUG: 4. TCP Connection established\n")
        sys.stdout.flush()
    except Exception as e:
        sys.stdout.write(f"[-] Connection failed: {e}\n")
        sys.stdout.flush()
        return
        
    try:
        nonce = await reader.readexactly(32)
        sys.stdout.write("DEBUG: 5. Received nonce from daemon\n")
        sys.stdout.flush()
        
        signature = priv_key.sign(nonce)
        writer.write(pub_bytes + enc_pub_bytes + signature)
        await writer.drain()
        
        daemon_enc_pub_bytes = await reader.readexactly(32)
        daemon_enc_pub = x25519.X25519PublicKey.from_public_bytes(daemon_enc_pub_bytes)
        
        shared_key = enc_priv_key.exchange(daemon_enc_pub)
        aesgcm = AESGCM(shared_key)
        
        sys.stdout.write(f"[+] E2EE Secure Tunnel Established! [Node ID: {node_id[:12]}...]\n")
        sys.stdout.write("----------------------------------------------------------\n")
        sys.stdout.write("Type your message (encrypted end-to-end), or 'exit' to quit.\n")
        sys.stdout.write("----------------------------------------------------------\n\n")
        sys.stdout.flush()
        
        while True:
            sys.stdout.write("mycelium-e2ee> ")
            sys.stdout.flush()
            
            loop = asyncio.get_running_loop()
            user_input = await loop.run_in_executor(None, sys.stdin.readline)
            user_input = user_input.strip()
            
            if not user_input:
                continue
            if user_input.lower() == "exit":
                break
                
            payload_dict = {"type": "SECURE_CHAT", "text": user_input}
            plaintext = json.dumps(payload_dict).encode("utf-8")
            iv = os.urandom(12)
            ciphertext = aesgcm.encrypt(iv, plaintext, None)
            
            pkt = {
                "source_id": node_id,
                "dest_id": "daemon_node",
                "ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
                "nonce": base64.b64encode(iv).decode("utf-8"),
                "ttl": 15
            }
            
            signable = json.dumps({
                "source_id": pkt["source_id"],
                "dest_id": pkt["dest_id"],
                "ciphertext": pkt["ciphertext"],
                "nonce": pkt["nonce"],
                "ttl": pkt["ttl"]
            }, sort_keys=True).encode("utf-8")
            
            pkt["signature"] = base64.b64encode(priv_key.sign(signable)).decode("utf-8")
            encoded = json.dumps(pkt).encode("utf-8")
            
            writer.write(len(encoded).to_bytes(4, "big") + encoded)
            await writer.drain()
            
            ack = await reader.readexactly(18)
            sys.stdout.write(f"[ACK] {ack.decode()}\n\n")
            sys.stdout.flush()
            
    except Exception as e:
        sys.stdout.write(f"[-] CLI Session Error: {e}\n")
        sys.stdout.flush()
    finally:
        writer.close()
        await writer.wait_closed()
        sys.stdout.write("[*] Disconnected.\n")
        sys.stdout.flush()

if __name__ == "__main__":
    sys.stdout.write("DEBUG: 0. Entering main loop\n")
    sys.stdout.flush()
    try:
        asyncio.run(run_e2ee_cli())
    except KeyboardInterrupt:
        sys.stdout.write("\n[*] Exiting...\n")
        sys.stdout.flush()
