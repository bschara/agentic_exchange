import asyncio
import logging
from eth_account import Account

from graph.builder import build_agent_graph
from graph.state import AgentState

logger = logging.getLogger(__name__)


class BaseAgent:
    def __init__(self, agent_id: str, agent_name: str, strategy: str, private_key: str):
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.strategy = strategy
        self.private_key = private_key
        self.wallet_address = Account.from_key(private_key).address
        self._graph = build_agent_graph()
        self._running = False
        self._state: AgentState = self._build_initial_state()

    def _build_initial_state(self) -> AgentState:
        return AgentState(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            strategy=self.strategy,
            wallet_address=self.wallet_address,
            private_key=self.private_key,
            market_context="",
            current_price=100.0,
            spread_pct=0.0,
            price_trend="FLAT",
            volatility_estimate=0.0,
            agent_warnings=[],
            injected_events=[],
            current_position=0.0,
            position_side="FLAT",
            onchain_balance=1.0,
            active_order_ids=[],
            pnl_session=0.0,
            entry_price=0.0,
            reasoning="",
            decision={},
            last_tx_hash=None,
            last_tx_error=None,
            execution_success=False,
            last_action="hold",
            loop_count=0,
            should_continue=True,
        )

    async def run(self):
        self._running = True
        logger.info(f"Agent {self.agent_name} starting ({self.wallet_address})")
        try:
            await self._graph.ainvoke(
                self._state,
                config={"recursion_limit": 100_000},
            )
        except Exception as e:
            logger.error(f"Agent {self.agent_name} crashed: {e}", exc_info=True)

    def stop(self):
        self._running = False
        self._state["should_continue"] = False

    def get_state_summary(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "status": "IDLE",
            "balance_eth": self._state.get("onchain_balance", 0.0),
            "position": self._state.get("current_position", 0.0),
            "position_side": self._state.get("position_side", "FLAT"),
            "pnl_session": self._state.get("pnl_session", 0.0),
            "active_orders": len(self._state.get("active_order_ids", [])),
            "last_action": self._state.get("last_action", "hold"),
            "last_tx_hash": self._state.get("last_tx_hash"),
            "reasoning": self._state.get("reasoning", ""),
            "reasoning_summary": self._state.get("decision", {}).get("reasoning_summary", ""),
            "loop_count": self._state.get("loop_count", 0),
        }
