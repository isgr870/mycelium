import os, json, base64
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

os.makedirs(".mycelium", exist_ok=True)
key_path = ".mycelium/node.key"
if os.path.exists(key_path):
    with open(key_path, "rb") as f:
        priv = serialization.load_pem_private_key(f.read(), password=None)
    print("[+] Loaded existing key.")
else:
    priv = ed25519.Ed25519PrivateKey.generate()
    with open(key_path, "wb") as f:
        f.write(priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    print("[+] Generated new key.")

pub = priv.public_key()
node_id = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
print(f"Node ID: {node_id}")

data = json.dumps({"source": node_id, "msg": "Hello Mesh"}, sort_keys=True).encode()
sig = base64.b64encode(priv.sign(data)).decode()
print(f"Signature generated successfully: {sig[:20]}...")
