import asyncio
import json
import logging
import math
import re
import time
import uuid
from typing import TYPE_CHECKING

import anthropic
import numpy as np

from config import settings
from graph.state import AgentState

if TYPE_CHECKING:
    from market.state_bus import MarketStateBus
    from blockchain.contracts import ExchangeContract, TreasuryContract
    from api.websocket_hub import ConnectionManager

logger = logging.getLogger(__name__)

_anthropic = anthropic.Anthropic(api_key=settings.anthropic_api_key)

SYSTEM_PROMPTS = {
    "market_maker": """You are MM-Prime, an autonomous market-making agent on the Somnia blockchain.

Your goal: Profit from the bid-ask spread by placing simultaneous buy and sell limit orders.
Strategy rules:
- If volatility < 2%: maintain 0.2% spread (bid at -0.1%, ask at +0.1% from mid)
- If volatility 2-4%: widen to 0.5% spread
- If volatility > 4%: widen to 1.0% spread
- Cancel stale orders if price moved > 0.5% from your order prices
- If risk warning received: reduce order sizes by 50%
- Max position size: 2.0 units

You MUST respond with a JSON decision in a ```json block.
Available actions: "place_order" (params: is_buy, price, amount), "cancel_all_orders" (no params), "hold" (no params).
amount must be between 0.1 and 1.0.""",

    "momentum_trader": """You are Momentum-Alpha, an autonomous momentum trading agent on Somnia.

Your goal: Ride price trends for directional profit.
Strategy rules:
- Strong uptrend (5-bar): enter LONG if not already long (place buy order at ask)
- Strong downtrend (5-bar): enter SHORT if not already short (place sell order at bid)
- If trend reverses: cancel all and flip
- If risk warning received: reduce position by 50% (cancel half orders)
- Max position size: 1.5 units
- Uptrend = last price > 5 bars ago price by > 0.3%

You MUST respond with a JSON decision in a ```json block.
Available actions: "place_order" (params: is_buy, price, amount), "cancel_all_orders" (no params), "hold" (no params).
amount must be between 0.1 and 1.0.""",

    "arbitrage_agent": """You are Arb-Scanner, an autonomous arbitrage agent on Somnia.

Your goal: Exploit temporary pricing inefficiencies in the order book.
Strategy rules:
- If bid-ask spread > 0.5% AND you have no active orders: place both a buy at best-bid+0.01% and sell at best-ask-0.01% to capture the spread
- If spread < 0.3%: hold (no profitable arb)
- If you have open arb positions and trend strongly moves one way, cancel the losing side
- Max position size: 1.0 units

You MUST respond with a JSON decision in a ```json block.
Available actions: "place_order" (params: is_buy, price, amount), "cancel_all_orders" (no params), "hold" (no params).
amount must be between 0.1 and 0.5.""",

    "risk_manager": """You are Risk-Shield, an autonomous risk management agent on Somnia.

Your goal: Monitor systemic risk and protect the portfolio ecosystem.
Strategy rules:
- If volatility > 4%: broadcast HIGH risk warning "Volatility spike detected, reduce positions"
- If volatility 2-4%: broadcast MEDIUM warning "Elevated volatility, exercise caution"
- If volatility < 2%: clear warnings (broadcast "Market stable")
- You ALSO trade: take small counter-trend positions to hedge (sell into spikes, buy into crashes)
- Max position size: 0.5 units for your own hedges
- When injected events detected: always broadcast a warning

You MUST respond with a JSON decision in a ```json block.
Available actions: "place_order" (params: is_buy, price, amount), "cancel_all_orders" (no params), "hold" (no params), "broadcast_warning" (params: severity, message).
amount must be between 0.05 and 0.5.""",
}


def _parse_decision(reasoning: str, agent_id: str, state: AgentState) -> dict:
    """Extract JSON decision from LLM reasoning, with robust fallback."""
    patterns = [
        r"```json\s*(\{.*?\})\s*```",
        r"```\s*(\{.*?\})\s*```",
        r'(\{"action".*?\})',
    ]
    for pat in patterns:
        match = re.search(pat, reasoning, re.DOTALL)
        if match:
            try:
                decision = json.loads(match.group(1))
                if "action" in decision:
                    return decision
            except json.JSONDecodeError:
                pass

    # Keyword fallback
    text = reasoning.lower()
    if "cancel" in text:
        return {"action": "cancel_all_orders", "reasoning_summary": "Cancelled by keyword match", "params": {}}
    if "buy" in text or "long" in text:
        price = state.get("current_price", 100.0)
        return {"action": "place_order", "reasoning_summary": "Buy inferred from reasoning", "params": {"is_buy": True, "price": round(price * 1.001, 4), "amount": 0.1}}
    if "sell" in text or "short" in text:
        price = state.get("current_price", 100.0)
        return {"action": "place_order", "reasoning_summary": "Sell inferred from reasoning", "params": {"is_buy": False, "price": round(price * 0.999, 4), "amount": 0.1}}

    return {"action": "hold", "reasoning_summary": "No clear signal", "params": {}}


def _validate_decision(decision: dict, state: AgentState) -> dict:
    """Apply risk limits to the parsed decision."""
    action = decision.get("action", "hold")
    params = decision.get("params", {})

    if action == "place_order":
        amount = float(params.get("amount", 0.1))
        price = float(params.get("price", state.get("current_price", 100.0)))

        # Cap at 10% of balance
        balance = state.get("onchain_balance", 1.0)
        max_amount = max(0.05, balance * 0.10 / max(price, 0.01))
        amount = min(amount, max_amount, 1.0)
        amount = max(amount, 0.05)

        # Reduce by 50% if risk warning active
        if state.get("agent_warnings"):
            amount *= 0.5
            amount = max(amount, 0.05)

        params["amount"] = round(amount, 4)
        params["price"] = round(price, 4)
        decision["params"] = params

    return decision


# Node functions

def observe_node(state: AgentState) -> AgentState:
    from agents.orchestrator import _global_state_bus, _global_exchange, _global_treasury

    async def _observe():
        bus = _global_state_bus
        exchange = _global_exchange
        treasury = _global_treasury

        ctx = await bus.get_market_context(state["agent_id"])
        snapshot = await bus.get_snapshot()
        warnings = await bus.get_active_warnings()
        events = await bus.get_injected_events()

        # Get onchain balance
        balance = 1.0
        if treasury:
            try:
                balance = await treasury.get_balance(state["wallet_address"])
            except Exception:
                pass

        # Price trend from recent closes
        closes = _global_state_bus._engine.get_recent_closes(10)
        if len(closes) >= 5:
            trend = "UP" if closes[-1] > closes[0] * 1.003 else "DOWN" if closes[-1] < closes[0] * 0.997 else "FLAT"
        else:
            trend = "FLAT"

        # Volatility estimate
        if len(closes) >= 5:
            returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
            vol = float(np.std(returns) * 100) if returns else 0.0
        else:
            vol = 0.0

        return {
            "market_context": ctx,
            "current_price": snapshot["price"],
            "spread_pct": snapshot["spread_pct"],
            "price_trend": trend,
            "volatility_estimate": round(vol, 4),
            "agent_warnings": warnings,
            "injected_events": events,
            "onchain_balance": balance,
        }

    try:
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(_observe())
    except RuntimeError:
        result = asyncio.run(_observe())

    return {**state, **result}


def reason_node(state: AgentState) -> AgentState:
    from agents.orchestrator import _global_coordinator

    # When AgentCoordinator is live, all decisions come from Somnia's on-chain LLM —
    # skip Claude entirely. The actual BUY/SELL/HOLD decision happens asynchronously
    # via the on-chain callback after validator consensus.
    if _global_coordinator:
        return {
            **state,
            "reasoning": (
                f"⬡ Somnia on-chain LLM agent active — {state['agent_name']} decision "
                f"delegated to validator consensus (loop #{state.get('loop_count', 0)})"
            ),
        }

    # Fallback: Claude reasoning (simulation mode or no coordinator configured)
    system_prompt = SYSTEM_PROMPTS.get(state["agent_id"], "You are a trading agent. Return a JSON decision.")
    position_desc = f"{state['current_position']:+.3f} ({state['position_side']})" if state.get("current_position") else "0.000 (FLAT)"

    user_prompt = f"""Current market conditions:
{state['market_context']}

Your state:
- Position: {position_desc}
- Session PnL: {state.get('pnl_session', 0.0):+.4f}
- Active orders: {len(state.get('active_order_ids', []))}
- Loop #{state.get('loop_count', 0)}
- Injected events: {state.get('injected_events', [])}

Analyze the market and decide your action. Be concise but specific about WHY you are taking this action.
Return your decision in a ```json block with keys: action, reasoning_summary, params."""

    try:
        response = _anthropic.messages.create(
            model=settings.claude_model,
            max_tokens=settings.max_llm_reasoning_tokens,
            messages=[{"role": "user", "content": user_prompt}],
            system=system_prompt,
        )
        reasoning = response.content[0].text
    except Exception as e:
        logger.error(f"LLM error for {state['agent_id']}: {e}")
        reasoning = f"API error: {e}. Holding position."

    return {**state, "reasoning": reasoning}


def decide_node(state: AgentState) -> AgentState:
    decision = _parse_decision(state["reasoning"], state["agent_id"], state)
    decision = _validate_decision(decision, state)
    return {**state, "decision": decision}


def execute_node(state: AgentState) -> AgentState:
    from agents.orchestrator import _global_exchange, _global_coordinator

    decision = state.get("decision", {"action": "hold", "params": {}})
    action = decision.get("action", "hold")
    params = decision.get("params", {})

    async def _execute():
        exchange = _global_exchange
        coordinator = _global_coordinator
        tx_hash = None
        error = None
        success = False
        used_somnia_agent = False

        try:
            if coordinator:
                # Contract is self-re-triggering after each handleDecision() callback.
                # Orchestrator fires one initial triggerAgentDecision() per agent on startup.
                # Nothing to do here — carry forward last known tx hash for the dashboard.
                tx_hash = state.get("last_tx_hash")
                success = True
                used_somnia_agent = True

            elif action == "place_order" and exchange:
                # Fallback: Claude decided, execute directly on Exchange
                result = await exchange.place_order(
                    agent_pk=state["private_key"],
                    is_buy=params.get("is_buy", True),
                    price=float(params.get("price", state["current_price"])),
                    amount=float(params.get("amount", 0.1)),
                )
                tx_hash = result.get("tx_hash", "")
                success = bool(tx_hash)

            elif action == "cancel_all_orders" and exchange:
                for oid in state.get("active_order_ids", []):
                    try:
                        result = await exchange.cancel_order(state["private_key"], oid)
                        tx_hash = result.get("tx_hash", tx_hash or "")
                    except Exception as e:
                        logger.warning(f"Cancel order {oid} failed: {e}")
                success = True

            elif action in ("hold", "broadcast_warning"):
                success = True

        except Exception as e:
            error = str(e)
            logger.error(f"Execute error for {state['agent_id']}: {e}")

        return tx_hash, error, success, used_somnia_agent

    try:
        loop = asyncio.get_event_loop()
        tx_hash, error, success, used_somnia_agent = loop.run_until_complete(_execute())
    except RuntimeError:
        tx_hash, error, success, used_somnia_agent = asyncio.run(_execute())

    # Update position tracking
    new_position = state.get("current_position", 0.0)
    new_side = state.get("position_side", "FLAT")
    new_pnl = state.get("pnl_session", 0.0)

    if action == "place_order" and success:
        amount = float(params.get("amount", 0.1))
        is_buy = params.get("is_buy", True)
        if is_buy:
            new_position += amount
        else:
            new_position -= amount
        new_side = "LONG" if new_position > 0.001 else "SHORT" if new_position < -0.001 else "FLAT"
    elif action == "cancel_all_orders" and success:
        price_now = state.get("current_price", state.get("entry_price", 100.0))
        entry = state.get("entry_price", price_now)
        if entry > 0 and new_position != 0:
            new_pnl += new_position * (price_now - entry) / entry
        new_position = 0.0
        new_side = "FLAT"

    entry_price = state.get("entry_price", 0.0)
    if action == "place_order" and success and entry_price == 0.0:
        entry_price = float(params.get("price", state["current_price"]))

    return {
        **state,
        "last_tx_hash": tx_hash or state.get("last_tx_hash"),
        "last_tx_error": error,
        "execution_success": success,
        "last_action": action,
        "used_somnia_agent": used_somnia_agent,
        "current_position": round(new_position, 4),
        "position_side": new_side,
        "pnl_session": round(new_pnl, 6),
        "entry_price": entry_price,
    }


def broadcast_node(state: AgentState) -> AgentState:
    from agents.orchestrator import _global_hub, _global_state_bus

    decision = state.get("decision", {})
    action = decision.get("action", "hold")
    params = decision.get("params", {})
    summary = decision.get("reasoning_summary", "")

    async def _broadcast():
        hub = _global_hub
        bus = _global_state_bus

        # Determine status
        status = "EXECUTING" if state.get("execution_success") and action != "hold" else "IDLE"

        agent_update = {
            "type": "agent_update",
            "data": {
                "agent_id": state["agent_id"],
                "agent_name": state["agent_name"],
                "status": status,
                "balance_eth": round(state.get("onchain_balance", 0.0), 4),
                "position": state.get("current_position", 0.0),
                "position_side": state.get("position_side", "FLAT"),
                "pnl_session": state.get("pnl_session", 0.0),
                "active_orders": len(state.get("active_order_ids", [])),
                "last_action": action,
                "last_tx_hash": state.get("last_tx_hash"),
                "reasoning": state.get("reasoning", ""),
                "reasoning_summary": summary,
                "loop_count": state.get("loop_count", 0),
                "used_somnia_agent": state.get("used_somnia_agent", False),
                "timestamp": time.time(),
            },
        }
        await hub.broadcast(agent_update)

        # Activity feed entry
        feed_item = {
            "type": "activity_feed",
            "data": {
                "id": str(uuid.uuid4()),
                "agent_id": state["agent_id"],
                "agent_name": state["agent_name"],
                "message": summary or f"{action.replace('_', ' ').title()}",
                "category": "trade" if action in ("place_order", "execute_trade") else
                            "warning" if action == "broadcast_warning" else
                            "order" if action == "cancel_all_orders" else "system",
                "timestamp": int(time.time()),
            },
        }
        await hub.broadcast(feed_item)

        # Risk-Shield warning propagation.
        # Somnia-native path: threshold-based (no Claude). Claude path: parse decision.
        if state["agent_id"] == "risk_manager":
            from agents.orchestrator import _global_coordinator
            if _global_coordinator:
                # Rule-based: volatility thresholds drive warnings without LLM
                vol = state.get("volatility_estimate", 0.0)
                if vol > 3.0:
                    severity = "HIGH" if vol > 4.0 else "MEDIUM"
                    warning_msg = f"Volatility {vol:.1f}% — Somnia agent flagging elevated risk"
                    await bus.set_agent_warning("risk_manager", warning_msg)
                    await hub.broadcast({
                        "type": "risk_warning",
                        "data": {
                            "from_agent": "risk_manager",
                            "severity": severity,
                            "warning_type": "vol_spike",
                            "message": warning_msg,
                            "timestamp": time.time(),
                        },
                    })
                elif vol < 2.0:
                    await bus.clear_agent_warning("risk_manager")
            elif action == "broadcast_warning":
                # Claude fallback path
                warning_msg = params.get("message", summary)
                await bus.set_agent_warning("risk_manager", warning_msg)
                await hub.broadcast({
                    "type": "risk_warning",
                    "data": {
                        "from_agent": "risk_manager",
                        "severity": params.get("severity", "MEDIUM"),
                        "warning_type": "vol_spike",
                        "message": warning_msg,
                        "timestamp": time.time(),
                    },
                })
            elif "stable" in summary.lower():
                await bus.clear_agent_warning("risk_manager")

        await asyncio.sleep(settings.agent_loop_interval_seconds)

    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_broadcast())
    except RuntimeError:
        asyncio.run(_broadcast())

    return {
        **state,
        "loop_count": state.get("loop_count", 0) + 1,
    }
