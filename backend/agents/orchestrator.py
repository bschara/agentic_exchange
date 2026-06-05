import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

from eth_account import Account

from config import settings
from market.price_engine import ChainPriceTracker
from market.state_bus import MarketStateBus
from blockchain.contracts import (
    ExchangeContract, TreasuryContract, AgentCoordinatorContract,
    AgentRegistryContract, AgentTokenContract, QuoteTokenContract,
)
from api.websocket_hub import ConnectionManager
from agents.metrics_collector import MetricsCollector, empty_agent_metrics
from agents.token_replenisher import TokenReplenisher
from market.price_feed import fetch_eth_usd
from agents.watchdog import AgentWatchdog

logger = logging.getLogger(__name__)

_ZERO = "0x0000000000000000000000000000000000000000"

AGENT_CONFIGS = [
    {"id": "market_maker"},
    {"id": "momentum_trader"},
    {"id": "arbitrage_agent"},
    {"id": "risk_manager"},
    {"id": "noise_trader"},
]


def _is_address(addr: str) -> bool:
    import re
    return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", addr)) and addr != _ZERO


def _load_local_deployment():
    json_path = Path(__file__).parent.parent.parent / "contracts" / "deployments" / "somnia-local.json"
    if not json_path.exists():
        return
    try:
        dep = json.loads(json_path.read_text())
        c = dep.get("contracts", {})
        is_local = "127.0.0.1" in settings.somnia_rpc_url or "localhost" in settings.somnia_rpc_url
        if c.get("Exchange", {}).get("address") and (is_local or not _is_address(settings.exchange_address)):
            settings.exchange_address          = c["Exchange"]["address"]
            settings.treasury_address          = c["Treasury"]["address"]
            settings.agent_coordinator_address = c["AgentCoordinator"]["address"]
            settings.agent_registry_address    = c.get("AgentRegistry", {}).get("address", settings.agent_registry_address)
            settings.agent_token_address       = c.get("AgentToken", {}).get("address", settings.agent_token_address)
            settings.quote_token_address       = c.get("QuoteToken", {}).get("address", settings.quote_token_address)
            logger.info(f"Loaded contract addresses from {json_path.name}")

    except Exception as e:
        logger.warning(f"Could not load somnia-local.json: {e}")


class AgentOrchestrator:
    def __init__(self, hub: ConnectionManager):
        self._hub = hub

        _load_local_deployment()

        try:
            settings.deployer_address = Account.from_key(settings.deployer_private_key).address
        except Exception:
            logger.warning("Could not derive deployer address from deployer_private_key")

        self._price_tracker = ChainPriceTracker(initial_price=settings.initial_price)
        self._state_bus = MarketStateBus(self._price_tracker)

        # Contracts
        self._exchange: Optional[ExchangeContract] = None
        self._treasury: Optional[TreasuryContract] = None
        self._coordinator: Optional[AgentCoordinatorContract] = None
        self._registry: Optional[AgentRegistryContract] = None
        self._agent_token: Optional[AgentTokenContract] = None
        self._quote_token: Optional[QuoteTokenContract] = None

        if _is_address(settings.exchange_address):
            self._exchange = ExchangeContract(settings.exchange_address, settings.somnia_rpc_url)
            self._treasury = TreasuryContract(settings.treasury_address, settings.somnia_rpc_url)
            if _is_address(settings.agent_coordinator_address):
                self._coordinator = AgentCoordinatorContract(
                    settings.agent_coordinator_address, settings.somnia_rpc_url
                )
        if _is_address(settings.agent_registry_address):
            self._registry = AgentRegistryContract(settings.agent_registry_address, settings.somnia_rpc_url)
        if _is_address(settings.agent_token_address):
            self._agent_token = AgentTokenContract(settings.agent_token_address, settings.somnia_rpc_url)
        if _is_address(settings.quote_token_address):
            self._quote_token = QuoteTokenContract(settings.quote_token_address, settings.somnia_rpc_url)

        self.paused_agents: set[str] = set()
        self._order_to_agent: dict[int, str] = {}
        self._chain_metrics: dict = self._build_initial_chain_metrics()

        # All system agents operate through the coordinator pool — no individual wallets.
        self.agents: dict[str, dict] = {}
        for cfg in AGENT_CONFIGS:
            self.agents[cfg["id"]] = {
                "agent_id":   cfg["id"],
                "agent_name": cfg["id"],
            }

        self._wallet_to_id: dict[str, str] = {}

        self._reload_user_agents_from_db()

        # Sub-components (created after agents dict is populated)
        self._watchdog: Optional[AgentWatchdog] = None
        self._metrics_collector = MetricsCollector(
            coordinator=self._coordinator,
            exchange=self._exchange,
            treasury=self._treasury,
            registry=self._registry,
            price_tracker=self._price_tracker,
            state_bus=self._state_bus,
            hub=self._hub,
            agents=self.agents,
            chain_metrics=self._chain_metrics,
            paused_agents=self.paused_agents,
            wallet_to_id=self._wallet_to_id,
            order_to_agent=self._order_to_agent,
            on_agent_seen=lambda agent_id: (
                self._watchdog.mark_seen(agent_id) if self._watchdog else None
            ),
            rpc_url=settings.somnia_rpc_url,
        )
        self._token_replenisher = TokenReplenisher(
            quote_token=self._quote_token,
            agent_token=self._agent_token,
            deployer_pk=settings.deployer_private_key,
            coordinator_address=settings.agent_coordinator_address,
        )

        # Task handles
        self._poll_task: Optional[asyncio.Task] = None
        self._snapshot_task: Optional[asyncio.Task] = None
        self._metrics_task: Optional[asyncio.Task] = None
        self._token_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None

    def _build_initial_chain_metrics(self) -> dict:
        return {
            "coordinator_balance": 0.0,
            "total_locked": 0.0,
            "spread_pct": 0.0,
            "buy_depth": 0,
            "sell_depth": 0,
            "loop_stopped_any": False,
            "recent_fills": [],
            "coalition_alert": None,
            "somnia_block_ms": settings.somnia_block_ms,
            "agents": {cfg["id"]: empty_agent_metrics(cfg["id"]) for cfg in AGENT_CONFIGS},
            "last_update": 0.0,
        }

    async def start_all(self):
        logger.info("Starting orchestrator...")
        try:
            live_price = float(await fetch_eth_usd())
            self._price_tracker.price = live_price
            logger.info(f"Price engine seeded from live ETH/USD: ${live_price:.0f}")
        except Exception as exc:
            logger.warning(f"Live price fetch failed, keeping default ${self._price_tracker.price:.0f}: {exc}")

        self._poll_task     = asyncio.create_task(self._metrics_collector.run_trade_poll())
        self._snapshot_task = asyncio.create_task(self._snapshot_broadcast_loop())
        self._metrics_task  = asyncio.create_task(self._contract_metrics_poll_loop())
        self._token_task    = asyncio.create_task(self._token_replenisher.run())

        if self._coordinator:
            logger.info("Firing initial on-chain triggers (contract self-loops after this)...")
            _on_chain = {"market_maker", "momentum_trader", "arbitrage_agent", "risk_manager", "noise_trader"}

            self._watchdog = AgentWatchdog(
                coordinator=self._coordinator,
                paused_agents=self.paused_agents,
                chain_metrics=self._chain_metrics,
                agents=self.agents,
                deployer_pk=settings.deployer_private_key,
                deployer_address=settings.deployer_address,
            )

            for cfg in AGENT_CONFIGS:
                if cfg["id"] not in _on_chain:
                    continue
                try:
                    result = await self._coordinator.trigger_decision(
                        agent_pk=settings.deployer_private_key,
                        agent_id=cfg["id"],
                    )
                    logger.info(f"  {cfg['id']} initial trigger: {result.get('tx_hash')}")
                except Exception as e:
                    logger.error(f"  {cfg['id']} initial trigger FAILED: {e}")
                finally:
                    # Always set a baseline so the watchdog doesn't fire immediately
                    self._watchdog.mark_seen(cfg["id"])
                await asyncio.sleep(2.0)

            self._watchdog_task = asyncio.create_task(self._watchdog.run())

            # Recover user agents loaded from DB that may not have been set up yet
            for agent_id, info in list(self.agents.items()):
                if info.get("is_user_agent") and info.get("owner_address"):
                    asyncio.create_task(
                        self._ensure_user_agent_setup(agent_id, info["owner_address"])
                    )
        else:
            logger.info("No AgentCoordinator — running in observe-only mode.")

        logger.info("All loops started.")

    async def stop_all(self):
        for task in [
            self._poll_task, self._snapshot_task, self._metrics_task,
            self._token_task, self._watchdog_task,
        ]:
            if task:
                task.cancel()

    async def inject_event(self, event_type: str, params: dict):
        price_before = self._price_tracker.price
        logger.info(f"Injecting event: {event_type}")
        await self._state_bus.inject_event(event_type, params)

        _shock = {
            "whale_buy": 1.03, "whale_sell": 0.97, "flash_crash": 0.92,
            "news_event": 1.015, "volatility_spike": 1.0,
        }
        event_descriptions = {
            "whale_buy":        "Whale buy: +3% price impact",
            "whale_sell":       "Whale sell: -3% price impact",
            "volatility_spike": "Volatility spike: ±2% × 5 ticks",
            "flash_crash":      "Flash crash: -8% price shock",
            "news_event":       "News event: +1.5% upside",
        }
        price_after = price_before * _shock.get(event_type, 1.0)
        await self._hub.broadcast({
            "type": "event_injected",
            "data": {
                "event_type":   event_type,
                "description":  event_descriptions.get(event_type, event_type),
                "price_before": round(price_before, 4),
                "price_after":  round(price_after, 4),
                "timestamp":    time.time(),
            },
        })

    def get_agent_states(self) -> dict:
        return self._chain_metrics.get("agents", {})

    # ── Internal loops ────────────────────────────────────────────────────────

    async def _snapshot_broadcast_loop(self):
        while True:
            try:
                snapshot = await self._state_bus.get_snapshot()
                await self._hub.broadcast({
                    "type": "market_snapshot",
                    "data": snapshot,
                    "timestamp": time.time(),
                })
            except Exception as e:
                logger.error(f"Snapshot broadcast error: {e}")
            await asyncio.sleep(3.0)

    async def _contract_metrics_poll_loop(self):
        from_block = 0  # start from genesis to catch all historical events on every restart
        logger.info("Contract metrics poll starting from block 0 (full history scan)")
        while True:
            try:
                # Detect new agents BEFORE collect() so their metrics are populated
                # before historical DecisionExecuted events are processed.
                if self._registry:
                    for agent_id in await self._registry.get_all_agent_ids():
                        if agent_id not in self.agents:
                            info = await self._registry.get_agent(agent_id)
                            if info and info.get("agentOwner"):
                                await self._on_user_agent_registered(
                                    agent_id,
                                    info["agentOwner"],
                                    info.get("name", agent_id),
                                    info.get("icon", "🤖"),
                                    int(info.get("riskLevel", 3)),
                                )
                from_block = await self._metrics_collector.collect(from_block)
            except Exception as e:
                logger.error(f"Contract metrics poll error: {e}")
            await asyncio.sleep(5.0)

    # ── User agent support ────────────────────────────────────────────────────

    def _reload_user_agents_from_db(self) -> None:
        try:
            from agents.user_agents_db import UserAgentsDB
            for record in UserAgentsDB().load():
                agent_id = record["agent_id"]
                if agent_id in self.agents:
                    continue
                self.agents[agent_id] = {
                    "agent_id":      agent_id,
                    "agent_name":    record.get("name", agent_id),
                    "wallet_address": "",
                    "owner_address": record.get("owner_address", ""),
                    "icon":          record.get("icon", "🤖"),
                    "risk_level":    record.get("risk_level", 3),
                    "is_user_agent": True,
                }
                entry = empty_agent_metrics(agent_id)
                entry["agent_name"] = record.get("name", agent_id)
                self._chain_metrics["agents"][agent_id] = entry
                logger.info(f"Reloaded user agent from DB: {agent_id}")
        except Exception as e:
            logger.warning(f"_reload_user_agents_from_db failed: {e}")

    async def _ensure_user_agent_setup(self, agent_id: str, owner: str) -> None:
        """Allocate capital, fund STT, and fire a trigger for a user agent if not yet done."""
        if not self._coordinator:
            return
        try:
            token_bal, _ = await self._coordinator.get_agent_allocation(agent_id)
        except Exception:
            token_bal = 0.0

        if token_bal == 0.0:
            try:
                await self._coordinator.allocate_to_agent(
                    settings.deployer_private_key,
                    agent_id,
                    owner,
                    token_amount=1000.0,
                    quote_amount=1000.0,
                )
                logger.info(f"User agent {agent_id} allocated 1000 sETH / 1000 USDC")
            except Exception as e:
                logger.error(f"allocateToAgent failed for {agent_id}: {e}")
                if self._watchdog:
                    self._watchdog.mark_seen(agent_id)
                return  # watchdog will retry with allocation check every 45s

        try:
            stt = await self._coordinator.get_user_stt_balance(owner)
            if stt < 0.05:
                await self._coordinator.deposit_stt_for_owner(
                    settings.deployer_private_key, owner, amount_eth=0.1
                )
                logger.info(f"User agent {agent_id}: deposited 0.1 STT for owner {owner}")
        except Exception as e:
            logger.error(f"depositStt failed for {agent_id}: {e}")

        try:
            result = await self._coordinator.trigger_decision(
                agent_pk=settings.deployer_private_key,
                agent_id=agent_id,
            )
            logger.info(f"User agent {agent_id} triggered: {result.get('tx_hash', '')[:16]}")
        except Exception as e:
            logger.error(f"trigger_decision failed for {agent_id}: {e}")
        finally:
            if self._watchdog:
                self._watchdog.mark_seen(agent_id)

    async def _on_user_agent_registered(
        self, agent_id: str, owner: str, name: str, icon: str = "🤖", risk_level: int = 3
    ) -> None:
        try:
            from agents.user_agents_db import UserAgentsDB
            UserAgentsDB().upsert_from_event(agent_id, owner, name, icon, risk_level)
        except Exception as e:
            logger.warning(f"Could not persist user agent {agent_id}: {e}")

        if agent_id not in self.agents:
            self.agents[agent_id] = {
                "agent_id":      agent_id,
                "agent_name":    name,
                "wallet_address": "",
                "owner_address": owner.lower(),
                "icon":          icon,
                "risk_level":    risk_level,
                "is_user_agent": True,
            }
        if agent_id not in self._chain_metrics["agents"]:
            entry = empty_agent_metrics(agent_id)
            entry["agent_name"] = name
            self._chain_metrics["agents"][agent_id] = entry

        logger.info(f"User agent registered: {agent_id} (owner={owner})")
        await self._ensure_user_agent_setup(agent_id, owner)
