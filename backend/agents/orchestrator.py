import asyncio
import json
import logging
import time
from pathlib import Path
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


def _load_local_deployment():
    """Override settings contract addresses and agent PKs from somnia-local.json if .env has placeholders."""
    json_path = Path(__file__).parent.parent.parent / "contracts" / "deployments" / "somnia-local.json"
    if not json_path.exists():
        return
    try:
        dep = json.loads(json_path.read_text())
        c = dep.get("contracts", {})
        if c.get("Exchange", {}).get("address") and not _is_address(settings.exchange_address):
            settings.exchange_address         = c["Exchange"]["address"]
            settings.treasury_address         = c["Treasury"]["address"]
            settings.agent_coordinator_address = c["AgentCoordinator"]["address"]
            settings.agent_registry_address   = c.get("AgentRegistry", {}).get("address", settings.agent_registry_address)
            logger.info(f"Loaded contract addresses from {json_path.name}")

        # Load agent PKs if .env has placeholders (enables zero-config local dev)
        agents_data = dep.get("agents", {})
        pk_map = {
            "market_maker":    "market_maker_pk",
            "momentum_trader": "momentum_trader_pk",
            "arbitrage_agent": "arbitrage_agent_pk",
            "risk_manager":    "risk_manager_pk",
        }
        for agent_id, pk_key in pk_map.items():
            pk = agents_data.get(agent_id, {}).get("pk", "")
            current = getattr(settings, pk_key, "")
            if pk and (not current or current == "0x0000000000000000000000000000000000000000000000000000000000000000"):
                setattr(settings, pk_key, pk)
                logger.info(f"Loaded {agent_id} PK from {json_path.name}")
    except Exception as e:
        logger.warning(f"Could not load somnia-local.json: {e}")


class AgentOrchestrator:
    def __init__(self, hub: ConnectionManager):
        self._hub = hub

        _load_local_deployment()

        self._price_tracker = ChainPriceTracker(initial_price=settings.initial_price)
        self._state_bus = MarketStateBus(self._price_tracker)

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

        # Address → agent_id mapping — built once, shared by both polling loops
        self._wallet_to_id: dict[str, str] = {
            a["wallet_address"].lower(): a["agent_id"] for a in self.agents.values()
        }
        # Tracks the block at which each agent's last DecisionTriggered event fired
        self._decision_trigger_blocks: dict[str, int] = {}

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
            "recent_fills": [],
            "somnia_block_ms": settings.somnia_block_ms,
            "agents": {
                cfg["id"]: {
                    "agent_id":                 cfg["id"],
                    "agent_name":               cfg["name"],
                    "decisions_total":          0,
                    "buy_count":                0,
                    "sell_count":               0,
                    "hold_count":               0,
                    "failures":                 0,
                    "orders_placed":            0,
                    "treasury_balance":         0.0,
                    "last_decision":            None,
                    "last_price":               0.0,
                    "last_order_id":            None,
                    "last_fetched_price":       0.0,
                    "loop_stopped":             False,
                    "loop_stopped_reason":      None,
                    "trade_pnl":                0.0,
                    "total_buy_volume":         0.0,
                    "total_sell_volume":        0.0,
                    "avg_decision_latency_ms":  0.0,
                    "decision_latency_count":   0,
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
                    candle_updates: dict[int, dict] = {}

                    for event in events:
                        buyer_id  = self._wallet_to_id.get(event["buyer"].lower())
                        seller_id = self._wallet_to_id.get(event["seller"].lower())
                        completed_bar = await self._state_bus.record_fill(
                            event["price"], event["amount"], buyer_id, seller_id
                        )
                        self._record_pnl_from_trade(event, buyer_id, seller_id)
                        if completed_bar:
                            candle_updates[completed_bar["time"]] = completed_bar

                    current = self._price_tracker.get_current_bar()
                    if current:
                        candle_updates[current["time"]] = current

                    for bar in sorted(candle_updates.values(), key=lambda b: b["time"]):
                        await self._hub.broadcast({"type": "candle", "data": bar})

                    if events:
                        from_block = max(e["block"] for e in events) + 1

            except Exception as e:
                logger.error(f"Trade event poll error: {e}")

            await asyncio.sleep(1.0)

    def _record_pnl_from_trade(self, event: dict, buyer_id: Optional[str], seller_id: Optional[str]):
        """Update per-agent P&L and recent_fills from a TradeExecuted event."""
        trade_value = event["price"] * event["amount"]
        metrics = self._chain_metrics

        if buyer_id and buyer_id in metrics["agents"]:
            metrics["agents"][buyer_id]["trade_pnl"]       -= trade_value
            metrics["agents"][buyer_id]["total_buy_volume"] += trade_value

        if seller_id and seller_id in metrics["agents"]:
            metrics["agents"][seller_id]["trade_pnl"]        += trade_value
            metrics["agents"][seller_id]["total_sell_volume"] += trade_value

        metrics["recent_fills"].insert(0, {
            "price":        round(event["price"], 4),
            "amount":       round(event["amount"], 4),
            "buyer_agent":  buyer_id or "external",
            "seller_agent": seller_id or "external",
            "block":        event["block"],
        })
        metrics["recent_fills"] = metrics["recent_fills"][:20]

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

        while True:
            try:
                from_block = await self._collect_chain_metrics(from_block, self._wallet_to_id)
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

                if ev["event"] == "DecisionTriggered" and agent:
                    self._decision_trigger_blocks[ev.get("agentId", "")] = ev["block"]

                elif ev["event"] == "DecisionExecuted" and agent:
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

                    # Latency: blocks from trigger to execution × ms per block
                    agent_id_str = ev.get("agentId", "")
                    trigger_block = self._decision_trigger_blocks.get(agent_id_str, 0)
                    block_ms = metrics.get("somnia_block_ms", 0)
                    if trigger_block and block_ms:
                        delta_blocks = ev["block"] - trigger_block
                        latency_ms   = delta_blocks * block_ms
                        count        = agent["decision_latency_count"]
                        agent["avg_decision_latency_ms"] = round(
                            (agent["avg_decision_latency_ms"] * count + latency_ms) / (count + 1), 1
                        )
                        agent["decision_latency_count"] += 1

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

            real_book = await self._exchange.get_order_book(10)
            self._state_bus.set_order_book(real_book["bids"], real_book["asks"])

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
