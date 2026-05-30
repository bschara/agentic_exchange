import asyncio
import logging
import math
import time
from typing import Callable, Optional

from web3 import Web3

logger = logging.getLogger(__name__)


def empty_agent_metrics(agent_id: str) -> dict:
    return {
        "agent_id":                 agent_id,
        "agent_name":               agent_id,
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
        "last_context":             "",
        "win_streak":               0,
        "loop_stopped":             False,
        "loop_stopped_reason":      None,
        "paused":                   False,
        "agt_balance":              0.0,
        "quote_balance":            0.0,
        "initial_quote_balance":    None,
        "trade_pnl":                0.0,
        "total_buy_volume":         0.0,
        "total_sell_volume":        0.0,
        "avg_decision_latency_ms":  0.0,
        "decision_latency_count":   0,
        "net_position":             0.0,
        "avg_cost":                 0.0,
        "unrealized_pnl":           0.0,
        "wallet_address":           "",
    }


class MetricsCollector:
    """
    Drives two async loops:
      - run_trade_poll(): polls trade/fill events every 1 s, updates P&L + candles
      - collect(from_block): called every 5 s by the orchestrator to gather all
        coordinator, exchange, and treasury metrics, then broadcasts chain_metrics
    """

    def __init__(
        self,
        coordinator,
        exchange,
        treasury,
        registry,
        price_tracker,
        state_bus,
        hub,
        agents: dict,
        chain_metrics: dict,
        paused_agents: set,
        wallet_to_id: dict,
        order_to_agent: dict,
        on_agent_seen: Callable[[str], None],
        rpc_url: str,
    ):
        self._coordinator = coordinator
        self._exchange = exchange
        self._treasury = treasury
        self._registry = registry
        self._price_tracker = price_tracker
        self._state_bus = state_bus
        self._hub = hub
        self._agents = agents
        self._chain_metrics = chain_metrics
        self._paused_agents = paused_agents
        self._wallet_to_id = wallet_to_id
        self._order_to_agent = order_to_agent
        self._on_agent_seen = on_agent_seen
        self._rpc_url = rpc_url
        self._decision_trigger_blocks: dict[str, int] = {}

    async def get_start_block(self) -> int:
        if not (self._coordinator or self._exchange):
            return 0
        try:
            from blockchain.client import get_web3
            w3 = get_web3(self._rpc_url)
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: w3.eth.block_number)
        except Exception as e:
            logger.warning(f"Could not get start block: {e}")
            return 0

    # ── Trade event poll (1 s) ────────────────────────────────────────────────

    async def run_trade_poll(self) -> None:
        from_block = await self.get_start_block()
        logger.info(f"Trade event poll starting from block {from_block}")
        while True:
            try:
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

    def _record_pnl_from_trade(
        self, event: dict, buyer_id: Optional[str], seller_id: Optional[str]
    ) -> None:
        price = event["price"]
        amount = event["amount"]
        trade_value = price * amount
        metrics = self._chain_metrics

        if buyer_id and buyer_id in metrics["agents"]:
            ag = metrics["agents"][buyer_id]
            prev_qty = max(ag["net_position"], 0.0)
            prev_cost = ag["avg_cost"]
            new_qty = prev_qty + amount
            ag["avg_cost"] = (prev_cost * prev_qty + price * amount) / new_qty
            ag["total_buy_volume"] += trade_value
            ag["net_position"] += amount

        if seller_id and seller_id in metrics["agents"]:
            ag = metrics["agents"][seller_id]
            avg_cost = ag["avg_cost"]
            long_qty = max(ag["net_position"], 0.0)
            closed_qty = min(amount, long_qty)
            if closed_qty > 0 and avg_cost > 0:
                ag["trade_pnl"] += (price - avg_cost) * closed_qty
            ag["total_sell_volume"] += trade_value
            ag["net_position"] -= amount
            if ag["net_position"] <= 0:
                ag["avg_cost"] = 0.0

        metrics["recent_fills"].insert(0, {
            "price":        round(price, 4),
            "amount":       round(amount, 4),
            "buyer_agent":  buyer_id or "external",
            "seller_agent": seller_id or "external",
            "block":        event["block"],
            "tx_hash":      event.get("tx_hash", ""),
        })
        metrics["recent_fills"] = metrics["recent_fills"][:20]

    # ── Contract metrics poll (5 s) ───────────────────────────────────────────

    async def collect(self, from_block: int) -> int:
        """Collect all chain metrics. Returns the next from_block to use."""
        metrics = self._chain_metrics
        metrics["last_update"] = time.time()
        max_block = from_block

        max_block = await self._process_coordinator_events(from_block, max_block)
        max_block = await self._process_exchange_metrics(from_block, max_block)
        await self._process_treasury_balances()
        await self._sync_registry_data()

        for agent in self._agents.values():
            agent_id = agent["agent_id"]
            if agent_id in metrics["agents"]:
                metrics["agents"][agent_id]["wallet_address"] = agent["wallet_address"]

        await self._hub.broadcast({
            "type": "chain_metrics",
            "data": metrics,
            "timestamp": metrics["last_update"],
        })
        return max_block + 1 if max_block > from_block else from_block

    async def _process_coordinator_events(self, from_block: int, max_block: int) -> int:
        if not self._coordinator:
            return max_block
        metrics = self._chain_metrics
        metrics["coordinator_balance"] = await self._coordinator.get_balance()

        for ev in await self._coordinator.get_coordinator_events(from_block):
            max_block = max(max_block, ev["block"])
            agent = metrics["agents"].get(ev.get("agentId"))

            if ev["event"] == "DecisionTriggered" and agent:
                agent_id_str = ev.get("agentId", "")
                self._decision_trigger_blocks[agent_id_str] = ev["block"]
                self._on_agent_seen(agent_id_str)

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
                if order_id > 0 and agent_id_str:
                    self._order_to_agent[order_id] = agent_id_str
                    agent["orders_placed"] += 1
                trigger_block = self._decision_trigger_blocks.get(agent_id_str, 0)
                block_ms = metrics.get("somnia_block_ms", 0)
                if trigger_block and block_ms:
                    delta_blocks = ev["block"] - trigger_block
                    latency_ms = delta_blocks * block_ms
                    count = agent["decision_latency_count"]
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
                self._paused_agents.add(agent_id_str)
                if agent:
                    agent["paused"] = True
                    agent["loop_stopped"] = True
                    agent["loop_stopped_reason"] = "paused"
                logger.info(f"Agent paused on-chain: {agent_id_str}")

            elif ev["event"] == "AgentResumed":
                agent_id_str = ev.get("agentId", "")
                self._paused_agents.discard(agent_id_str)
                if agent:
                    agent["paused"] = False
                    agent["loop_stopped"] = False
                    agent["loop_stopped_reason"] = None
                logger.info(f"Agent resumed on-chain: {agent_id_str}")

            elif ev["event"] == "LLMRequestFired" and agent:
                agent["last_fetched_price"] = float(ev.get("fetchedPrice", 0))
                agent["last_context"] = ev.get("context", "")

            elif ev["event"] == "CoalitionFormed":
                direction = ev.get("direction", "")
                price_wei = ev.get("price", 0)
                order_id = ev.get("orderId", 0)
                price_eth = float(Web3.from_wei(price_wei, "ether")) if price_wei else 0.0
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
                    "amount":       0.003,
                    "buyer_agent":  "coalition" if direction == "BUY" else "external",
                    "seller_agent": "coalition" if direction == "SELL" else "external",
                    "block":        ev["block"],
                    "tx_hash":      "",
                    "category":     "coalition",
                })
                metrics["recent_fills"] = metrics["recent_fills"][:20]
                logger.info(
                    f"Coalition formed: {direction} × 3 agents @ ${price_eth:.2f} orderId={order_id}"
                )
                await self._hub.broadcast({
                    "type": "coalition_alert",
                    "data": alert,
                    "timestamp": time.time(),
                })

        return max_block

    async def _process_exchange_metrics(self, from_block: int, max_block: int) -> int:
        if not self._exchange:
            return max_block
        metrics = self._chain_metrics

        bid, bid_ok = await self._exchange.get_best_bid()
        ask, ask_ok = await self._exchange.get_best_ask()
        if bid_ok and ask_ok and bid > 0:
            metrics["spread_pct"] = round((ask - bid) / bid * 100, 4)

        depth = await self._exchange.get_order_book_depth()
        metrics["buy_depth"] = depth["buy_count"]
        metrics["sell_depth"] = depth["sell_count"]

        real_book = await self._exchange.get_order_book(10)
        self._state_bus.set_order_book(real_book["bids"], real_book["asks"])

        current_price = await self._exchange.get_last_trade_price()
        if current_price == 0.0:
            current_price = self._price_tracker.price
        if current_price > 0:
            for agent_data in metrics["agents"].values():
                net_pos = agent_data["net_position"]
                avg_cost = agent_data["avg_cost"]
                agent_data["unrealized_pnl"] = (
                    round(net_pos * (current_price - avg_cost), 4)
                    if net_pos > 0 and avg_cost > 0
                    else 0.0
                )

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

        for ev in await self._exchange.get_order_placed_events(from_block):
            max_block = max(max_block, ev["block"])
            agent_id = self._wallet_to_id.get(ev["agent"].lower())
            if agent_id == "noise_trader" and agent_id in metrics["agents"]:
                metrics["agents"][agent_id]["orders_placed"] += 1

        return max_block

    async def _process_treasury_balances(self) -> None:
        if not self._treasury:
            return
        metrics = self._chain_metrics
        metrics["total_locked"] = await self._treasury.get_total_locked()
        for agent in self._agents.values():
            balance = await self._treasury.get_balance(agent["wallet_address"])
            metrics["agents"][agent["agent_id"]]["treasury_balance"] = balance

    async def _sync_registry_data(self) -> None:
        if not self._registry:
            return
        try:
            agent_ids = await self._registry.get_all_agent_ids()
            for agent_id in agent_ids:
                info = await self._registry.get_agent(agent_id)
                if not info or not info.get("agentOwner"):
                    continue
                if agent_id not in self._chain_metrics["agents"]:
                    self._chain_metrics["agents"][agent_id] = empty_agent_metrics(agent_id)
                ag = self._chain_metrics["agents"][agent_id]
                ag["agent_name"] = info.get("name") or agent_id
                ag["registered_at"] = info.get("createdAt", 0)
                ag["active"] = info.get("active", True)
        except Exception as e:
            logger.debug(f"Registry sync failed: {e}")
