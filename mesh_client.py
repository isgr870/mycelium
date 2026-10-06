import os, sys, json, asyncio, base64
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

IDENTITY_DIR = os.path.expanduser("~/.mycelium")
KEY_PATH = os.path.join(IDENTITY_DIR, "node.key")

with open(KEY_PATH, "rb") as f:
    priv_key = serialization.load_pem_private_key(f.read(), password=None)
pub_key = priv_key.public_key()
pub_bytes = pub_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
node_id = pub_bytes.hex()

async def run_routing_client():
    sys.stdout.write("[*] Connecting routing test client...\n")
    sys.stdout.flush()
    
    reader, writer = await asyncio.open_connection("127.0.0.1", 9000)
    
    try:
        # 1. Handshake
        nonce = await reader.readexactly(32)
        signature = priv_key.sign(nonce)
        writer.write(pub_bytes + signature)
        await writer.drain()
        
        response = await reader.readexactly(13)
        sys.stdout.write(f"[+] Handshake Status: {response.decode()}\n")
        sys.stdout.flush()
        
        # Test 1: Send packet targeting local daemon ("daemon_node")
        sys.stdout.write("[*] Test 1: Sending packet destined for local node...\n")
        sys.stdout.flush()
        
        payload1 = {"type": "PING", "content": "Testing local delivery route"}
        pkt1 = {
            "source_id": node_id,
            "dest_id": "daemon_node",
            "payload": payload1,
            "ttl": 10
        }
        
        signable1 = json.dumps({
            "source_id": pkt1["source_id"],
            "dest_id": pkt1["dest_id"],
            "payload": pkt1["payload"],
            "ttl": pkt1["ttl"]
        }, sort_keys=True).encode("utf-8")
        
        pkt1["signature"] = base64.b64encode(priv_key.sign(signable1)).decode("utf-8")
        encoded1 = json.dumps(pkt1).encode("utf-8")
        
        writer.write(len(encoded1).to_bytes(4, "big") + encoded1)
        await writer.drain()
        
        ack1 = await reader.readexactly(22)
        sys.stdout.write(f"[+] Server Response: {ack1.decode()}\n\n")
        sys.stdout.flush()
        await asyncio.sleep(1)
        
        # Test 2: Send packet targeting a foreign node ID (triggers multi-hop forwarding logic)
        sys.stdout.write("[*] Test 2: Sending packet destined for a remote peer (triggers forwarding)...\n")
        sys.stdout.flush()
        
        payload2 = {"type": "RELAY", "content": "Broadcast across mesh graph"}
        pkt2 = {
            "source_id": node_id,
            "dest_id": "deadbeef1234567890abcdef", # Simulated remote node ID
            "payload": payload2,
            "ttl": 5
        }
        
        signable2 = json.dumps({
            "source_id": pkt2["source_id"],
            "dest_id": pkt2["dest_id"],
            "payload": pkt2["payload"],
            "ttl": pkt2["ttl"]
        }, sort_keys=True).encode("utf-8")
        
        pkt2["signature"] = base64.b64encode(priv_key.sign(signable2)).decode("utf-8")
        encoded2 = json.dumps(pkt2).encode("utf-8")
        
        writer.write(len(encoded2).to_bytes(4, "big") + encoded2)
        await writer.drain()
        
        ack2 = await reader.readexactly(22)
        sys.stdout.write(f"[+] Server Response: {ack2.decode()}\n")
        sys.stdout.flush()
        
        await asyncio.sleep(2)
        
    except Exception as e:
        sys.stdout.write(f"[-] Client routing error: {e}\n")
        sys.stdout.flush()
    finally:
        writer.close()
        await writer.wait_closed()
        sys.stdout.write("[*] Routing test complete.\n")
        sys.stdout.flush()

if __name__ == "__main__":
    asyncio.run(run_routing_client())
