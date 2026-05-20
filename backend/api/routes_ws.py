import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()

_hub = None
_orchestrator = None


def init_routes(hub, orchestrator):
    global _hub, _orchestrator
    _hub = hub
    _orchestrator = orchestrator


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await _hub.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await _hub.send_personal(websocket, {"type": "pong"})
                elif msg.get("type") == "inject_event":
                    event_type = msg.get("data", {}).get("event_type", "")
                    params = msg.get("data", {}).get("params", {})
                    if _orchestrator and event_type:
                        await _orchestrator.inject_event(event_type, params)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        await _hub.disconnect(websocket)
