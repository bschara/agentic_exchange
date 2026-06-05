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
    Falls back to orchestrator in-memory state for agents not yet persisted to disk.
    """
    from agents.user_agents_db import UserAgentsDB

    records = UserAgentsDB().get_by_owner(address)
    seen_ids = {r["agent_id"] for r in records}

    # Merge live metrics from orchestrator if available
    live_metrics = {}
    if _orchestrator is not None:
        live_metrics = _orchestrator.get_agent_states()

        # Include agents known in-memory but not yet written to disk (e.g. disk write failed)
        for agent_id, agent_data in _orchestrator.agents.items():
            if (
                agent_data.get("is_user_agent")
                and agent_data.get("owner_address", "").lower() == address.lower()
                and agent_id not in seen_ids
            ):
                records.append({
                    "agent_id":      agent_id,
                    "owner_address": agent_data.get("owner_address", ""),
                    "name":          agent_data.get("agent_name", agent_id),
                    "icon":          agent_data.get("icon", "🤖"),
                    "risk_level":    agent_data.get("risk_level", 3),
                })
                seen_ids.add(agent_id)

    # Filter out agents no longer registered in the current on-chain Registry.
    # This prevents stale DB entries (from a previous local deployment) from showing
    # pause/resume buttons that would revert in MetaMask.
    registered_ids: set[str] = set()
    if _orchestrator is not None and _orchestrator._registry:
        try:
            registered_ids = set(await _orchestrator._registry.get_all_agent_ids())
        except Exception as e:
            logger.warning(f"Could not fetch registered agent IDs: {e}")
            registered_ids = seen_ids  # fall back to showing all cached if Registry unavailable

    enriched = []
    for record in records:
        agent_id = record["agent_id"]
        if registered_ids and agent_id not in registered_ids:
            logger.debug(f"Skipping unregistered user agent {agent_id} (stale DB entry)")
            continue
        entry = dict(record)
        if agent_id in live_metrics:
            entry["metrics"] = live_metrics[agent_id]
        enriched.append(entry)

    return {"agents": enriched, "address": address.lower()}
