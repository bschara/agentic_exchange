# Architecture — Agentic Exchange

Real-time autonomous trading demo on Somnia (chain 50312). Four Claude-powered agents trade in continuous 8-second loops, recording every decision permanently onchain. A WebSocket-connected dashboard makes the system observable in real-time.

---

## Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                   Somnia Blockchain (50312)                  │
│       Exchange.sol · AgentRegistry.sol · Treasury.sol        │
└──────────────────────────┬──────────────────────────────────┘
                           │ web3 txs (6 gwei hardcoded, per-wallet Lock)
┌──────────────────────────▼──────────────────────────────────┐
│                      FastAPI Backend                         │
│  ┌──────────────┐   ┌──────────────────────────────────┐   │
│  │ PriceEngine  │   │       4 × LangGraph Agent         │   │
│  │   (GBM)      ├──►│  observe→reason→decide→execute    │   │
│  └──────┬───────┘   │         →broadcast (8s loop)      │   │
│         │           └──────────────┬─────────────────── ┘   │
│  ┌──────▼────────────────────────┐ │                        │
│  │        MarketStateBus         │◄┘  (warnings, events)   │
│  │  price · order book · history │                          │
│  │  agent warnings · events      ├──► WS broadcast (2s)    │
│  └───────────────────────────────┘                          │
└──────────────────────────┬──────────────────────────────────┘
                           │ WebSocket  ws://localhost:8000/ws
┌──────────────────────────▼──────────────────────────────────┐
│                    Next.js Dashboard                         │
│  CandlestickChart · OrderBook · AgentCards · ActivityFeed   │
│  Zustand: marketStore · agentStore · feedStore              │
└─────────────────────────────────────────────────────────────┘
```

---

## LangGraph Agent State Machine

All 4 agents run the same compiled graph — differentiated only by the strategy system prompt stored in `backend/graph/nodes.py:SYSTEM_PROMPTS`.

```
observe_node → reason_node → decide_node → execute_node → broadcast_node
     ↑_______________________________________________________________↑
                    (conditional edge: should_continue → observe)
```

### Node Descriptions

**`observe_node`** (`backend/graph/nodes.py`)

- Reads a snapshot from `MarketStateBus`: current price, bid/ask, spread, order book depth
- Computes `price_trend` (UP / DOWN / FLAT) from the last 10 price bars
- Computes `volatility_estimate` from the last 20 log-returns
- Reads any active warnings posted by Risk Manager via `state_bus.get_active_warnings()`
- Reads active onchain order IDs from `ExchangeContract.get_active_orders()` (skipped in simulation mode)
- Builds `market_context`: a structured string passed to Claude as the user prompt

**`reason_node`** (`backend/graph/nodes.py`)

- Calls `anthropic.messages.create(model="claude-sonnet-4-6", max_tokens=400)`
- System prompt: strategy-specific personality (market maker, momentum, arb, risk)
- User prompt: the `market_context` string from observe
- Raw text response stored in `state["reasoning"]`
- Claude is instructed to always end its response with a JSON decision block

**`decide_node`** (`backend/graph/nodes.py`)

- Extracts JSON from reasoning with regex (`{...}` pattern)
- Falls back to rule-based logic if parse fails; final fallback is `action: "hold"`
- Validates: order size ≤ 10% of current balance, position within `MAX_POSITION_SIZE`
- If an active Risk Manager warning is present → reduces all order sizes by 50%

Decision JSON format:

```json
{
  "action": "place_order | cancel_all_orders | hold",
  "reasoning_summary": "one-sentence human-readable explanation",
  "params": {
    "is_buy": true,
    "price": 102.5,
    "amount": 0.5
  }
}
```

**`execute_node`** (`backend/graph/nodes.py`)

- Switches on `decision["action"]`:
  - `place_order` → `ExchangeContract.place_order(is_buy, price, amount)`
  - `cancel_all_orders` → iterates active order IDs, calls `cancelOrder()` for each
  - `hold` → no-op
- All tx errors are caught and logged; `execution_success=False` is set but the agent never crashes
- In simulation mode (`_global_exchange is None`): generates a fake 0x-prefixed tx hash

**`broadcast_node`** (`backend/graph/nodes.py`)

- Sends `agent_update` WebSocket message to all connected dashboard clients
- Sends `activity_feed` entry with agent name + action summary
- If agent is Risk Manager and decision includes a warning → calls `state_bus.set_agent_warning()`
- Sleeps for `AGENT_LOOP_INTERVAL_SECONDS` (default 8.0s) before returning control to the graph
- Sets `should_continue=True` (agent runs forever until shutdown)

---

## MarketStateBus (`backend/market/state_bus.py`)

The shared in-memory state layer. Protected by `asyncio.Lock` for safe concurrent access from 4 agent tasks.

Key methods:

- `get_snapshot()` → price, bid/ask, spread, volume, order book, recent trades
- `get_market_context()` → formatted string ready for Claude's user prompt
- `synthesize_order_book(price)` → generates synthetic bid/ask depth around mid price
- `inject_event(event_type, params)` → records event for agents to observe next loop
- `set_agent_warning(agent_id, warning)` → Risk Manager writes here; others read via `get_active_warnings()`
- `clear_agent_warning(agent_id)` → clears after warning is no longer triggered

---

## Price Engine (`backend/market/price_engine.py`)

Simulates a realistic price series using **Geometric Brownian Motion (GBM)**:

```
S(t+1) = S(t) × exp((μ - σ²/2)Δt + σ√Δt × Z)
where Z ~ N(0,1)
```

- `next_price()` → advances one tick (called every 1 second)
- `apply_price_shock(pct)` → instantaneous price jump (used for whale/crash events)
- `set_volatility_multiplier(multiplier, duration_seconds)` → temporary vol increase (auto-expires)
- `OHLCVBuilder` → accumulates 1-second ticks into 5-second OHLCV bars

---

## Blockchain Layer (`backend/blockchain/`)

### `client.py` — Web3 singleton

- One `Web3` instance shared across all agents
- Per-wallet `asyncio.Lock`: each agent wallet has its own lock, preventing nonce conflicts when multiple agents submit transactions concurrently
- Hardcoded `GAS_PRICE = 6_000_000_000` (6 gwei) — dynamic estimation (`eth_gasPrice`) causes failures on Somnia testnet
- `send_transaction(private_key, to, data, value)`: builds tx, signs, broadcasts, waits up to 30s for receipt
- Simulation mode: skips all of the above, returns `"0x" + 64 random hex chars`

### `contracts.py` — typed wrappers

- `ExchangeContract`: `place_order()`, `cancel_order()`, `execute_trade()`, `get_active_orders()`
- `AgentRegistry`: `register()`, `update_reputation()`
- `TreasuryContract`: `get_balance()`, `deposit()`, `withdraw()`

All methods are `async` and call through `client.send_transaction()`.

---

## Smart Contracts (`contracts/contracts/`)

### `Exchange.sol`

Records orders and trades onchain. No real token movement — purely an onchain audit trail.

```
placeOrder(bool isBuy, uint256 price, uint256 amount) → orderId
cancelOrder(uint256 orderId)
executeTrade(uint256 buyOrderId, uint256 sellOrderId) → tradeId
getActiveOrders() → uint256[]

Events:
  OrderPlaced(orderId, agent, isBuy, price, amount)
  OrderCancelled(orderId, agent)
  TradeExecuted(tradeId, buyOrderId, sellOrderId, buyer, seller, price, amount)
```

`executeTrade` validates `buyOrder.price >= sellOrder.price`, marks both inactive, emits `TradeExecuted`.

### `AgentRegistry.sol`

On-chain agent registry. Each agent wallet is registered with a name, strategy string, and reputation score.

```
register(address agent, string name, string strategy)  // owner-only
updateReputation(address agent, int256 delta)           // owner-only
getAllAgents() → address[]
```

### `Treasury.sol`

Tracks per-agent STT balances. `allocate()` is owner-only, used by the system for simulated P&L tracking.

```
deposit() payable
depositFor(address agent) payable
withdraw(uint256 amount)
getBalance(address agent) → uint256
allocate(address from, address to, uint256 amount)  // owner-only
```

---

## WebSocket Message Protocol

### Backend → Frontend

| `type`            | Frequency             | Key fields                                                                                                                                 |
| ----------------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `market_snapshot` | every 2s              | `price`, `bid`, `ask`, `spread_pct`, `volume_24h`, `order_book` (top 10 levels), `recent_trades` (last 50)                                 |
| `candle`          | every 5s (bar close)  | `time`, `open`, `high`, `low`, `close`, `volume`                                                                                           |
| `agent_update`    | per agent loop (~8s)  | `agent_id`, `status` (THINKING/EXECUTING/IDLE), `balance_eth`, `position`, `pnl_session`, `reasoning`, `reasoning_summary`, `last_tx_hash` |
| `risk_warning`    | on Risk Mgr trigger   | `severity`, `warning_type`, `message`                                                                                                      |
| `event_injected`  | on event button click | `event_type`, `price_before`, `price_after`                                                                                                |
| `activity_feed`   | real-time             | `id`, `agent_name`, `message`, `category`                                                                                                  |

### Frontend → Backend

```json
{ "type": "inject_event", "data": { "event_type": "whale_buy" } }
```

Event types: `whale_buy`, `whale_sell`, `volatility_spike`, `news_event`, `flash_crash`

### HTTP Endpoints

| Method | Path             | Response                            |
| ------ | ---------------- | ----------------------------------- |
| `GET`  | `/health`        | `{ status, agents_running, block }` |
| `GET`  | `/state`         | Full market snapshot                |
| `GET`  | `/agents`        | Array of 4 agent state summaries    |
| `POST` | `/events/inject` | `{ event_type }` → triggers event   |

---

## Frontend State (`frontend/store/`)

### `marketStore`

- `candles`: ring buffer (max 200) of OHLCV bars
- `orderBook`: `{ bids: Level[], asks: Level[] }` (top 10 each)
- `recentTrades`: last 50 trades
- `currentPrice`, `isConnected`

### `agentStore`

- `agents: Record<agent_id, AgentState>` — latest state for each of 4 agents
- `reasoningHistory: Record<agent_id, string[]>` — last 20 reasoning texts per agent

### `feedStore`

- `items: ActivityFeedItem[]` — ring buffer (max 100, newest first)

---

## Agent Coordination — Risk Manager Flow

```
Risk-Shield (risk_manager agent)
  ↓ observe: sees high position exposure in state
  ↓ reason: Claude decides to broadcast reduce warning
  ↓ execute: (no onchain tx — internal warning)
  ↓ broadcast: calls state_bus.set_agent_warning("risk_manager", {...})
               sends risk_warning WS message to dashboard

MM-Prime / Momentum-Alpha / Arb-Scanner (next loop, ~8s later)
  ↓ observe: state_bus.get_active_warnings() → includes risk_manager warning
  ↓ reason: Claude receives "RISK MANAGER WARNING: reduce position sizes" in context
  ↓ decide: order sizes multiplied by 0.5 regardless of Claude output
  ↓ execute: smaller orders placed
```

The warning persists in `MarketStateBus` until Risk-Shield clears it (exposure drops below threshold).

---

## Key Design Decisions

| Decision                                   | Reason                                                                                                    |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| **Hardcoded 6 gwei gas price**             | Dynamic `eth_gasPrice` RPC call returns unreliable values on Somnia testnet and causes tx failures        |
| **Per-wallet `asyncio.Lock`**              | Four agents running concurrently would cause nonce conflicts without exclusive access per wallet          |
| **GBM price engine, not real feed**        | Hackathon demo needs predictable behavior and controllable events (whale buy, crash) for judges           |
| **All 4 agents use `BaseAgent`**           | Strategy differentiation via system prompts, not separate code paths — simpler to reason about and modify |
| **Simulation mode**                        | Testnet reliability is unpredictable; demo must work even if Somnia is down. One env var switches modes.  |
| **Ring buffers in frontend (max 200/100)** | Prevents memory growth during extended demo sessions                                                      |
| **`series.update()` only for chart**       | Calling `setData()` repeatedly on TradingView v5 causes visible flicker and memory leaks                  |
| **Agents staggered 2s apart on startup**   | Spreads Anthropic API calls to avoid hitting rate limits during initialization burst                      |
