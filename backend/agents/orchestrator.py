import asyncio
import json
import logging
import math
import random
import time
from pathlib import Path
from typing import Optional

from eth_account import Account
from web3 import Web3

from config import settings
from market.price_engine import ChainPriceTracker
from market.state_bus import MarketStateBus
from blockchain.contracts import ExchangeContract, TreasuryContract, AgentCoordinatorContract, AgentRegistryContract, AgentTokenContract
from api.websocket_hub import ConnectionManager

logger = logging.getLogger(__name__)

_ZERO = "0x0000000000000000000000000000000000000000"

def _is_address(addr: str) -> bool:
    """Returns True if addr looks like a real 20-byte Ethereum address (not a placeholder)."""
    import re
    return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", addr)) and addr != _ZERO


AGENT_CONFIGS = [
    {"id": "market_maker",    "pk_key": "market_maker_pk"},
    {"id": "momentum_trader", "pk_key": "momentum_trader_pk"},
    {"id": "arbitrage_agent", "pk_key": "arbitrage_agent_pk"},
    {"id": "risk_manager",    "pk_key": "risk_manager_pk"},
    {"id": "noise_trader",    "pk_key": "noise_trader_pk"},
]


def _load_local_deployment():
    """Override settings contract addresses and agent PKs from somnia-local.json if .env has placeholders."""
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
            logger.info(f"Loaded contract addresses from {json_path.name}")

        # Load agent PKs if .env has placeholders or on local devnet (enables zero-config local dev)
        agents_data = dep.get("agents", {})
        pk_map = {
            "market_maker":    "market_maker_pk",
            "momentum_trader": "momentum_trader_pk",
            "arbitrage_agent": "arbitrage_agent_pk",
            "risk_manager":    "risk_manager_pk",
            "noise_trader":    "noise_trader_pk",
        }
        for agent_id, pk_key in pk_map.items():
            pk = agents_data.get(agent_id, {}).get("pk", "")
            current = getattr(settings, pk_key, "")
            if pk and (is_local or not current or current == "0x0000000000000000000000000000000000000000000000000000000000000000"):
                setattr(settings, pk_key, pk)
                logger.info(f"Loaded {agent_id} PK from {json_path.name}")
    except Exception as e:
        logger.warning(f"Could not load somnia-local.json: {e}")


class AgentOrchestrator:
    def __init__(self, hub: ConnectionManager):
        self._hub = hub

        _load_local_deployment()

        # Derive deployer address from private key so auth.py can compare signatures
        try:
            settings.deployer_address = Account.from_key(settings.deployer_private_key).address
        except Exception:
            logger.warning("Could not derive deployer address from deployer_private_key")

        self._price_tracker = ChainPriceTracker(initial_price=settings.initial_price)
        self._state_bus = MarketStateBus(self._price_tracker)

        # Contracts — only instantiated when addresses are valid 20-byte hex strings
        self._exchange: Optional[ExchangeContract] = None
        self._treasury: Optional[TreasuryContract] = None
        self._coordinator: Optional[AgentCoordinatorContract] = None
        self._registry: Optional[AgentRegistryContract] = None
        self._agent_token: Optional[AgentTokenContract] = None

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

        # Set of agent IDs whose on-chain loop has been deliberately paused
        self.paused_agents: set[str] = set()

        # Maps Exchange order ID → agent_id for orders placed via AgentCoordinator.
        # Coordinator's msg.sender is the contract address (not individual agent wallets),
        # so wallet_to_id lookups fail for on-chain trades. This map is built from
        # DecisionExecuted events which carry both agentId and orderId.
        self._order_to_agent: dict[int, str] = {}

        # Must be initialized before the agents loop so wallet_address can be propagated
        self._chain_metrics: dict = self._build_initial_chain_metrics()

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
                "agent_name":     cfg["id"],  # overwritten by registry sync on first cycle
                "wallet_address": wallet,
            }
            # Propagate wallet_address into chain_metrics initial state
            if cfg["id"] in self._chain_metrics.get("agents", {}):
                self._chain_metrics["agents"][cfg["id"]]["wallet_address"] = wallet

        # Address ↔ agent_id mappings — built once, extended as new agents are discovered
        self._wallet_to_id: dict[str, str] = {
            a["wallet_address"].lower(): a["agent_id"] for a in self.agents.values()
        }
        self._id_to_wallet: dict[str, str] = {
            a["agent_id"]: a["wallet_address"].lower() for a in self.agents.values()
        }
        # Tracks the block at which each agent's last DecisionTriggered event fired
        self._decision_trigger_blocks: dict[str, int] = {}
        # Tracks wall-clock time of last observed DecisionTriggered per agent (for watchdog)
        self._watchdog_last_seen: dict[str, float] = {}

        # Load persisted user agents into memory on startup (no re-trigger — loops already running)
        self._reload_user_agents_from_db()

        self._poll_task: Optional[asyncio.Task] = None
        self._snapshot_task: Optional[asyncio.Task] = None
        self._metrics_task: Optional[asyncio.Task] = None
        self._noise_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None

    @staticmethod
    def _empty_agent_metrics(agent_id: str) -> dict:
        return {
            "agent_id":                 agent_id,
            "agent_name":               agent_id,  # overwritten by registry sync
            "strategy":                 "",
            "reputation":               100,
            "trades_on_chain":          0,
            "registered_at":            0,
            "active":                   True,
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
            "last_context":             "",   # full LLM prompt from last LLMRequestFired
            "win_streak":               0,    # consecutive filled orders
            "loop_stopped":             False,
            "loop_stopped_reason":      None,
            "paused":                   False,
            "agt_balance":              0.0,
            "trade_pnl":                0.0,
            "total_buy_volume":         0.0,
            "total_sell_volume":        0.0,
            "avg_decision_latency_ms":  0.0,
            "decision_latency_count":   0,
            "net_position":             0.0,
            "unrealized_pnl":           0.0,
            "wallet_address":           "",
        }

    def _build_initial_chain_metrics(self) -> dict:
        return {
            "coordinator_balance": 0.0,
            "total_locked": 0.0,
            "spread_pct": 0.0,
            "buy_depth": 0,
            "sell_depth": 0,
            "loop_stopped_any": False,
            "recent_fills": [],
            "coalition_alert": None,  # set when CoalitionFormed fires, cleared after broadcast
            "somnia_block_ms": settings.somnia_block_ms,
            "agents": {
                cfg["id"]: self._empty_agent_metrics(cfg["id"])
                for cfg in AGENT_CONFIGS
            },
            "last_update": 0.0,
        }

    async def start_all(self):
        logger.info("Starting orchestrator...")

        self._poll_task     = asyncio.create_task(self._trade_event_poll_loop())
        self._snapshot_task = asyncio.create_task(self._snapshot_broadcast_loop())
        self._metrics_task  = asyncio.create_task(self._contract_metrics_poll_loop())

        if self._exchange:
            self._noise_task = asyncio.create_task(self._noise_trader_loop())

        if self._coordinator:
            logger.info("Firing initial on-chain triggers (contract self-loops after this)...")
            _on_chain_agents = {"market_maker", "momentum_trader", "arbitrage_agent", "risk_manager"}
            for cfg in AGENT_CONFIGS:
                if cfg["id"] not in _on_chain_agents:
                    continue  # noise_trader uses Python loop only
                pk = getattr(settings, cfg["pk_key"])
                try:
                    result = await self._coordinator.trigger_decision(
                        agent_pk=pk,
                        agent_id=cfg["id"],
                    )
                    logger.info(f"  {cfg['id']} initial trigger: {result.get('tx_hash')}")
                    self._watchdog_last_seen[cfg["id"]] = time.time()
                except Exception as e:
                    logger.error(f"  {cfg['id']} initial trigger FAILED: {e}")
                await asyncio.sleep(2.0)  # extra breathing room for the daemon
            self._watchdog_task = asyncio.create_task(self._agent_watchdog_loop())
        else:
            logger.info("No AgentCoordinator configured — running in observe-only mode.")

        logger.info("All loops started.")

    async def stop_all(self):
        for task in [self._poll_task, self._snapshot_task, self._metrics_task, self._noise_task, self._watchdog_task]:
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
                # Update order→agent mapping BEFORE fetching trades so attribution is correct
                # even when DecisionExecuted and TradeExecuted land in the same block.
                if self._coordinator:
                    dec_events = await self._coordinator.get_decision_executed_events(from_block)
                    for ev in dec_events:
                        order_id = int(ev.get("orderId", 0))
                        agent_id_str = ev.get("agentId", "")
                        if order_id > 0 and agent_id_str:
                            self._order_to_agent[order_id] = agent_id_str

                if self._exchange:
                    events = await self._exchange.get_recent_trade_events(from_block)
                    candle_updates: dict[int, dict] = {}

                    for event in events:
                        # For on-chain agents, buyer/seller is the coordinator contract address,
                        # not individual wallets. Fall back to order_id lookup built from
                        # DecisionExecuted events which map order_id → agent_id.
                        buyer_id = (
                            self._wallet_to_id.get(event["buyer"].lower()) or
                            self._order_to_agent.get(int(event.get("buy_order_id", 0)))
                        )
                        seller_id = (
                            self._wallet_to_id.get(event["seller"].lower()) or
                            self._order_to_agent.get(int(event.get("sell_order_id", 0)))
                        )
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
        """Update per-agent P&L, net position, and recent_fills from a TradeExecuted event."""
        price = event["price"]
        amount = event["amount"]
        trade_value = price * amount
        metrics = self._chain_metrics

        if buyer_id and buyer_id in metrics["agents"]:
            metrics["agents"][buyer_id]["trade_pnl"]       -= trade_value
            metrics["agents"][buyer_id]["total_buy_volume"] += trade_value
            metrics["agents"][buyer_id]["net_position"]    += amount

        if seller_id and seller_id in metrics["agents"]:
            metrics["agents"][seller_id]["trade_pnl"]        += trade_value
            metrics["agents"][seller_id]["total_sell_volume"] += trade_value
            metrics["agents"][seller_id]["net_position"]     -= amount

        metrics["recent_fills"].insert(0, {
            "price":        round(price, 4),
            "amount":       round(amount, 4),
            "buyer_agent":  buyer_id or "external",
            "seller_agent": seller_id or "external",
            "block":        event["block"],
            "tx_hash":      event.get("tx_hash", ""),
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

    async def _sync_registry_data(self):
        """Sync agent name/icon/riskLevel from the unified string-keyed AgentRegistry."""
        if not self._registry:
            return
        try:
            agent_ids = await self._registry.get_all_agent_ids()
            for agent_id in agent_ids:
                info = await self._registry.get_agent(agent_id)
                if not info or not info.get("agentOwner"):
                    continue
                if agent_id not in self._chain_metrics["agents"]:
                    self._chain_metrics["agents"][agent_id] = self._empty_agent_metrics(agent_id)
                ag = self._chain_metrics["agents"][agent_id]
                ag["agent_name"]   = info.get("name") or agent_id
                ag["registered_at"] = info.get("createdAt", 0)
                ag["active"]        = info.get("active", True)
        except Exception as e:
            logger.debug(f"Registry sync failed: {e}")

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
                await self._sync_registry_data()
                # Poll AgentRegistered events from registry to discover newly created agents
                if self._registry:
                    for ev in await self._registry.get_agent_registered_events(from_block - 1 if from_block > 0 else 0):
                        agent_id = ev["agentId"]
                        if agent_id not in self.agents:
                            await self._on_user_agent_registered(
                                agent_id, ev["agentOwner"], ev["name"], ev["icon"], ev["riskLevel"]
                            )
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
                    agent_id_str = ev.get("agentId", "")
                    self._decision_trigger_blocks[agent_id_str] = ev["block"]
                    self._watchdog_last_seen[agent_id_str] = time.time()

                elif ev["event"] == "DecisionExecuted" and agent:
                    decision = ev.get("decision", "")
                    order_id = int(ev.get("orderId", 0))
                    agent_id_str = ev.get("agentId", "")
                    agent["decisions_total"] += 1
                    if decision == "BUY":
                        agent["buy_count"] += 1
                    elif decision == "SELL":
                        agent["sell_count"] += 1
                    else:
                        agent["hold_count"] += 1
                    agent["last_decision"] = decision
                    agent["win_streak"] = int(ev.get("streak", 0))
                    price_wei = ev.get("price", 0)
                    agent["last_price"] = float(Web3.from_wei(price_wei, "ether")) if price_wei else 0.0
                    agent["last_order_id"] = order_id
                    # Track order → agent mapping for P&L attribution (coordinator is msg.sender,
                    # not individual wallet, so wallet_to_id fails for on-chain trades)
                    if order_id > 0 and agent_id_str:
                        self._order_to_agent[order_id] = agent_id_str
                        agent["orders_placed"] += 1

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
                    reason = ev.get("reason", "")
                    agent["loop_stopped"] = True
                    agent["loop_stopped_reason"] = reason
                    if reason != "paused":
                        metrics["loop_stopped_any"] = True
                    logger.warning(f"On-chain loop stopped for {ev.get('agentId')}: {reason}")

                elif ev["event"] == "AgentPaused":
                    agent_id_str = ev.get("agentId", "")
                    self.paused_agents.add(agent_id_str)
                    if agent:
                        agent["paused"] = True
                        agent["loop_stopped"] = True
                        agent["loop_stopped_reason"] = "paused"
                    logger.info(f"Agent paused on-chain: {agent_id_str}")

                elif ev["event"] == "AgentResumed":
                    agent_id_str = ev.get("agentId", "")
                    self.paused_agents.discard(agent_id_str)
                    if agent:
                        agent["paused"] = False
                        agent["loop_stopped"] = False
                        agent["loop_stopped_reason"] = None
                    logger.info(f"Agent resumed on-chain: {agent_id_str}")


                elif ev["event"] == "LLMRequestFired" and agent:
                    agent["last_fetched_price"] = float(ev.get("fetchedPrice", 0))
                    agent["last_context"] = ev.get("context", "")

                elif ev["event"] == "CoalitionFormed":
                    direction  = ev.get("direction", "")
                    price_wei  = ev.get("price", 0)
                    order_id   = ev.get("orderId", 0)
                    price_eth  = float(Web3.from_wei(price_wei, "ether")) if price_wei else 0.0
                    alert = {
                        "direction":   direction,
                        "agent_count": int(ev.get("agentCount", 3)),
                        "price":       round(price_eth, 4),
                        "order_id":    order_id,
                        "block":       ev["block"],
                        "timestamp":   time.time(),
                    }
                    metrics["coalition_alert"] = alert
                    metrics["recent_fills"].insert(0, {
                        "price":        round(price_eth, 4),
                        "amount":       0.003,  # 3× base = ORDER_AMOUNT_BASE * 3
                        "buyer_agent":  "coalition" if direction == "BUY" else "external",
                        "seller_agent": "coalition" if direction == "SELL" else "external",
                        "block":        ev["block"],
                        "tx_hash":      "",
                        "category":     "coalition",
                    })
                    metrics["recent_fills"] = metrics["recent_fills"][:20]
                    logger.info(f"Coalition formed: {direction} × 3 agents @ ${price_eth:.2f} orderId={order_id}")
                    await self._hub.broadcast({
                        "type": "coalition_alert",
                        "data": alert,
                        "timestamp": time.time(),
                    })

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

            # Mark-to-market unrealized P&L for all agents
            current_price = await self._exchange.get_last_trade_price()
            if current_price == 0.0:
                current_price = self._price_tracker.price
            if current_price > 0:
                for agent_data in metrics["agents"].values():
                    net_pos = agent_data["net_position"]
                    agent_data["unrealized_pnl"] = round(net_pos * current_price, 4)

            # Risk warnings — emitted when market conditions are abnormal
            spread_pct = metrics["spread_pct"]
            if spread_pct > 2.0:
                await self._hub.broadcast({
                    "type": "risk_warning",
                    "data": {
                        "from_agent": "risk_manager",
                        "severity": "HIGH" if spread_pct > 5.0 else "MEDIUM",
                        "warning_type": "HIGH_SPREAD",
                        "message": f"Spread at {spread_pct:.2f}% — liquidity critically low",
                        "timestamp": time.time(),
                    },
                })

            closes = self._price_tracker.get_recent_closes(10)
            if len(closes) >= 5:
                returns = [
                    math.log(closes[i] / closes[i - 1])
                    for i in range(1, len(closes))
                    if closes[i - 1] > 0
                ]
                if returns:
                    vol = (sum(r ** 2 for r in returns) / len(returns)) ** 0.5 * 100
                    if vol > 2.0:
                        await self._hub.broadcast({
                            "type": "risk_warning",
                            "data": {
                                "from_agent": "risk_manager",
                                "severity": "HIGH" if vol > 5.0 else "MEDIUM",
                                "warning_type": "VOLATILITY_SPIKE",
                                "message": f"Volatility spike: {vol:.2f}% stddev over last 10 bars",
                                "timestamp": time.time(),
                            },
                        })

            # OrderPlaced events use msg.sender = coordinator address for on-chain agents,
            # so wallet_to_id lookup fails. orders_placed is now attributed via DecisionExecuted
            # (see _order_to_agent above). Only count noise_trader orders here via wallet lookup.
            for ev in await self._exchange.get_order_placed_events(from_block):
                max_block = max(max_block, ev["block"])
                agent_id = wallet_to_id.get(ev["agent"].lower())
                if agent_id == "noise_trader" and agent_id in metrics["agents"]:
                    metrics["agents"][agent_id]["orders_placed"] += 1

        # ── Treasury ─────────────────────────────────────────────────────────────
        if self._treasury:
            metrics["total_locked"] = await self._treasury.get_total_locked()
            for agent in self.agents.values():
                balance = await self._treasury.get_balance(agent["wallet_address"])
                metrics["agents"][agent["agent_id"]]["treasury_balance"] = balance

        # ── AgentToken balances ───────────────────────────────────────────────────
        # AgentCoordinator is msg.sender for all on-chain placeOrder calls, so the
        # Exchange pulls AGT escrow from the coordinator address — not individual wallets.
        # Polling individual agent wallets always returns 0.
        if self._agent_token:
            coordinator_agt = 0.0
            if _is_address(settings.agent_coordinator_address):
                coordinator_agt = await self._agent_token.get_balance(settings.agent_coordinator_address)
            for agent in self.agents.values():
                agent_id = agent["agent_id"]
                if agent_id == "noise_trader":
                    bal = await self._agent_token.get_balance(agent["wallet_address"])
                    metrics["agents"][agent_id]["agt_balance"] = bal
                else:
                    metrics["agents"][agent_id]["agt_balance"] = coordinator_agt

        # Ensure wallet_address is always current in metrics (supports explorer links)
        for agent in self.agents.values():
            agent_id = agent["agent_id"]
            if agent_id in metrics["agents"]:
                metrics["agents"][agent_id]["wallet_address"] = agent["wallet_address"]

        await self._hub.broadcast({
            "type": "chain_metrics",
            "data": metrics,
            "timestamp": metrics["last_update"],
        })

        return max_block + 1 if max_block > from_block else from_block

    async def _noise_trader_loop(self):
        """Places random orders every 4-6 seconds to keep the book alive."""
        noise_pk = getattr(settings, "noise_trader_pk", "")
        logger.info("Noise trader loop started")
        while True:
            try:
                ref_price = self._price_tracker.price
                if ref_price > 0 and self._exchange:
                    # Noise trader has no AGT tokens so SELL orders revert (Exchange locks AGT on SELL).
                    # Always BUY — main agents provide the SELL side via AgentCoordinator.
                    is_buy = True
                    slippage = random.uniform(-0.005, 0.005)
                    price = ref_price * (1 + slippage)
                    amount = round(random.uniform(0.03, 0.08), 3)
                    result = await self._exchange.place_order(noise_pk, is_buy, price, amount)
                    side = "BUY" if is_buy else "SELL"
                    logger.debug(f"Noise trader: {side} {amount} @ ${price:.2f} tx={result.get('tx_hash', '')[:12]}")
            except Exception as e:
                logger.debug(f"Noise trader order failed: {e}")
            await asyncio.sleep(random.uniform(4.0, 6.0))

    async def _agent_watchdog_loop(self):
        """Re-triggers any on-chain agent whose loop has stalled (no DecisionTriggered in 45 s)."""
        _on_chain_agents = {"market_maker", "momentum_trader", "arbitrage_agent", "risk_manager"}
        STALL_SECONDS = 45.0
        await asyncio.sleep(30.0)  # grace period for first cycle to complete
        while True:
            if self._coordinator:
                now = time.time()

                # System agents
                for cfg in AGENT_CONFIGS:
                    if cfg["id"] not in _on_chain_agents:
                        continue
                    agent_id = cfg["id"]
                    agent_data = self._chain_metrics.get("agents", {}).get(agent_id, {})
                    if agent_data.get("loop_stopped") or agent_id in self.paused_agents:
                        continue
                    last_seen = self._watchdog_last_seen.get(agent_id, 0.0)
                    if now - last_seen > STALL_SECONDS:
                        logger.warning(f"[watchdog] {agent_id} stalled ({now - last_seen:.0f}s) — re-triggering")
                        pk = getattr(settings, cfg["pk_key"])
                        try:
                            result = await self._coordinator.trigger_decision(agent_pk=pk, agent_id=agent_id)
                            logger.info(f"[watchdog] {agent_id} retrigger tx={result.get('tx_hash', '')[:16]}")
                            self._watchdog_last_seen[agent_id] = now
                        except Exception as e:
                            logger.error(f"[watchdog] {agent_id} retrigger failed: {e}")
                        await asyncio.sleep(2.0)

                # User agents — use deployer key for gas (triggerAgentDecision has no onlyOwner)
                for agent_id, agent_info in list(self.agents.items()):
                    if not agent_info.get("is_user_agent"):
                        continue
                    agent_data = self._chain_metrics.get("agents", {}).get(agent_id, {})
                    if agent_data.get("loop_stopped") or agent_id in self.paused_agents:
                        continue
                    last_seen = self._watchdog_last_seen.get(agent_id, 0.0)
                    if last_seen > 0 and now - last_seen > STALL_SECONDS:
                        logger.warning(f"[watchdog] user agent {agent_id} stalled — re-triggering")
                        try:
                            result = await self._coordinator.trigger_decision(
                                agent_pk=settings.deployer_private_key, agent_id=agent_id
                            )
                            logger.info(f"[watchdog] {agent_id} retrigger tx={result.get('tx_hash', '')[:16]}")
                            self._watchdog_last_seen[agent_id] = now
                        except Exception as e:
                            logger.error(f"[watchdog] user agent {agent_id} retrigger failed: {e}")
                        await asyncio.sleep(2.0)

            await asyncio.sleep(15.0)

    # ── User agent support ────────────────────────────────────────────────────────

    def _reload_user_agents_from_db(self) -> None:
        """Re-populate in-memory dicts from the on-chain event cache on startup."""
        try:
            from agents.user_agents_db import UserAgentsDB
            for record in UserAgentsDB().load():
                agent_id = record["agent_id"]
                if agent_id in self.agents:
                    continue  # already known
                self.agents[agent_id] = {
                    "agent_id":      agent_id,
                    "agent_name":    record.get("name", agent_id),
                    "wallet_address": "",   # user agents have no dedicated wallet
                    "owner_address": record.get("owner_address", ""),
                    "icon":          record.get("icon", "🤖"),
                    "risk_level":    record.get("risk_level", 3),
                    "is_user_agent": True,
                }
                entry = self._empty_agent_metrics(agent_id)
                entry["agent_name"] = record.get("name", agent_id)
                self._chain_metrics["agents"][agent_id] = entry
                logger.info(f"Reloaded user agent from DB: {agent_id}")
        except Exception as e:
            logger.warning(f"_reload_user_agents_from_db failed: {e}")

    async def _on_user_agent_registered(
        self, agent_id: str, owner: str, name: str, icon: str = "🤖", risk_level: int = 3
    ) -> None:
        """Called when a new AgentOwnerSet event is detected on-chain."""
        try:
            from agents.user_agents_db import UserAgentsDB
            UserAgentsDB().upsert_from_event(agent_id, owner, name, icon, risk_level)
        except Exception as e:
            logger.warning(f"Could not persist user agent {agent_id}: {e}")

        # Register in orchestrator memory
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
            entry = self._empty_agent_metrics(agent_id)
            entry["agent_name"] = name
            self._chain_metrics["agents"][agent_id] = entry

        logger.info(f"User agent registered: {agent_id} (owner={owner})")

        # Kick off the on-chain loop using deployer key for gas (triggerAgentDecision has no onlyOwner)
        if self._coordinator:
            try:
                result = await self._coordinator.trigger_decision(
                    agent_pk=settings.deployer_private_key,
                    agent_id=agent_id,
                )
                self._watchdog_last_seen[agent_id] = time.time()
                logger.info(f"User agent {agent_id} initial trigger tx={result.get('tx_hash', '')[:16]}")
            except Exception as e:
                logger.error(f"User agent {agent_id} initial trigger failed: {e}")

    def get_agent_states(self) -> dict:
        return self._chain_metrics.get("agents", {})
