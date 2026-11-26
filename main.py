import os
import secrets
import uvicorn

os.environ.setdefault("MYCELIUM_SECRET_KEY", secrets.token_hex(32))
os.environ.setdefault("MYCELIUM_HOST", "127.0.0.1")
os.environ.setdefault("MYCELIUM_PORT", "8000")

from node import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ["MYCELIUM_HOST"],
        port=int(os.environ["MYCELIUM_PORT"]),
    )
