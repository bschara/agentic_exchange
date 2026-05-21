# Backend — Agentic Exchange

Python FastAPI server that kicks off four autonomous on-chain agents on Somnia and observes their activity. All trading decisions are validated by Somnia's LLM inference agent (multi-validator consensus) — no off-chain AI involved.

---

## Directory Map

```
backend/
├── main.py                  # FastAPI app, CORS, lifespan startup/shutdown
├── config.py                # Pydantic Settings — all env vars with defaults
├── requirements.txt         # Python dependencies (pinned)
├── .env                     # Secret keys — NOT committed (see .gitignore)
├── agents/
│   └── orchestrator.py      # Agent wallet registry, poll loops, metrics loop, startup triggers
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
    ├── routes_http.py       # GET /health, GET /state, GET /agents, GET /chain-metrics, POST /events/inject
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
# Edit .env — fill contract addresses and agent wallet private keys

# 4. Start
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 5. Health check
curl http://localhost:8000/health
# → {"status":"ok","agents_running":0,"ws_connections":0}
```

---

## Configuration Reference

All settings live in `config.py` (Pydantic Settings) and are loaded from `backend/.env`.

| Variable                    | Default                            | Required     | Purpose                                                                               |
| --------------------------- | ---------------------------------- | ------------ | ------------------------------------------------------------------------------------- |
| `SOMNIA_RPC_URL`            | `https://dream-rpc.somnia.network` | No           | Somnia testnet RPC endpoint                                                           |
| `SOMNIA_CHAIN_ID`           | `50312`                            | No           | Somnia chain ID                                                                       |
| `EXCHANGE_ADDRESS`          | `0x000...000`                      | **Yes**      | Deployed Exchange.sol address                                                         |
| `AGENT_REGISTRY_ADDRESS`    | `0x000...000`                      | **Yes**      | Deployed AgentRegistry.sol address                                                    |
| `TREASURY_ADDRESS`          | `0x000...000`                      | **Yes**      | Deployed Treasury.sol address                                                         |
| `AGENT_COORDINATOR_ADDRESS` | `0x000...000`                      | **Yes**      | Deployed AgentCoordinator.sol address; triggers self-sustaining on-chain agent loops  |
| `MARKET_MAKER_PK`           | `0x000...000`                      | **Yes**      | Market Maker agent wallet private key                                                 |
| `MOMENTUM_TRADER_PK`        | `0x000...000`                      | **Yes**      | Momentum Trader wallet private key                                                    |
| `ARBITRAGE_AGENT_PK`        | `0x000...000`                      | **Yes**      | Arb Scanner wallet private key                                                        |
| `RISK_MANAGER_PK`           | `0x000...000`                      | **Yes**      | Risk Shield wallet private key                                                        |
| `INITIAL_PRICE`             | `100.0`                            | No           | Starting price for GBM chart (until real trades come in)                              |
| `PRICE_VOLATILITY`          | `0.025`                            | No           | GBM base volatility (σ)                                                               |
| `PRICE_DRIFT`               | `0.0002`                           | No           | GBM drift (μ)                                                                         |
| `FRONTEND_URL`              | `http://localhost:3000`            | No           | Allowed CORS origin                                                                   |

**Contracts activate automatically** when addresses in `.env` are valid 20-byte hex strings (not placeholders). On startup the orchestrator fires one `triggerAgentDecision()` per agent; after that the contract self-re-triggers and Python never touches the contracts again.

---

## Orchestrator Background Loops

`AgentOrchestrator.start_all()` always starts these three loops:

| Loop | Interval | Purpose |
|------|----------|---------|
| `_trade_event_poll_loop` | 1s | Reads `TradeExecuted` events, updates `PriceEngine` and `MarketStateBus`, broadcasts `candle` WS messages |
| `_snapshot_broadcast_loop` | 2s | Reads `MarketStateBus.get_snapshot()`, broadcasts `market_snapshot` WS message |
| `_contract_metrics_poll_loop` | 5s | Reads coordinator events + contract state, broadcasts `chain_metrics` WS message |

When `_coordinator` is set, it additionally fires one `triggerAgentDecision()` per agent at startup (staggered 1s apart). After that, the on-chain loop is self-sustaining.

### Contract Metrics Poll

`_contract_metrics_poll_loop` runs every 5s and accumulates the following into `self._chain_metrics`:

```python
{
  "coordinator_balance": float,   # STT remaining in AgentCoordinator
  "total_locked": float,          # total STT in Treasury
  "spread_pct": float,            # live (ask - bid) / bid × 100
  "buy_depth": int,               # active buy order count in Exchange
  "sell_depth": int,              # active sell order count in Exchange
  "loop_stopped_any": bool,       # true if any agent emitted LoopStopped
  "agents": {
    "<agent_id>": {
      "decisions_total": int,     # DecisionExecuted + DecisionFailed events
      "buy_count": int,           # DecisionExecuted where decision == "BUY"
      "sell_count": int,          # DecisionExecuted where decision == "SELL"
      "hold_count": int,          # DecisionExecuted where decision == "HOLD"
      "failures": int,            # DecisionFailed events
      "orders_placed": int,       # OrderPlaced events from this agent's wallet
      "treasury_balance": float,  # Treasury.getBalance(wallet)
      "last_decision": str,       # "BUY" | "SELL" | "HOLD" | null
      "last_price": float,        # price from last DecisionExecuted
      "last_fetched_price": float,# raw ETH/USD from last LLMRequestFired
      "loop_stopped": bool,       # true if LoopStopped emitted for this agent
      "loop_stopped_reason": str  # reason string from LoopStopped event
    }
  }
}
```

`from_block` is advanced after each poll to avoid double-counting events. This data is also available at `GET /chain-metrics`.

---

## Market Layer

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
| `inject_event(event_type, params)`     | Records a market event (updates GBM display)                                 |
| `set_agent_warning(agent_id, warning)` | Writes a warning visible in MarketStateBus                                   |
| `clear_agent_warning(agent_id)`        | Removes an active warning                                                    |
| `get_active_warnings()`                | Returns list of current active warnings                                      |

All methods protected by `asyncio.Lock` for safe concurrent access from 4 agent tasks.

---

## Blockchain Integration

### `blockchain/client.py`

- **Single Web3 instance** shared across all agents (cached, thread-safe)
- **POA middleware** (`ExtraDataToPOAMiddleware`) applied for Somnia's PoA consensus
- **Hardcoded gas price: 6 gwei** — dynamic `eth_gasPrice` RPC calls cause failures on Somnia testnet
- **Per-wallet `asyncio.Lock`**: 4 agents each own a wallet; the lock prevents nonce reuse when agents transact concurrently
- **30s receipt timeout**: if confirmation doesn't arrive, logs a warning and the agent continues (never blocks)

### `blockchain/contracts.py`

ABI loading strategy: tries `contracts/deployments/somnia-testnet.json` first (deployed ABIs), falls back to minimal inline ABIs. This means the backend works before deployment with reduced functionality.

**`AgentCoordinatorContract`** — wraps `AgentCoordinator.sol`:
- `trigger_decision(agent_pk, agent_id)` → ABI-encodes `triggerAgentDecision(agentId)`, submits signed tx from the agent's wallet. Called once per agent at startup by `orchestrator.start_all()`. After this the contract self-loops.
- `get_balance()` → reads the coordinator's STT balance (must stay funded; each cycle costs 2 deposits)
- `get_coordinator_events(from_block)` → polls `DecisionExecuted`, `DecisionFailed`, `LoopStopped`, `LLMRequestFired` events in one pass, returns them sorted by block number

**`ExchangeContract`** methods:
- `get_best_bid()` / `get_best_ask()` → on-chain spread from active order book
- `get_last_trade_price()` → price of most recent matched fill (0 if no fills yet)
- `has_traded()` → bool — whether any match has ever occurred
- `get_recent_trade_events(from_block)` → reads `TradeExecuted` event logs for OHLCV construction
- `get_order_book_depth()` → `{ buy_count, sell_count }` from `getActiveBuys()`/`getActiveSells()`
- `get_order_placed_events(from_block)` → reads `OrderPlaced` events; includes `agent` address for wallet-to-ID mapping

**`TreasuryContract`** methods:
- `get_balance(agent_address)` → per-agent STT balance
- `get_total_locked()` → total STT held by the treasury contract (`totalLocked()`)

---

## WebSocket Message Reference

### Backend → Frontend

| `type`            | Frequency       | Fields                                                                                                                                                                                                                                                      |
| ----------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `market_snapshot` | every 2s        | `price`, `bid`, `ask`, `spread_pct`, `volume_24h`, `order_book` (top 10), `recent_trades` (last 50)                                                                                                                                                         |
| `candle`          | every 5s        | `time`, `open`, `high`, `low`, `close`, `volume`                                                                                                                                                                                                            |
| `chain_metrics`   | every 5s        | `coordinator_balance`, `total_locked`, `spread_pct`, `buy_depth`, `sell_depth`, `loop_stopped_any`; `agents` map with per-agent `decisions_total`, `buy_count`, `sell_count`, `failures`, `treasury_balance`, `last_decision`, `last_price`, `loop_stopped` |
| `risk_warning`    | on state change | `severity` (LOW/MEDIUM/HIGH), `warning_type`, `message`                                                                                                                                                                                                     |
| `event_injected`  | on button click | `event_type`, `description`, `price_before`, `price_after`, `timestamp`                                                                                                                                                                                     |

### Frontend → Backend

```json
{ "type": "inject_event", "data": { "event_type": "whale_buy" } }
{ "type": "ping" }
```

### HTTP Endpoints

| Method | Path             | Description                                   |
| ------ | ---------------- | --------------------------------------------- |
| `GET`  | `/health`        | `{ status, agents_running, ws_connections }`  |
| `GET`  | `/state`         | Full market snapshot from `MarketStateBus`    |
| `GET`  | `/agents`        | Array of 4 agent state summaries from `chain_metrics` |
| `GET`  | `/chain-metrics` | Latest `chain_metrics` snapshot (live coordinator/exchange/treasury state) |
| `POST` | `/events/inject` | Body: `{ "event_type": "...", "params": {} }` |

---

## Tuning Agent Behavior

### Change a strategy prompt

Edit the `setSystemPrompt` calls in `contracts/scripts/deploy.js` and redeploy. System prompts are stored on-chain in `AgentCoordinator` and passed to the Somnia LLM inference agent on each decision cycle.

### Add a new agent

1. Add entry to `AGENT_CONFIGS` in `agents/orchestrator.py`
2. Add `new_agent_pk` field to `config.py`
3. Add wallet PK to `backend/.env`
4. Add `setSystemPrompt` call in `contracts/scripts/deploy.js`
5. Register + fund in `contracts/scripts/seed.js`
6. Add `triggerAgentDecision()` call in deploy or startup (orchestrator fires it automatically for all `AGENT_CONFIGS` entries)

### Change initial price or volatility

Set `INITIAL_PRICE` and `PRICE_VOLATILITY` in `backend/.env`. Volatility (`σ`) of `0.025` produces ~2.5% price swings per tick under normal conditions. These only affect the GBM chart display — actual trade prices come from on-chain fills.

---

## Key Design Decisions

| Decision                              | Reason                                                                                                                                                                              |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Contract metrics poll, not agent push | Backend observes the on-chain loop via event polling rather than driving it. Decouples dashboard from the trading cycle and never blocks the contract's self-trigger cadence.       |
| `from_block` advances in metrics loop | After each poll the loop stores `max_block_seen + 1` so events are counted exactly once across poll cycles.                                                                         |
| `_is_address()` guard on init         | Validates addresses against `r"0x[0-9a-fA-F]{40}"` before instantiating contracts — gracefully handles unconfigured `.env` without raising at startup.                             |
| `asyncio.Lock` per wallet             | Concurrent startup triggers (1s stagger) could cause nonce conflicts; per-wallet lock prevents dropped txs.                                                                         |
| GBM price, not a real feed            | Demo needs controllable events (whale buy, crash) — a real feed can't be scripted. Replaced by on-chain prices once fills start arriving.                                           |
| Hardcoded 6 gwei gas                  | `eth_gasPrice` RPC returns unreliable values on Somnia testnet; hardcoding avoids tx failures.                                                                                      |
| 30s receipt timeout (not infinite)    | A stuck startup trigger should never block the orchestrator — log and continue.                                                                                                     |
| Agents stagger 1s at startup          | Spreads the burst of `triggerAgentDecision()` transactions to avoid nonce collisions during the initial on-chain kickoff.                                                           |
