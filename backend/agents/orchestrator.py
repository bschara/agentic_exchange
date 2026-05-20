import asyncio
import logging
import time
from typing import Optional

from config import settings
from market.price_engine import PriceEngine
from market.state_bus import MarketStateBus
from blockchain.contracts import ExchangeContract, TreasuryContract, AgentCoordinatorContract
from api.websocket_hub import ConnectionManager
from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# Global singletons accessed by graph nodes
_global_state_bus: Optional[MarketStateBus] = None
_global_exchange: Optional[ExchangeContract] = None
_global_treasury: Optional[TreasuryContract] = None
_global_coordinator: Optional[AgentCoordinatorContract] = None
_global_hub: Optional[ConnectionManager] = None


AGENT_CONFIGS = [
    {"id": "market_maker", "name": "MM-Prime", "strategy": "market_maker", "pk_key": "market_maker_pk"},
    {"id": "momentum_trader", "name": "Momentum-Alpha", "strategy": "momentum_trader", "pk_key": "momentum_trader_pk"},
    {"id": "arbitrage_agent", "name": "Arb-Scanner", "strategy": "arbitrage_agent", "pk_key": "arbitrage_agent_pk"},
    {"id": "risk_manager", "name": "Risk-Shield", "strategy": "risk_manager", "pk_key": "risk_manager_pk"},
]


class AgentOrchestrator:
    def __init__(self, hub: ConnectionManager):
        global _global_hub
        _global_hub = hub
        self._hub = hub

        # Price engine
        self._price_engine = PriceEngine(
            initial_price=settings.initial_price,
            volatility=settings.price_volatility,
            drift=settings.price_drift,
        )

        # State bus
        self._state_bus = MarketStateBus(self._price_engine)
        self._state_bus.synthesize_order_book(settings.initial_price)

        global _global_state_bus
        _global_state_bus = self._state_bus

        # Contracts
        self._exchange: Optional[ExchangeContract] = None
        self._treasury: Optional[TreasuryContract] = None

        self._coordinator: Optional[AgentCoordinatorContract] = None

        if (settings.exchange_address != "0x0000000000000000000000000000000000000000" and
                not settings.simulation_mode):
            self._exchange = ExchangeContract(settings.exchange_address, settings.somnia_rpc_url)
            self._treasury = TreasuryContract(settings.treasury_address, settings.somnia_rpc_url)
            if settings.agent_coordinator_address != "0x0000000000000000000000000000000000000000":
                self._coordinator = AgentCoordinatorContract(
                    settings.agent_coordinator_address, settings.somnia_rpc_url
                )

        global _global_exchange, _global_treasury, _global_coordinator
        _global_exchange = self._exchange
        _global_treasury = self._treasury
        _global_coordinator = self._coordinator

        # Agents
        self.agents: dict[str, BaseAgent] = {}
        for cfg in AGENT_CONFIGS:
            pk = getattr(settings, cfg["pk_key"])
            agent = BaseAgent(
                agent_id=cfg["id"],
                agent_name=cfg["name"],
                strategy=cfg["strategy"],
                private_key=pk,
            )
            self.agents[cfg["id"]] = agent

        self._tasks: dict[str, asyncio.Task] = {}
        self._price_task: Optional[asyncio.Task] = None
        self._snapshot_task: Optional[asyncio.Task] = None
        self._event_vol_multiplier_reset: Optional[float] = None

    async def start_all(self):
        logger.info("Starting orchestrator...")

        # 1. Price loop (GBM simulation, anchored to chain when trades exist)
        self._price_task = asyncio.create_task(self._price_loop())

        # 2. Chain price sync — polls Exchange.getLastTradePrice() every 5s
        self._chain_sync_task = asyncio.create_task(self._chain_price_sync_loop())

        # 3. Snapshot broadcast loop
        self._snapshot_task = asyncio.create_task(self._snapshot_broadcast_loop())

        # 4. Start agents with staggered timing
        for i, (agent_id, agent) in enumerate(self.agents.items()):
            await asyncio.sleep(2.0)  # stagger by 2s to offset Anthropic API calls
            self._tasks[agent_id] = asyncio.create_task(agent.run())
            logger.info(f"Started agent: {agent.agent_name}")

        # 5. Fire one initial on-chain trigger per agent — after this the contract
        #    self-re-triggers via handleDecision() → _retrigger() indefinitely.
        if self._coordinator:
            logger.info("Firing initial on-chain triggers (agents will self-loop after this)...")
            for cfg in AGENT_CONFIGS:
                pk = getattr(settings, cfg["pk_key"])
                try:
                    result = await self._coordinator.trigger_decision(
                        agent_pk=pk,
                        agent_id=cfg["id"],
                    )
                    logger.info(f"  {cfg['id']} initial trigger: {result.get('tx_hash')}")
                except Exception as e:
                    logger.error(f"  {cfg['id']} initial trigger failed: {e}")
                await asyncio.sleep(1.0)

        logger.info("All agents started.")

    async def stop_all(self):
        for agent in self.agents.values():
            agent.stop()
        for task in self._tasks.values():
            task.cancel()
        for task in [self._price_task, self._snapshot_task,
                     getattr(self, "_chain_sync_task", None)]:
            if task:
                task.cancel()

    async def inject_event(self, event_type: str, params: dict):
        price_before = self._price_engine.price
        logger.info(f"Injecting event: {event_type}")

        if event_type == "whale_buy":
            self._price_engine.apply_price_shock(+0.03)
        elif event_type == "whale_sell":
            self._price_engine.apply_price_shock(-0.03)
        elif event_type == "volatility_spike":
            self._price_engine.set_volatility_multiplier(5.0, 30.0)
        elif event_type == "flash_crash":
            self._price_engine.apply_price_shock(-0.08)
            self._price_engine.set_volatility_multiplier(8.0, 20.0)
        elif event_type == "news_event":
            self._price_engine.set_volatility_multiplier(3.0, 15.0)
            self._price_engine.apply_price_shock(0.015)

        await self._state_bus.inject_event(event_type, params)
        price_after = self._price_engine.price

        event_descriptions = {
            "whale_buy": "Whale buy: +3% price impact",
            "whale_sell": "Whale sell: -3% price impact",
            "volatility_spike": "Volatility spike: 5x vol for 30s",
            "flash_crash": "Flash crash: -8% price shock",
            "news_event": "News event: 3x vol + 1.5% upside",
        }

        await self._hub.broadcast({
            "type": "event_injected",
            "data": {
                "event_type": event_type,
                "description": event_descriptions.get(event_type, event_type),
                "price_before": round(price_before, 4),
                "price_after": round(price_after, 4),
                "timestamp": time.time(),
            },
        })

    async def _price_loop(self):
        last_bar_time = 0
        while True:
            try:
                self._price_engine.next_price()
                price = self._price_engine.price

                # Regenerate synthetic order book around new price
                self._state_bus.synthesize_order_book(price)

                # Emit new candle bar if completed
                bar = self._price_engine.get_current_bar()
                if bar and bar["time"] != last_bar_time:
                    last_bar_time = bar["time"]
                    await self._hub.broadcast({"type": "candle", "data": bar})

            except Exception as e:
                logger.error(f"Price loop error: {e}")

            await asyncio.sleep(1.0)

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
            await asyncio.sleep(2.0)

    async def _chain_price_sync_loop(self):
        """
        Polls Exchange.getLastTradePrice() every 5s. When real on-chain trades
        exist, anchors the GBM simulation to the actual matched price so the
        chart reflects true price discovery rather than pure simulation.
        """
        while True:
            try:
                if self._exchange:
                    chain_price = await self._exchange.get_last_trade_price()
                    if chain_price > 0:
                        self._price_engine.set_chain_price(chain_price)
                        # Also update spread from real on-chain order book
                        bid, bid_exists = await self._exchange.get_best_bid()
                        ask, ask_exists = await self._exchange.get_best_ask()
                        if bid_exists and ask_exists:
                            self._state_bus.synthesize_order_book(
                                (bid + ask) / 2
                            )
            except Exception as e:
                logger.debug(f"Chain price sync: {e}")
            await asyncio.sleep(5.0)

    def get_agent_states(self) -> dict:
        return {a_id: a.get_state_summary() for a_id, a in self.agents.items()}
