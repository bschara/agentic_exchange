from typing import TypedDict, Optional


class AgentState(TypedDict):
    # Identity
    agent_id: str
    agent_name: str
    strategy: str
    wallet_address: str
    private_key: str

    # Market snapshot
    market_context: str
    current_price: float
    spread_pct: float
    price_trend: str
    volatility_estimate: float
    agent_warnings: list[str]
    injected_events: list[dict]

    # Agent's own state
    current_position: float
    position_side: str
    onchain_balance: float
    active_order_ids: list[int]
    pnl_session: float
    entry_price: float

    # LLM reasoning
    reasoning: str
    decision: dict

    # Execution result
    last_tx_hash: Optional[str]
    last_tx_error: Optional[str]
    execution_success: bool
    last_action: str
    used_somnia_agent: bool  # True when decision routed through Somnia's LLM consensus

    # Graph control
    loop_count: int
    should_continue: bool
