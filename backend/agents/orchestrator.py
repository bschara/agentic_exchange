import asyncio
import logging
import time
from typing import Optional

from eth_account import Account
from web3 import Web3

from config import settings
from market.price_engine import ChainPriceTracker
from market.state_bus import MarketStateBus
from blockchain.contracts import ExchangeContract, TreasuryContract, AgentCoordinatorContract
from api.websocket_hub import ConnectionManager

logger = logging.getLogger(__name__)

_ZERO = "0x0000000000000000000000000000000000000000"

def _is_address(addr: str) -> bool:
    """Returns True if addr looks like a real 20-byte Ethereum address (not a placeholder)."""
    import re
    return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", addr)) and addr != _ZERO


AGENT_CONFIGS = [
    {"id": "market_maker",     "name": "MM-Prime",       "pk_key": "market_maker_pk"},
    {"id": "momentum_trader",  "name": "Momentum-Alpha", "pk_key": "momentum_trader_pk"},
    {"id": "arbitrage_agent",  "name": "Arb-Scanner",    "pk_key": "arbitrage_agent_pk"},
    {"id": "risk_manager",     "name": "Risk-Shield",    "pk_key": "risk_manager_pk"},
]


class AgentOrchestrator:
    def __init__(self, hub: ConnectionManager):
        self._hub = hub

        self._price_tracker = ChainPriceTracker(initial_price=settings.initial_price)
        self._state_bus = MarketStateBus(self._price_tracker)
        self._state_bus.synthesize_order_book(settings.initial_price)

        # Contracts — only instantiated when addresses are valid 20-byte hex strings
        self._exchange: Optional[ExchangeContract] = None
        self._treasury: Optional[TreasuryContract] = None
        self._coordinator: Optional[AgentCoordinatorContract] = None

        if _is_address(settings.exchange_address):
            self._exchange = ExchangeContract(settings.exchange_address, settings.somnia_rpc_url)
            self._treasury = TreasuryContract(settings.treasury_address, settings.somnia_rpc_url)
            if _is_address(settings.agent_coordinator_address):
                self._coordinator = AgentCoordinatorContract(
                    settings.agent_coordinator_address, settings.somnia_rpc_url
                )

        # Lightweight agent registry — wallet addresses needed for metrics + treasury polling
        self.agents: dict[str, dict] = {}
        for cfg in AGENT_CONFIGS:
            pk = getattr(settings, cfg["pk_key"])
            try:
                wallet = Account.from_key(pk).address
            except Exception:
                wallet = "0x0000000000000000000000000000000000000000"
                logger.warning(f"Invalid private key for {cfg['id']} — wallet address set to zero")
            self.agents[cfg["id"]] = {
                "agent_id":       cfg["id"],
                "agent_name":     cfg["name"],
                "wallet_address": wallet,
            }

        self._poll_task: Optional[asyncio.Task] = None
        self._snapshot_task: Optional[asyncio.Task] = None
        self._metrics_task: Optional[asyncio.Task] = None
        self._chain_metrics: dict = self._build_initial_chain_metrics()

    def _build_initial_chain_metrics(self) -> dict:
        return {
            "coordinator_balance": 0.0,
            "total_locked": 0.0,
            "spread_pct": 0.0,
            "buy_depth": 0,
            "sell_depth": 0,
            "loop_stopped_any": False,
            "agents": {
                cfg["id"]: {
                    "agent_id":           cfg["id"],
                    "agent_name":         cfg["name"],
                    "decisions_total":    0,
                    "buy_count":          0,
                    "sell_count":         0,
                    "hold_count":         0,
                    "failures":           0,
                    "orders_placed":      0,
                    "treasury_balance":   0.0,
                    "last_decision":      None,
                    "last_price":         0.0,
                    "last_order_id":      None,
                    "last_fetched_price": 0.0,
                    "loop_stopped":       False,
                    "loop_stopped_reason": None,
                }
                for cfg in AGENT_CONFIGS
            },
            "last_update": 0.0,
        }

    async def start_all(self):
        logger.info("Starting orchestrator...")

        self._poll_task     = asyncio.create_task(self._trade_event_poll_loop())
        self._snapshot_task = asyncio.create_task(self._snapshot_broadcast_loop())
        self._metrics_task  = asyncio.create_task(self._contract_metrics_poll_loop())

        if self._coordinator:
            logger.info("Firing initial on-chain triggers (contract self-loops after this)...")
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
        else:
            logger.info("No AgentCoordinator configured — running in observe-only mode.")

        logger.info("All loops started.")

    async def stop_all(self):
        for task in [self._poll_task, self._snapshot_task, self._metrics_task]:
            if task:
                task.cancel()

    async def inject_event(self, event_type: str, params: dict):
        price_before = self._price_tracker.price
        logger.info(f"Injecting event: {event_type}")
        await self._state_bus.inject_event(event_type, params)

        event_descriptions = {
            "whale_buy":        "Whale buy: +3% price impact",
            "whale_sell":       "Whale sell: -3% price impact",
            "volatility_spike": "Volatility spike: 5x vol for 30s",
            "flash_crash":      "Flash crash: -8% price shock",
            "news_event":       "News event: 3x vol + 1.5% upside",
        }

        await self._hub.broadcast({
            "type": "event_injected",
            "data": {
                "event_type":  event_type,
                "description": event_descriptions.get(event_type, event_type),
                "price_before": round(price_before, 4),
                "price_after":  round(price_before, 4),
                "timestamp":    time.time(),
            },
        })

    async def _trade_event_poll_loop(self):
        """Polls Exchange.TradeExecuted events every 1s — drives the chart and price tracker."""
        from_block = 0
        if self._exchange:
            try:
                from blockchain.client import get_web3
                w3 = get_web3(settings.somnia_rpc_url)
                from_block = w3.eth.block_number
                logger.info(f"Trade event poll starting from block {from_block}")
            except Exception as e:
                logger.warning(f"Could not get current block, starting from 0: {e}")

        while True:
            try:
                if self._exchange:
                    events = await self._exchange.get_recent_trade_events(from_block)
                    for event in events:
                        completed_bar = await self._state_bus.record_fill(event["price"], event["amount"])
                        self._state_bus.synthesize_order_book(event["price"])

                        if completed_bar:
                            await self._hub.broadcast({"type": "candle", "data": completed_bar})

                        current = self._price_tracker.get_current_bar()
                        if current:
                            await self._hub.broadcast({"type": "candle", "data": current})

                    if events:
                        from_block = max(e["block"] for e in events) + 1

            except Exception as e:
                logger.error(f"Trade event poll error: {e}")

            await asyncio.sleep(1.0)

    async def _snapshot_broadcast_loop(self):
        """Broadcasts market snapshot every 2s to keep the dashboard fresh between fills."""
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

    async def _contract_metrics_poll_loop(self):
        """Polls on-chain contract state every 5s and broadcasts as chain_metrics."""
        from_block = 0
        if self._coordinator or self._exchange:
            try:
                from blockchain.client import get_web3
                w3 = get_web3(settings.somnia_rpc_url)
                from_block = w3.eth.block_number
                logger.info(f"Contract metrics poll starting from block {from_block}")
            except Exception as e:
                logger.warning(f"Could not get start block for metrics: {e}")

        wallet_to_id = {a["wallet_address"].lower(): a["agent_id"] for a in self.agents.values()}

        while True:
            try:
                from_block = await self._collect_chain_metrics(from_block, wallet_to_id)
            except Exception as e:
                logger.error(f"Contract metrics poll error: {e}")
            await asyncio.sleep(5.0)

    async def _collect_chain_metrics(self, from_block: int, wallet_to_id: dict) -> int:
        """Reads on-chain metrics, updates self._chain_metrics, broadcasts, returns next from_block."""
        metrics = self._chain_metrics
        metrics["last_update"] = time.time()
        max_block = from_block

        # ── AgentCoordinator ────────────────────────────────────────────────────
        if self._coordinator:
            metrics["coordinator_balance"] = await self._coordinator.get_balance()

            for ev in await self._coordinator.get_coordinator_events(from_block):
                max_block = max(max_block, ev["block"])
                agent = metrics["agents"].get(ev.get("agentId"))

                if ev["event"] == "DecisionExecuted" and agent:
                    decision = ev.get("decision", "")
                    agent["decisions_total"] += 1
                    if decision == "BUY":
                        agent["buy_count"] += 1
                    elif decision == "SELL":
                        agent["sell_count"] += 1
                    else:
                        agent["hold_count"] += 1
                    agent["last_decision"] = decision
                    price_wei = ev.get("price", 0)
                    agent["last_price"] = float(Web3.from_wei(price_wei, "ether")) if price_wei else 0.0
                    agent["last_order_id"] = ev.get("orderId")

                elif ev["event"] == "DecisionFailed" and agent:
                    agent["failures"] += 1

                elif ev["event"] == "LoopStopped" and agent:
                    agent["loop_stopped"] = True
                    agent["loop_stopped_reason"] = ev.get("reason", "")
                    metrics["loop_stopped_any"] = True
                    logger.warning(f"On-chain loop stopped for {ev.get('agentId')}: {ev.get('reason')}")

                elif ev["event"] == "LLMRequestFired" and agent:
                    agent["last_fetched_price"] = float(ev.get("fetchedPrice", 0))

        # ── Exchange ─────────────────────────────────────────────────────────────
        if self._exchange:
            bid, bid_ok = await self._exchange.get_best_bid()
            ask, ask_ok = await self._exchange.get_best_ask()
            if bid_ok and ask_ok and bid > 0:
                metrics["spread_pct"] = round((ask - bid) / bid * 100, 4)

            depth = await self._exchange.get_order_book_depth()
            metrics["buy_depth"]  = depth["buy_count"]
            metrics["sell_depth"] = depth["sell_count"]

            for ev in await self._exchange.get_order_placed_events(from_block):
                max_block = max(max_block, ev["block"])
                agent_id = wallet_to_id.get(ev["agent"].lower())
                if agent_id and agent_id in metrics["agents"]:
                    metrics["agents"][agent_id]["orders_placed"] += 1

        # ── Treasury ─────────────────────────────────────────────────────────────
        if self._treasury:
            metrics["total_locked"] = await self._treasury.get_total_locked()
            for agent in self.agents.values():
                balance = await self._treasury.get_balance(agent["wallet_address"])
                metrics["agents"][agent["agent_id"]]["treasury_balance"] = balance

        await self._hub.broadcast({
            "type": "chain_metrics",
            "data": metrics,
            "timestamp": metrics["last_update"],
        })

        return max_block + 1 if max_block > from_block else from_block

    def get_agent_states(self) -> dict:
        return self._chain_metrics.get("agents", {})
