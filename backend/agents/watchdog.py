import asyncio
import logging
import time

from blockchain.client import refresh_nonce

logger = logging.getLogger(__name__)

_ON_CHAIN_AGENTS = {"market_maker", "momentum_trader", "arbitrage_agent", "risk_manager", "noise_trader"}
_STALL_SECONDS = 45.0


class AgentWatchdog:
    """
    Monitors on-chain agent loops and re-triggers any that stop emitting
    DecisionTriggered events for longer than _STALL_SECONDS.
    """

    def __init__(
        self,
        coordinator,
        paused_agents: set,
        chain_metrics: dict,
        agents: dict,
        deployer_pk: str,
        deployer_address: str,
    ):
        self._coordinator = coordinator
        self._paused_agents = paused_agents
        self._chain_metrics = chain_metrics
        self._agents = agents
        self._deployer_pk = deployer_pk
        self._deployer_address = deployer_address
        self._last_seen: dict[str, float] = {}

    def mark_seen(self, agent_id: str, t: float | None = None) -> None:
        self._last_seen[agent_id] = t if t is not None else time.time()

    async def run(self) -> None:
        await asyncio.sleep(30.0)
        while True:
            now = time.time()
            await self._check_system_agents(now)
            await self._check_user_agents(now)
            await asyncio.sleep(15.0)

    async def _check_system_agents(self, now: float) -> None:
        for agent_id in _ON_CHAIN_AGENTS:
            agent_data = self._chain_metrics.get("agents", {}).get(agent_id, {})
            if agent_data.get("loop_stopped") or agent_id in self._paused_agents:
                continue
            last_seen = self._last_seen.get(agent_id)
            if last_seen is None or now - last_seen > _STALL_SECONDS:
                elapsed = f"{now - last_seen:.0f}s" if last_seen is not None else "never"
                logger.warning(f"[watchdog] {agent_id} stalled ({elapsed}) — re-triggering")
                await self._retrigger(agent_id, now)

    async def _check_user_agents(self, now: float) -> None:
        for agent_id, agent_info in list(self._agents.items()):
            if not agent_info.get("is_user_agent"):
                continue
            agent_data = self._chain_metrics.get("agents", {}).get(agent_id, {})
            if agent_data.get("loop_stopped") or agent_id in self._paused_agents:
                continue
            last_seen = self._last_seen.get(agent_id)
            if last_seen is None or now - last_seen > _STALL_SECONDS:
                logger.warning(f"[watchdog] user agent {agent_id} stalled — re-triggering")
                await self._retrigger(agent_id, now)

    async def _retrigger(self, agent_id: str, now: float) -> None:
        agent_info = self._agents.get(agent_id, {})
        if agent_info.get("is_user_agent"):
            owner = agent_info.get("owner_address", "")
            if owner:
                try:
                    stt = await self._coordinator.get_user_stt_balance(owner)
                    if stt < 0.05:
                        await self._coordinator.deposit_stt_for_owner(
                            self._deployer_pk, owner, amount_eth=0.1
                        )
                        logger.info(f"[watchdog] topped up STT for {agent_id}")
                except Exception as e:
                    logger.warning(f"[watchdog] STT top-up for {agent_id} failed: {e}")
                try:
                    token_bal, _ = await self._coordinator.get_agent_allocation(agent_id)
                    if token_bal == 0.0:
                        await self._coordinator.allocate_to_agent(
                            self._deployer_pk, agent_id, owner,
                            token_amount=1000.0, quote_amount=1000.0,
                        )
                        logger.info(f"[watchdog] allocated virtual balances for {agent_id}")
                except Exception as e:
                    logger.warning(f"[watchdog] allocation for {agent_id} failed: {e}")
        try:
            refresh_nonce(self._deployer_address)
            result = await self._coordinator.trigger_decision(
                agent_pk=self._deployer_pk, agent_id=agent_id
            )
            logger.info(f"[watchdog] {agent_id} retrigger tx={result.get('tx_hash', '')[:16]}")
            self._last_seen[agent_id] = now
        except Exception as e:
            logger.error(f"[watchdog] {agent_id} retrigger failed: {e}")
        await asyncio.sleep(2.0)
