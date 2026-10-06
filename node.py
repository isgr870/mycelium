import os
import json
import time
import math
import socket
import sqlite3
import httpx
import threading
import subprocess
from typing import List
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

DIR = os.path.expanduser("~/mycelium")
DB_PATH = os.path.join(DIR, "ledger.db")
UDP_PORT = 8001
LLM_ENGINE_URL = "http://0.0.0.0:8080/v1/chat/completions"

PEERS = {}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL, prompt TEXT, response TEXT, node_origin TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS knowledge (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL, title TEXT, content TEXT, embedding_json TEXT)")
    conn.commit()
    conn.close()

init_db()

# UDP Broadcaster & Listener for P2P Peer Discovery
def udp_broadcaster():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    msg = json.dumps({"type": "MYCELIUM_PING", "port": 8000}).encode("utf-8")
    while True:
        try:
            sock.sendto(msg, ("<broadcast>", UDP_PORT))
        except Exception:
            pass
        time.sleep(5)

def udp_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", UDP_PORT))
    except Exception:
        return
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            p = json.loads(data.decode("utf-8"))
            if p.get("type") == "MYCELIUM_PING":
                PEERS[addr[0]] = time.time()
        except Exception:
            pass

threading.Thread(target=udp_broadcaster, daemon=True).start()
threading.Thread(target=udp_listener, daemon=True).start()

app = FastAPI(title="Mycelium Mesh Node")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def get_local_knowledge(prompt: str) -> str:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT title, content FROM knowledge")
        rows = c.fetchall()
        conn.close()
        
        matches = []
        words = set(prompt.lower().split())
        for title, content in rows:
            score = sum(1 for w in words if w in content.lower() or w in title.lower())
            if score > 0:
                matches.append(f"[{title}]: {content}")
        
        if matches:
            return "\n--- CONTEXT FROM VAULT ---\n" + "\n".join(matches) + "\n-------------------------\n"
    except Exception:
        pass
    return ""

@app.get("/")
async def serve_index():
    idx = os.path.join(DIR, "index.html")
    if os.path.exists(idx):
        return FileResponse(idx)
    return JSONResponse({"status": "ONLINE", "message": "index.html missing"})

@app.get("/status")
async def get_status():
    now = time.time()
    active_peers = [ip for ip, last in PEERS.items() if now - last < 15]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM ledger")
    l_cnt = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM knowledge")
    k_cnt = c.fetchone()[0]
    conn.close()
    return {
        "status": "ONLINE",
        "active_peers": len(active_peers) + 1,
        "chain_length": l_cnt,
        "knowledge_docs": k_cnt,
        "llm_engine": "http://0.0.0.0:8080"
    }

@app.get("/sys/stats")
async def get_sys_stats():
    battery = "N/A"
    try:
        res = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            battery = json.loads(res.stdout).get("percentage", "N/A")
    except Exception:
        pass
    return {
        "timestamp": time.time(),
        "battery_percent": battery,
        "storage_db_bytes": os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    }

@app.get("/knowledge/list")
async def list_knowledge():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, timestamp, title, length(content) FROM knowledge ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "timestamp": r[1], "title": r[2], "size": r[3]} for r in rows]

@app.delete("/knowledge/{doc_id}")
async def delete_doc(doc_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM knowledge WHERE id = ?", (doc_id,))
    conn.commit()
    conn.close()
    return {"status": "success", "message": f"Deleted document {doc_id}"}

@app.get("/ledger/history")
async def get_ledger():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, timestamp, prompt, response, node_origin FROM ledger ORDER BY id DESC LIMIT 20")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "timestamp": r[1], "prompt": r[2], "response": r[3], "origin": r[4]} for r in rows]

@app.post("/knowledge/ingest")
async def ingest_doc(request: Request):
    data = await request.json()
    title = data.get("title", "Untitled")
    content = data.get("content", "").strip()
    if not content:
        return JSONResponse({"status": "error", "message": "Content empty"}, status_code=400)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO knowledge (timestamp, title, content, embedding_json) VALUES (?, ?, ?, ?)", (time.time(), title, content, "[]"))
    conn.commit()
    conn.close()
    return {"status": "success", "message": f"Ingested {title}"}

@app.post("/prompt")
async def handle_prompt(request: Request):
    data = await request.json()
    user_p = data.get("prompt", "")
    context = get_local_knowledge(user_p)
    if not context or any(w in user_p.lower() for w in ["summarize", "vault", "check", "all"]):
        # Fallback: combine all available knowledge
        try:
            all_docs = get_all_knowledge() if "get_all_knowledge" in globals() else []
            if not all_docs and hasattr(knowledge_base, "values"):
                all_docs = list(knowledge_base.values())
            context = "\n".join([str(d) for d in all_docs])[:1500]
        except Exception:
            pass
    system_prompt = "You are Mycelium Mesh AI. Be precise and technical."
    if context[:1500]:
        system_prompt += context[:1500]

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_p}
        ],
        "max_tokens": 512,
        "stream": True
    }
    
    async def stream_generator():
        full_res = ""
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream("POST", LLM_ENGINE_URL, json=payload) as response:
                    async for chunk in response.aiter_lines():
                        if chunk.startswith("data: "):
                            d_str = chunk[6:].strip()
                            if d_str == "[DONE]":
                                break
                            try:
                                d_json = json.loads(d_str)
                                tok = d_json["choices"][0]["delta"].get("content", "")
                                full_res += tok
                                yield f"data: {json.dumps({'token': tok})}\n\n"
                            except Exception:
                                continue
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("INSERT INTO ledger (timestamp, prompt, response, node_origin) VALUES (?, ?, ?, ?)", (time.time(), user_p, full_res, "local"))
            conn.commit()
            conn.close()
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
