from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
import os
import logging

logger = logging.getLogger(__name__)
app = FastAPI(title="Mycelium Mesh Server", version="10.12")

@app.get("/")
async def get_dashboard():
    html_path = os.path.join("static", "dashboard.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return {"status": "Mycelium mesh node active"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Ack: {data}")
    except WebSocketDisconnect:
        logger.info("WebSocket peer disconnected gracefully.")
    except Exception as e:
        logger.error("Unexpected WebSocket error handled: %s", e, exc_info=True)
