from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

_hub = None
_orchestrator = None
_state_bus = None


def init_http_routes(hub, orchestrator, state_bus):
    global _hub, _orchestrator, _state_bus
    _hub = hub
    _orchestrator = orchestrator
    _state_bus = state_bus


class InjectEventRequest(BaseModel):
    event_type: str
    params: dict = {}


@router.get("/health")
async def health():
    agents_running = len(_orchestrator.agents) if _orchestrator else 0
    return {
        "status": "ok",
        "agents_running": agents_running,
        "ws_connections": _hub.connection_count if _hub else 0,
    }


@router.get("/state")
async def get_state():
    if not _state_bus:
        return {}
    return await _state_bus.get_snapshot()


@router.get("/agents")
async def get_agents():
    if not _orchestrator:
        return []
    return list(_orchestrator.get_agent_states().values())


@router.get("/chain-metrics")
async def get_chain_metrics():
    if not _orchestrator:
        return {}
    return _orchestrator._chain_metrics


@router.post("/events/inject")
async def inject_event(req: InjectEventRequest):
    if _orchestrator:
        await _orchestrator.inject_event(req.event_type, req.params)
    return {"ok": True, "event_type": req.event_type}
