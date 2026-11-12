"""WebSocket endpoint for real-time agent output streaming."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, Any
import sys
import os
import json

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router"))

from graph.router import RouterSupervisor

router = APIRouter()

# Supervisor instance (shared with chat API via main.py)
supervisor: RouterSupervisor | None = None


def set_supervisor(sup: RouterSupervisor):
    global supervisor
    supervisor = sup


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        self.active_connections.pop(client_id, None)

    async def send(self, client_id: str, message: dict):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_text(json.dumps(message))


manager = ConnectionManager()


@router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            message_type = msg.get("type", "chat")

            if message_type == "chat" and supervisor:
                result = supervisor.run(msg.get("message", ""), msg.get("project"))
                await manager.send(client_id, {
                    "type": "chat_result",
                    "data": result,
                })
            elif message_type == "ping":
                await manager.send(client_id, {"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(client_id)
