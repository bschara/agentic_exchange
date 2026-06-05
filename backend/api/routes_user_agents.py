import logging

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter()

_orchestrator = None


def init_user_agent_routes(hub, orchestrator):
    global _orchestrator
    _orchestrator = orchestrator


@router.get("/agents")
async def get_user_agents(address: str = Query(..., description="Wallet address of the user")):
    """
    Returns user agents for the given wallet address, enriched with live chain metrics.
    Source of truth is the on-chain AgentRegistry — no local DB involved.
    """
    if _orchestrator is None:
        return {"agents": [], "address": address.lower()}

    registered_ids: set[str] = set()
    if _orchestrator._registry:
        try:
            registered_ids = set(await _orchestrator._registry.get_all_agent_ids())
        except Exception as e:
            logger.warning(f"Could not fetch registered agent IDs: {e}")

    live_metrics = _orchestrator.get_agent_states()
    enriched = []

    for agent_id, agent_data in _orchestrator.agents.items():
        if not agent_data.get("is_user_agent"):
            continue
        if agent_data.get("owner_address", "").lower() != address.lower():
            continue
        if registered_ids and agent_id not in registered_ids:
            continue
        entry = {
            "agent_id":      agent_id,
            "owner_address": agent_data.get("owner_address", ""),
            "name":          agent_data.get("agent_name", agent_id),
            "icon":          agent_data.get("icon", "🤖"),
            "risk_level":    agent_data.get("risk_level", 3),
        }
        if agent_id in live_metrics:
            entry["metrics"] = live_metrics[agent_id]
        enriched.append(entry)

    return {"agents": enriched, "address": address.lower()}
