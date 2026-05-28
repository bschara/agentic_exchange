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
    Returns cached user agents for the given wallet address, enriched with live chain metrics.
    Source of truth is the on-chain AgentOwnerSet event; this is a fast read-through cache.
    """
    from agents.user_agents_db import UserAgentsDB

    records = UserAgentsDB().get_by_owner(address)

    # Merge live metrics from orchestrator if available
    live_metrics = {}
    if _orchestrator is not None:
        live_metrics = _orchestrator.get_agent_states()

    enriched = []
    for record in records:
        agent_id = record["agent_id"]
        entry = dict(record)
        if agent_id in live_metrics:
            entry["metrics"] = live_metrics[agent_id]
        enriched.append(entry)

    return {"agents": enriched, "address": address.lower()}
