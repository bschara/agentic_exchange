from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import admin_auth
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


class FundAgentRequest(BaseModel):
    amount: float


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


@router.get("/agents/registry")
async def get_registry():
    """On-chain agent discovery — returns all registered agents from AgentRegistry."""
    if not _orchestrator or not _orchestrator._registry:
        return {"agents": [], "error": "AgentRegistry not initialized"}
    addresses = await _orchestrator._registry.get_all_agents()
    agents = []
    for addr in addresses:
        info = await _orchestrator._registry.get_agent(addr)
        if info:
            agents.append(info)
    return {"agents": agents, "count": len(agents)}


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


_ON_CHAIN_AGENTS = ["market_maker", "momentum_trader", "arbitrage_agent", "risk_manager"]


@router.post("/agents/{agent_id}/pause", dependencies=[Depends(admin_auth)])
async def pause_agent(agent_id: str):
    """Pause an agent's on-chain self-retrigger loop to conserve STT tokens."""
    if not _orchestrator or not _orchestrator._coordinator:
        raise HTTPException(status_code=503, detail="AgentCoordinator not initialized")
    if agent_id not in _ON_CHAIN_AGENTS:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")

    result = await _orchestrator._coordinator.pause_agent(settings.deployer_private_key, agent_id)
    _orchestrator.paused_agents.add(agent_id)

    agent_wallet = _orchestrator.agents.get(agent_id, {}).get("wallet_address")
    if agent_wallet and _orchestrator._registry:
        try:
            await _orchestrator._registry.set_active(settings.deployer_private_key, agent_wallet, False)
        except Exception:
            pass

    return {"status": "paused", "agent_id": agent_id, "tx": result.get("tx_hash")}


@router.post("/agents/{agent_id}/resume", dependencies=[Depends(admin_auth)])
async def resume_agent(agent_id: str):
    """Resume a paused agent — clears the pause flag and fires a fresh trigger."""
    if not _orchestrator or not _orchestrator._coordinator:
        raise HTTPException(status_code=503, detail="AgentCoordinator not initialized")
    if agent_id not in _ON_CHAIN_AGENTS:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")

    resume_result = await _orchestrator._coordinator.resume_agent(settings.deployer_private_key, agent_id)
    _orchestrator.paused_agents.discard(agent_id)

    agent_wallet = _orchestrator.agents.get(agent_id, {}).get("wallet_address")
    if agent_wallet and _orchestrator._registry:
        try:
            await _orchestrator._registry.set_active(settings.deployer_private_key, agent_wallet, True)
        except Exception:
            pass

    from agents.orchestrator import AGENT_CONFIGS
    pk = next((getattr(settings, c["pk_key"]) for c in AGENT_CONFIGS if c["id"] == agent_id), settings.deployer_private_key)
    trigger_result = await _orchestrator._coordinator.trigger_decision(agent_pk=pk, agent_id=agent_id)

    return {
        "status": "resumed",
        "agent_id": agent_id,
        "resume_tx": resume_result.get("tx_hash"),
        "trigger_tx": trigger_result.get("tx_hash"),
    }


@router.post("/agents/pause-all", dependencies=[Depends(admin_auth)])
async def pause_all_agents():
    """Pause all 4 on-chain agents to stop spending STT tokens."""
    if not _orchestrator or not _orchestrator._coordinator:
        raise HTTPException(status_code=503, detail="AgentCoordinator not initialized")

    results = {}
    for agent_id in _ON_CHAIN_AGENTS:
        try:
            result = await _orchestrator._coordinator.pause_agent(settings.deployer_private_key, agent_id)
            _orchestrator.paused_agents.add(agent_id)
            agent_wallet = _orchestrator.agents.get(agent_id, {}).get("wallet_address")
            if agent_wallet and _orchestrator._registry:
                try:
                    await _orchestrator._registry.set_active(settings.deployer_private_key, agent_wallet, False)
                except Exception:
                    pass
            results[agent_id] = {"ok": True, "tx": result.get("tx_hash")}
        except Exception as e:
            results[agent_id] = {"ok": False, "error": str(e)}

    return {"status": "all_paused", "results": results}


@router.post("/agents/resume-all", dependencies=[Depends(admin_auth)])
async def resume_all_agents():
    """Resume all 4 on-chain agents and fire fresh triggers for each."""
    if not _orchestrator or not _orchestrator._coordinator:
        raise HTTPException(status_code=503, detail="AgentCoordinator not initialized")

    from agents.orchestrator import AGENT_CONFIGS
    results = {}
    for agent_id in _ON_CHAIN_AGENTS:
        try:
            await _orchestrator._coordinator.resume_agent(settings.deployer_private_key, agent_id)
            _orchestrator.paused_agents.discard(agent_id)
            agent_wallet = _orchestrator.agents.get(agent_id, {}).get("wallet_address")
            if agent_wallet and _orchestrator._registry:
                try:
                    await _orchestrator._registry.set_active(settings.deployer_private_key, agent_wallet, True)
                except Exception:
                    pass
            pk = next((getattr(settings, c["pk_key"]) for c in AGENT_CONFIGS if c["id"] == agent_id), settings.deployer_private_key)
            trigger = await _orchestrator._coordinator.trigger_decision(agent_pk=pk, agent_id=agent_id)
            results[agent_id] = {"ok": True, "trigger_tx": trigger.get("tx_hash")}
        except Exception as e:
            results[agent_id] = {"ok": False, "error": str(e)}

    return {"status": "all_resumed", "results": results}


@router.post("/agents/{agent_id}/fund", dependencies=[Depends(admin_auth)])
async def fund_agent(agent_id: str, req: FundAgentRequest):
    """Mint AgentToken to an agent's wallet to fund sell-side order escrow."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    if not _orchestrator._agent_token:
        raise HTTPException(status_code=503, detail="AgentToken contract not initialized — set AGENT_TOKEN_ADDRESS")
    if agent_id not in _orchestrator.agents:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    agent_wallet = _orchestrator.agents[agent_id]["wallet_address"]
    result = await _orchestrator._agent_token.mint(
        deployer_pk=settings.deployer_private_key,
        agent_address=agent_wallet,
        amount_tokens=req.amount,
    )
    return {
        "status": "funded",
        "agent_id": agent_id,
        "agent_wallet": agent_wallet,
        "amount": req.amount,
        "tx": result.get("tx_hash"),
    }


@router.post("/agents/fund-all", dependencies=[Depends(admin_auth)])
async def fund_all_agents(req: FundAgentRequest):
    """Mint `amount` AGT tokens to all 4 on-chain agent wallets."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    if not _orchestrator._agent_token:
        raise HTTPException(status_code=503, detail="AgentToken contract not initialized — set AGENT_TOKEN_ADDRESS")
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    results = {}
    for agent_id in _ON_CHAIN_AGENTS:
        agent_wallet = _orchestrator.agents.get(agent_id, {}).get("wallet_address")
        if not agent_wallet:
            results[agent_id] = {"ok": False, "error": "wallet not found"}
            continue
        try:
            result = await _orchestrator._agent_token.mint(
                deployer_pk=settings.deployer_private_key,
                agent_address=agent_wallet,
                amount_tokens=req.amount,
            )
            results[agent_id] = {"ok": True, "tx": result.get("tx_hash")}
        except Exception as e:
            results[agent_id] = {"ok": False, "error": str(e)}

    return {"status": "all_funded", "amount": req.amount, "results": results}
