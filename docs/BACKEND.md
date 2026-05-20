# Backend — Agentic Exchange

Python FastAPI server powering four autonomous LangGraph agents that trade on the Somnia blockchain via Claude claude-sonnet-4-6 reasoning.

---

## Directory Map

```
backend/
├── main.py                  # FastAPI app, CORS, lifespan startup/shutdown
├── config.py                # Pydantic Settings — all env vars with defaults
├── requirements.txt         # Python dependencies (pinned)
├── .env                     # Secret keys — NOT committed (see .gitignore)
├── agents/
│   ├── base_agent.py        # BaseAgent class: builds + runs the LangGraph loop
│   └── orchestrator.py      # Creates 4 agents, price loop, snapshot loop, event injection
├── graph/
│   ├── state.py             # AgentState TypedDict — all fields that flow through the graph
│   ├── nodes.py             # 5 node functions + SYSTEM_PROMPTS dict (edit here to tune behavior)
│   └── builder.py           # Compiles the observe→reason→decide→execute→broadcast graph
├── market/
│   ├── price_engine.py      # GBM price simulation + OHLCVBuilder (5s bars)
│   ├── order_book.py        # In-memory bid/ask depth (BookEntry, OrderBook)
│   └── state_bus.py         # Async-safe shared state: price, order book, warnings, events
├── blockchain/
│   ├── client.py            # Web3 singleton, per-wallet nonce Lock, send_transaction()
│   └── contracts.py         # Typed wrappers: ExchangeContract, TreasuryContract
└── api/
    ├── websocket_hub.py     # ConnectionManager: broadcast() to all WS clients
    ├── routes_ws.py         # /ws WebSocket endpoint + message dispatch
    ├── routes_http.py       # GET /health, GET /state, GET /agents, POST /events/inject
    └── schemas.py           # Pydantic request/response models
```

---

## Running Locally

```bash
# 1. Create venv
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env — minimum required: ANTHROPIC_API_KEY

# 4. Start
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 5. Health check
curl http://localhost:8000/health
# → {"status":"ok","agents_running":4,"ws_connections":0}
```

---

## Configuration Reference

All settings live in `config.py` (Pydantic Settings) and are loaded from `backend/.env`.

| Variable                      | Default                            | Required     | Purpose                                          |
| ----------------------------- | ---------------------------------- | ------------ | ------------------------------------------------ |
| `ANTHROPIC_API_KEY`           | —                                  | **Yes**      | Claude API key (agents won't start without this) |
| `ANTHROPIC_MODEL`             | `claude-sonnet-4-6`                | No           | Claude model for agent reasoning                 |
| `SOMNIA_RPC_URL`              | `https://dream-rpc.somnia.network` | No           | Somnia testnet RPC endpoint                      |
| `SOMNIA_CHAIN_ID`             | `50312`                            | No           | Somnia chain ID                                  |
| `SIMULATION_MODE`             | `false`                            | No           | `true` = skip real txs, generate fake hashes     |
| `EXCHANGE_ADDRESS`            | `0x000...000`                      | Onchain only | Deployed Exchange.sol address                    |
| `AGENT_REGISTRY_ADDRESS`      | `0x000...000`                      | Onchain only | Deployed AgentRegistry.sol address               |
| `TREASURY_ADDRESS`            | `0x000...000`                      | Onchain only | Deployed Treasury.sol address                    |
| `MARKET_MAKER_PK`             | `0x000...000`                      | Onchain only | Market Maker agent wallet private key            |
| `MOMENTUM_TRADER_PK`          | `0x000...000`                      | Onchain only | Momentum Trader wallet private key               |
| `ARBITRAGE_AGENT_PK`          | `0x000...000`                      | Onchain only | Arb Scanner wallet private key                   |
| `RISK_MANAGER_PK`             | `0x000...000`                      | Onchain only | Risk Shield wallet private key                   |
| `AGENT_LOOP_INTERVAL_SECONDS` | `8.0`                              | No           | Time between agent decision cycles               |
| `MAX_TOKENS_REASONING`        | `400`                              | No           | Max Claude output tokens per reasoning step      |
| `INITIAL_PRICE`               | `100.0`                            | No           | Starting price for GBM simulation                |
| `PRICE_VOLATILITY`            | `0.025`                            | No           | GBM base volatility (σ)                          |
| `PRICE_DRIFT`                 | `0.0002`                           | No           | GBM drift (μ)                                    |
| `FRONTEND_URL`                | `http://localhost:3000`            | No           | Allowed CORS origin                              |

**Simulation mode activates automatically** when contract addresses are still at the zero-address placeholder. You don't need to set `SIMULATION_MODE=true` explicitly — the guard is in `orchestrator.py:54`.

---

## LangGraph Agent Loop

Each agent runs this compiled state machine in an infinite loop:

```
observe_node → reason_node → decide_node → execute_node → broadcast_node
     ↑_______________________________________________________________↑
                    (conditional edge back to observe)
```

### `observe_node` (`graph/nodes.py`)

**Reads:** `MarketStateBus.get_market_context(agent_id)`, `TreasuryContract.get_balance()`, `ExchangeContract.get_active_orders()`  
**Computes:** `price_trend` (UP/DOWN/FLAT from last 10 bars), `volatility_estimate` (std of last 20 log-returns)  
**Writes to state:** `market_context`, `current_price`, `spread_pct`, `price_trend`, `volatility_estimate`, `agent_warnings`, `injected_events`, `onchain_balance`, `active_order_ids`

### `reason_node` (`graph/nodes.py`)

**Reads:** `state["market_context"]`, `SYSTEM_PROMPTS[agent_id]`  
**Calls:** `anthropic.messages.create(model=..., max_tokens=400, system=..., user=market_context)`  
**Writes to state:** `state["reasoning"]` (raw Claude text output)

### `decide_node` (`graph/nodes.py`)

**Reads:** `state["reasoning"]`  
**Parses:** JSON block extracted from Claude text via 3 regex patterns, keyword fallback if all fail  
**Validates:** order size ≤ 10% of balance, position ≤ `MAX_POSITION_SIZE`, size halved if risk warning active  
**Writes to state:** `state["decision"]` (dict with `action`, `reasoning_summary`, `params`)

Decision actions:

```json
{ "action": "place_order",        "params": { "is_buy": true,  "price": 102.5, "amount": 0.5 } }
{ "action": "cancel_all_orders",  "params": {} }
{ "action": "hold",               "params": {} }
{ "action": "broadcast_warning",  "params": { "message": "..." } }
```

### `execute_node` (`graph/nodes.py`)

**Reads:** `state["decision"]`, `_global_exchange`, `_global_treasury`  
**Does:**

- `place_order` → `ExchangeContract.place_order(agent_pk, is_buy, price, amount)` → writes `last_tx_hash`
- `cancel_all_orders` → loops over `active_order_ids`, calls `cancel_order()` for each
- `hold` / `broadcast_warning` → no-op on blockchain
- Any tx error → logged, `execution_success=False`, agent never crashes  
  **Writes to state:** `last_tx_hash`, `execution_success`, `current_position`, `position_side`, `entry_price`, `pnl_session`

### `broadcast_node` (`graph/nodes.py`)

**Does:**

1. Sends `agent_update` WS message to all dashboard clients
2. Sends `activity_feed` WS message with human-readable action summary
3. If agent is Risk Manager and action is `broadcast_warning` → calls `state_bus.set_agent_warning()` (other agents read this on their next `observe`)
4. `await asyncio.sleep(AGENT_LOOP_INTERVAL_SECONDS)` — this is the pacing mechanism
5. Sets `should_continue=True` → graph loops back to `observe`

---

## Market Simulation

### Price Engine (`market/price_engine.py`)

Geometric Brownian Motion updated every 1 second:

```
S(t+1) = S(t) × exp((μ − σ²/2)Δt + σ√Δt × Z)
Z ~ N(0, 1)
```

Key methods:

- `next_price()` — advances one tick (called by `orchestrator._price_loop()`)
- `apply_price_shock(pct)` — instant price jump (whale buy/sell, flash crash)
- `set_volatility_multiplier(multiplier, duration_seconds)` — temporary vol increase, auto-expires
- `get_recent_closes(n)` — returns last N bar closes for trend/vol computation

`OHLCVBuilder` accumulates 1-second ticks into 5-second OHLCV bars.

### Order Book (`market/order_book.py`)

In-memory bid/ask book (`dict[order_id, BookEntry]`). `synthesize_order_book(mid_price)` in `MarketStateBus` regenerates 10 synthetic levels on each side every second to simulate realistic depth.

### MarketStateBus (`market/state_bus.py`)

The shared state layer — all agents read from here, Risk Manager writes warnings here.

| Method                                 | Description                                                                  |
| -------------------------------------- | ---------------------------------------------------------------------------- |
| `get_snapshot()`                       | Price, bid/ask, spread, volume, order book (top 10), recent trades (last 50) |
| `get_market_context(agent_id)`         | LLM-ready formatted string for Claude's user prompt                          |
| `inject_event(event_type, params)`     | Records a market event (visible to agents next loop)                         |
| `set_agent_warning(agent_id, warning)` | Risk Manager writes here; all agents observe it                              |
| `clear_agent_warning(agent_id)`        | Removes warning when Risk Manager determines conditions are stable           |
| `get_active_warnings()`                | Returns list of current warnings (included in market_context)                |

All methods protected by `asyncio.Lock` for safe concurrent access from 4 agent tasks.

---

## Blockchain Integration

### `blockchain/client.py`

- **Single Web3 instance** shared across all agents (cached, thread-safe)
- **POA middleware** (`ExtraDataToPOAMiddleware`) applied for Somnia's PoA consensus
- **Hardcoded gas price: 6 gwei** — dynamic `eth_gasPrice` RPC calls cause failures on Somnia testnet
- **Per-wallet `asyncio.Lock`**: 4 agents each own a wallet; the lock prevents nonce reuse when agents transact concurrently
- **30s receipt timeout**: if confirmation doesn't arrive, logs a warning and the agent continues (never blocks)
- **Simulation mode**: generates `"0x" + secrets.token_hex(32)` instead of submitting real txs

### `blockchain/contracts.py`

ABI loading strategy: tries `contracts/deployments/somnia-testnet.json` first (deployed ABIs), falls back to minimal inline ABIs. This means the backend works before deployment with reduced functionality.

---

## WebSocket Message Reference

### Backend → Frontend

| `type`            | Frequency           | Fields                                                                                                                                                                                           |
| ----------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `market_snapshot` | every 2s            | `price`, `bid`, `ask`, `spread_pct`, `volume_24h`, `order_book` (top 10), `recent_trades` (last 50)                                                                                              |
| `candle`          | every 5s            | `time`, `open`, `high`, `low`, `close`, `volume`                                                                                                                                                 |
| `agent_update`    | every ~8s per agent | `agent_id`, `name`, `status` (THINKING/EXECUTING/IDLE), `balance_eth`, `position`, `position_side`, `pnl_session`, `reasoning`, `reasoning_summary`, `last_tx_hash`, `last_action`, `loop_count` |
| `risk_warning`    | on Risk Mgr trigger | `severity` (LOW/MEDIUM/HIGH), `warning_type`, `message`                                                                                                                                          |
| `event_injected`  | on button click     | `event_type`, `description`, `price_before`, `price_after`, `timestamp`                                                                                                                          |
| `activity_feed`   | real-time           | `id`, `agent_name`, `message`, `category` (order/trade/warning/event/system)                                                                                                                     |

### Frontend → Backend

```json
{ "type": "inject_event", "data": { "event_type": "whale_buy" } }
{ "type": "ping" }
```

### HTTP Endpoints

| Method | Path             | Description                                   |
| ------ | ---------------- | --------------------------------------------- |
| `GET`  | `/health`        | `{ status, agents_running, ws_connections }`  |
| `GET`  | `/state`         | Full market snapshot                          |
| `GET`  | `/agents`        | Array of 4 agent state summaries              |
| `POST` | `/events/inject` | Body: `{ "event_type": "...", "params": {} }` |

---

## Tuning Agent Behavior

### Change a strategy prompt

Edit `SYSTEM_PROMPTS` in `graph/nodes.py`. Each agent has a dedicated entry keyed by `agent_id`. The system prompt defines personality, risk tolerance, and decision format expectations.

### Change loop speed

Set `AGENT_LOOP_INTERVAL_SECONDS` in `backend/.env`. Default is `8.0`. Faster loops hit Claude API harder — minimum practical value is ~3.0 with staggered agents.

### Add a new agent

1. Add entry to `AGENT_CONFIGS` in `agents/orchestrator.py`
2. Add strategy system prompt to `SYSTEM_PROMPTS` in `graph/nodes.py`
3. Add `new_agent_pk` field to `config.py`
4. Add wallet PK to `backend/.env`
5. Register + fund in `contracts/scripts/seed.js`

### Change initial price or volatility

Set `INITIAL_PRICE` and `PRICE_VOLATILITY` in `backend/.env`. Volatility (`σ`) of `0.025` produces ~2.5% price swings per tick under normal conditions.

---

## Key Design Decisions

| Decision                                  | Reason                                                                                        |
| ----------------------------------------- | --------------------------------------------------------------------------------------------- |
| All 4 agents use `BaseAgent` + same graph | Strategy differentiation via system prompt only — simpler to reason about and modify          |
| `asyncio.Lock` per wallet                 | Concurrent agents would cause nonce conflicts and dropped txs                                 |
| GBM price, not a real feed                | Demo needs controllable events (whale buy, crash) — a real feed can't be scripted             |
| Simulation mode                           | Somnia testnet reliability is unpredictable; demo must work without blockchain access         |
| Agents stagger 2s at startup              | Spreads the burst of Anthropic API calls during initialization                                |
| Hardcoded 6 gwei gas                      | `eth_gasPrice` RPC returns unreliable values on Somnia testnet; hardcoding avoids tx failures |
| 30s receipt timeout (not infinite)        | A stuck tx should never block the agent loop — log and continue                               |
