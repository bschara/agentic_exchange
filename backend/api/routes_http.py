from fastapi import APIRouter
from pydantic import BaseModel

from config import settings

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


@router.get("/debug/config")
async def debug_config():
    """Returns non-sensitive config values so you can verify the backend loaded the right .env."""
    return {
        "somnia_rpc_url": settings.somnia_rpc_url,
        "somnia_chain_id": settings.somnia_chain_id,
        "exchange_address": settings.exchange_address,
        "agent_registry_address": settings.agent_registry_address,
        "treasury_address": settings.treasury_address,
        "agent_coordinator_address": settings.agent_coordinator_address,
        "coordinator_initialized": _orchestrator is not None and _orchestrator._coordinator is not None,
    }


@router.post("/agents/trigger")
async def trigger_all_agents():
    """Manually fire triggerAgentDecision for all 4 agents. Use this if startup triggers were missed."""
    if not _orchestrator or not _orchestrator._coordinator:
        return {"ok": False, "error": "AgentCoordinator not initialized — check /debug/config"}

    results = {}
    from agents.orchestrator import AGENT_CONFIGS
    for cfg in AGENT_CONFIGS:
        pk = getattr(settings, cfg["pk_key"])
        try:
            result = await _orchestrator._coordinator.trigger_decision(
                agent_pk=pk,
                agent_id=cfg["id"],
            )
            results[cfg["id"]] = {"ok": True, "tx": result.get("tx_hash")}
        except Exception as e:
            results[cfg["id"]] = {"ok": False, "error": str(e)}

    return {"ok": True, "results": results}
