# Architecture — Agentic Exchange

Real-time autonomous trading demo on Somnia (chain 50312). Four agents trade in continuous 8-second loops, with decisions validated by Somnia's on-chain LLM consensus layer when deployed. Every order lands on a real on-chain limit order book with automatic matching. A WebSocket-connected dashboard makes the system observable in real-time.

---

## Component Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Somnia Blockchain (chain 50312)                    │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Exchange.sol  (real on-chain LOB)                           │    │
│  │  placeOrder() → _matchOrder() → TradeExecuted(price,amount) │    │
│  │  getBestBid() · getBestAsk() · getLastTradePrice()          │    │
│  └─────────────────────┬──────────────────────┬───────────────┘    │
│                         │ placeOrder (direct)   │ placeOrder        │
│                         │                       │ (from callback)   │
│  ┌──────────────────────┴──┐  ┌────────────────┴──────────────┐    │
│  │ AgentRegistry · Treasury│  │  AgentCoordinator.sol          │    │
│  └─────────────────────────┘  │  requestDecision()             │    │
│                                │    → IAgentRequester           │    │
│                                │  handleResponse() callback      │    │
│                                │    → Exchange.placeOrder()      │    │
│                                └────────────────┬──────────────┘    │
│  ┌─────────────────────────────────────         │                   │
│  │  Somnia LLM Inference Agent        ──────────┘ (platform fires) │
│  │  inferString(ctx, systemPrompt,                                   │
│  │    ["BUY","SELL","HOLD"])                                         │
│  │  → multi-validator consensus                                      │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
         ↑ web3 txs (6 gwei hardcoded, per-wallet Lock)
┌────────┴─────────────────────────────────────────────────────────────┐
│                         FastAPI Backend                               │
│  ┌─────────────────┐   ┌──────────────────────────────────────────┐ │
│  │ PriceEngine     │   │       4 × LangGraph Agent                 │ │
│  │ (GBM, anchored  ├──►│  observe→reason→decide→execute→broadcast  │ │
│  │  to chain fills)│   │  (8s loop)                                │ │
│  └────────┬────────┘   └───────────────────┬──────────────────────┘ │
│    _chain_price_sync_loop (5s)              │                        │
│  ┌────────▼───────────────────────────────┐│                        │
│  │        MarketStateBus                  ││ (warnings, events)     │
│  │  price · order book · history          │◄┘                       │
│  │  agent warnings · events               ├──► WS broadcast (2s)   │
│  └────────────────────────────────────────┘                          │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ WebSocket  ws://localhost:8000/ws
┌──────────────────────────────▼───────────────────────────────────────┐
│                    Next.js Dashboard                                  │
│  CandlestickChart · OrderBook · AgentCards · ActivityFeed            │
│  Each card: ⬡ ON-CHAIN LLM badge (violet when Somnia active)        │
│  Zustand: marketStore · agentStore · feedStore                       │
└──────────────────────────────────────────────────────────────────────┘
```

---

## LangGraph Agent State Machine

All 4 agents run the same compiled graph — differentiated by strategy-specific system prompts stored on-chain in `AgentCoordinator.systemPrompts` (onchain mode) or in `backend/graph/nodes.py:SYSTEM_PROMPTS` (simulation mode).

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

**Onchain mode** (when `_global_coordinator` is set):

- Returns immediately with a placeholder: `"⬡ Somnia on-chain LLM agent active — decision delegated to validator consensus"`
- The actual BUY/SELL/HOLD decision is made by Somnia's validator network in `execute_node` (via `handleResponse()` callback)

**Simulation mode** (no coordinator):

- Calls `anthropic.messages.create(model="claude-sonnet-4-6", max_tokens=400)`
- System prompt: strategy-specific personality from `SYSTEM_PROMPTS[agent_id]`
- User prompt: the `market_context` string from observe
- Raw text response stored in `state["reasoning"]`
- Claude is instructed to end its response with a JSON decision block

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

**Onchain mode** (when `_global_coordinator` is set):

- No-op: the contract is self-re-triggering. On startup, `orchestrator.start_all()` fires one `triggerAgentDecision()` per agent; after that, `handleDecision()` calls `_retrigger()` at the end of every cycle — the loop runs forever without any further Python interaction.
- Carries forward `last_tx_hash` for dashboard display and sets `used_somnia_agent=True` → lights up the dashboard badge.

**Simulation mode** (no coordinator):

- Switches on `decision["action"]`:
  - `place_order` → `ExchangeContract.place_order(is_buy, price, amount)`
  - `cancel_all_orders` → iterates active order IDs, calls `cancelOrder()` for each
  - `hold` / `broadcast_warning` → no-op
- All tx errors caught; `execution_success=False` set but agent never crashes
- When exchange is `None`: generates a fake 0x-prefixed tx hash

**`broadcast_node`** (`backend/graph/nodes.py`)

- Sends `agent_update` WebSocket message to all connected dashboard clients
- Sends `activity_feed` entry with agent name + action summary
- **Risk Manager warnings** (onchain mode): threshold-based rule — volatility > 3% → `state_bus.set_agent_warning()` + broadcast `risk_warning` WS message; volatility < 2% → `state_bus.clear_agent_warning()`. No LLM involvement.
- **Risk Manager warnings** (simulation mode): if Claude's decision was `broadcast_warning` → `state_bus.set_agent_warning()` with the message from decision params
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
- `set_chain_price(chain_price)` → anchors GBM to a real on-chain fill price; updates `self.price` and ticks the OHLCV builder
- `OHLCVBuilder` → accumulates 1-second ticks into 5-second OHLCV bars

### `_chain_price_sync_loop` (`backend/agents/orchestrator.py`)

Runs every 5 seconds when coordinator is live:

1. Calls `ExchangeContract.get_last_trade_price()` — the price of the last matched fill
2. If `> 0` (at least one on-chain trade has occurred): calls `price_engine.set_chain_price(price)` to anchor the GBM to real price discovery
3. Reads `get_best_bid()` / `get_best_ask()` from the contract to re-center the synthetic order book display

This keeps the dashboard chart coherent with actual on-chain trading activity.

---

## Blockchain Layer (`backend/blockchain/`)

### `client.py` — Web3 singleton

- One `Web3` instance shared across all agents
- Per-wallet `asyncio.Lock`: each agent wallet has its own lock, preventing nonce conflicts when multiple agents submit transactions concurrently
- Hardcoded `GAS_PRICE = 6_000_000_000` (6 gwei) — dynamic estimation (`eth_gasPrice`) causes failures on Somnia testnet
- `send_transaction(private_key, to, data, value)`: builds tx, signs, broadcasts, waits up to 30s for receipt
- Simulation mode: skips all of the above, returns `"0x" + 64 random hex chars`

### `contracts.py` — typed wrappers

- `ExchangeContract`: `place_order()`, `cancel_order()`, `get_active_orders()`, `get_best_bid()`, `get_best_ask()`, `get_last_trade_price()`, `has_traded()`, `get_recent_trade_events()`
- `AgentCoordinatorContract`: `request_decision(agent_pk, agent_id, market_context, market_price)` → submits tx to Somnia, returns `{tx_hash, agent_id, market_price}`; `get_balance()` → coordinator STT balance
- `AgentRegistry`: `register()`, `update_reputation()`
- `TreasuryContract`: `get_balance()`, `deposit()`, `withdraw()`

All methods are `async` and call through `client.send_transaction()`.

---

## Smart Contracts (`contracts/contracts/`)

### `Exchange.sol`

Real on-chain limit order book with automatic matching. Every `placeOrder()` call triggers the matching engine — no separate `executeTrade` step.

```
placeOrder(bool isBuy, uint256 price, uint256 amount) → orderId
  → internally calls _matchOrder() which scans the opposite side for price crossings
  → matching fills are recorded via _recordTrade(), emitting TradeExecuted
  → unmatched remainder stays as an open resting order

cancelOrder(uint256 orderId)
getBestBid() → (price, exists)
getBestAsk() → (price, exists)
getLastTradePrice() → uint256
getActiveOrders() → uint256[]
getActiveBuys() → uint256[]
getActiveSells() → uint256[]

Events:
  OrderPlaced(orderId, agent, isBuy, price, amount)
  OrderCancelled(orderId, agent)
  OrderFilled(orderId, filledAmount, fullFill)
  TradeExecuted(tradeId, buyOrderId, sellOrderId, buyer, seller, price, amount)
```

`_matchOrder()` does an O(n) scan of the opposite book. For buy orders: matches sells where `sell.price <= buy.price`. For sell orders: matches buys where `buy.price >= sell.price`. Maker price is used as the fill price. Partial fills are supported.

### `AgentCoordinator.sol`

Routes all 4 agents through Somnia's on-chain LLM inference agent. Self-re-triggers after every decision cycle — no Python involvement after the initial startup kick.

**Two-step pipeline per cycle:**

```
triggerAgentDecision(string agentId)       ← called once by Python on startup
  → reads agentConfigs[agentId] → { priceUrl, selector, decimals }
  → require(balance >= deposit × 2)
  → platform.createRequest(jsonApiAgentId, handlePriceData.selector, fetchUint payload)
  → emit DecisionTriggered(requestId, agentId)

handlePriceData(requestId, responses, ...)  ← Somnia JSON API agent callback
  → decodes fetchedPrice from responses[0].result
  → _buildContext(fetchedPrice, agentId) — reads Exchange on-chain state
  → platform.createRequest(llmAgentId, handleDecision.selector, inferString payload)
  → emit LLMRequestFired(llmRequestId, agentId, fetchedPrice)

handleDecision(requestId, responses, ...)   ← Somnia LLM validator consensus callback
  → decodes "BUY" / "SELL" / "HOLD"
  → reads Exchange.getLastTradePrice() as base, applies ±0.1% offset
  → Exchange.placeOrder() on-chain
  → emit DecisionExecuted(requestId, agentId, decision, price, orderId)
  → _retrigger(agentId)  ← fires the NEXT cycle immediately

_retrigger(agentId) internal
  → checks address(this).balance >= deposit × 2
  → if funded: fires the next JSON API fetch → loop continues
  → if underfunded: emit LoopStopped(agentId, "Insufficient balance", balance)
  → if no config:   emit LoopStopped(agentId, "No agent config", balance)

setAgentConfig(agentId, url, selector, decimals)  // owner-only
setSystemPrompt(string agentId, string prompt)    // owner-only
setLlmAgentId(uint256 agentId)                    // owner-only
setJsonApiAgentId(uint256 agentId)                // owner-only
fund() payable
withdraw()
```

Events:
```
DecisionTriggered(requestId, agentId)
LLMRequestFired(llmRequestId, agentId, fetchedPrice)
DecisionExecuted(requestId, agentId, decision, price, orderId)
DecisionFailed(requestId, agentId, reason)
PriceFetchFailed(requestId, agentId)
LoopStopped(agentId, reason, balance)   ← emitted when self-re-trigger cannot proceed
```

Platform address (testnet): `0x037Bb9C718F3f7fe5eCBDB0b600D607b52706776`  
Default `llmAgentId`: `2` (override via `SOMNIA_LLM_AGENT_ID` env var at deploy time)

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

## End-to-End Autonomous Agent Flow

Complete flow from startup kick to self-perpetuating on-chain loop — three sequential transactions per cycle, all on Somnia chain 50312. Python fires Tx 1 **once per agent at startup**; after that the contract loops itself indefinitely.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Python Backend (FastAPI)                                                     │
│                                                                               │
│  orchestrator.start_all() — once, at startup                                 │
│    coordinator.trigger_decision(agent_pk, agent_id)  ← per agent, 1s apart  │
│    ↓ signs + broadcasts tx (6 gwei)                                          │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │ Tx 1: triggerAgentDecision(agentId)
                                       │ (fired ONCE per agent at startup)
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  AgentCoordinator.sol  (on Somnia chain 50312)                                │
│                                                                               │
│  triggerAgentDecision(agentId)                                               │
│    · reads agentConfigs[agentId] → { priceUrl, selector, decimals }          │
│    · require(balance >= deposit × 2)                                         │
│    · payload = fetchUint(priceUrl, selector, decimals)                       │
│    · platform.createRequest{value: deposit}(                                 │
│        jsonApiAgentId,                                                       │
│        address(this),                                                        │
│        handlePriceData.selector,                                             │
│        payload                                                               │
│      )  → stores pendingPriceRequests[requestId]                             │
│    · emit DecisionTriggered(requestId, agentId)                              │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │ request queued on Somnia platform
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  Somnia JSON API Agent  (base agent, id = jsonApiAgentId)                    │
│                                                                               │
│  fetchUint(                                                                  │
│    "https://api.coingecko.com/...?ids=ethereum&vs_currencies=usd",           │
│    "ethereum.usd",                                                           │
│    0    ← whole-dollar price, e.g. returns 3245 for $3245                   │
│  )                                                                           │
│  → makes HTTP request to CoinGecko                                          │
│  → extracts integer field                                                    │
│  → ABI-encodes result as uint256                                             │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │ Tx 2: handlePriceData(requestId, [3245], Success, ...)
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  AgentCoordinator.handlePriceData()  (callback, msg.sender == platform)      │
│                                                                               │
│  · fetchedPrice = abi.decode(responses[0].result, (uint256))  → 3245        │
│  · _buildContext(3245, agentId):                                             │
│      reads Exchange.getLastTradePrice() → lastFillUsd                       │
│      reads Exchange.getBestBid()        → bidUsd                            │
│      reads Exchange.getBestAsk()        → askUsd                            │
│      returns "ETH/USD: $3245. On-chain last trade: $3244.                   │
│               Best bid: $3243. Best ask: $3245. Decide: BUY, SELL, or HOLD."│
│  · llmPayload = inferString(context, systemPrompts[agentId], false,         │
│                              ["BUY","SELL","HOLD"])                          │
│  · platform.createRequest{value: deposit}(                                  │
│        llmAgentId,                                                          │
│        address(this),                                                       │
│        handleDecision.selector,                                             │
│        llmPayload                                                           │
│      )  → stores pendingLLMRequests[llmRequestId]                           │
│  · emit LLMRequestFired(llmRequestId, agentId, 3245)                        │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │ request queued on Somnia platform
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  Somnia LLM Inference Agent  (base agent, id = llmAgentId)                  │
│                                                                               │
│  inferString(                                                                │
│    prompt  = "ETH/USD: $3245. On-chain last trade: $3244. ...",             │
│    system  = systemPrompts[agentId],   ← strategy prompt stored on-chain    │
│    cot     = false,                                                          │
│    allowed = ["BUY","SELL","HOLD"]     ← constrains output to 3 values      │
│  )                                                                           │
│  → multi-validator consensus across Somnia's decentralized network          │
│  → majority vote → "BUY" / "SELL" / "HOLD"                                 │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │ Tx 3: handleDecision(requestId, ["BUY"], Success, ...)
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  AgentCoordinator.handleDecision()   (callback, msg.sender == platform)      │
│                                                                               │
│  · decision = abi.decode(responses[0].result, (string))  → "BUY"           │
│  · basePrice = exchange.hasTraded()                                         │
│                  ? exchange.getLastTradePrice()   ← real on-chain fill      │
│                  : fetchedPrice × 1e18            ← CoinGecko fallback      │
│  · orderPrice = basePrice × (10000 + 10) / 10000  ← +0.1% for buy         │
│  · exchange.placeOrder(true, orderPrice, 0.1e18)                            │
│      → _matchOrder() scans sell book for crossing price                     │
│      → if match: TradeExecuted(price, amount) emitted, lastTradePrice set   │
│      → if no match: resting buy order added to book                         │
│  · emit DecisionExecuted(requestId, agentId, "BUY", orderPrice, orderId)    │
│  · _retrigger(agentId)                                                       │
│      → balance >= deposit × 2?                                               │
│          YES → next cycle fires immediately (Tx 1 again on-chain)           │
│               emit DecisionTriggered(newReqId, agentId)                     │
│          NO  → emit LoopStopped(agentId, "Insufficient balance", balance)   │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Three transactions per cycle. Zero off-chain computation in the decision loop.** Python fires Tx 1 once per agent at startup. Txs 2 and 3 are fired entirely by Somnia's infrastructure. After Tx 3, `_retrigger()` fires the next cycle on-chain — the loop runs forever until the coordinator's STT balance is exhausted, at which point `LoopStopped(agentId, reason, balance)` is emitted.

---

## Somnia Agent Protocol

How the self-perpetuating on-chain loop works. Python fires the first trigger once per agent; after that the contract drives itself.

```
Python backend (once at startup per agent)
  │
  └─ coordinator.trigger_decision(agent_pk, agent_id)
       │ signs + sends tx: AgentCoordinator.triggerAgentDecision(agentId)
       │
       ▼
AgentCoordinator.triggerAgentDecision(agentId)
  · reads agentConfigs[agentId] → { priceUrl, selector, decimals }
  · require(balance >= deposit × 2)
  · platform.createRequest{value: deposit}(jsonApiAgentId, handlePriceData.selector,
      fetchUint(priceUrl, selector, decimals))
  · emit DecisionTriggered(requestId, agentId)
       │
       ▼  (Somnia JSON API agent fetches price off-chain)
AgentCoordinator.handlePriceData(requestId, responses, ...)  ← platform callback
  · fetchedPrice = abi.decode(responses[0].result, (uint256))
  · _buildContext(fetchedPrice, agentId) — reads Exchange.sol on-chain
  · platform.createRequest{value: deposit}(llmAgentId, handleDecision.selector,
      inferString(context, systemPrompts[agentId], false, ["BUY","SELL","HOLD"]))
  · emit LLMRequestFired(llmRequestId, agentId, fetchedPrice)
       │
       ▼  (Somnia LLM Inference Agent — multi-validator consensus)
AgentCoordinator.handleDecision(requestId, responses, ...)   ← platform callback
  · decision = abi.decode(responses[0].result, (string))  → "BUY" / "SELL" / "HOLD"
  · BUY:  price = lastTradePrice × 1.001  → Exchange.placeOrder(true, price, 0.1e18)
  · SELL: price = lastTradePrice × 0.999  → Exchange.placeOrder(false, price, 0.1e18)
  · HOLD: no order placed
  · emit DecisionExecuted(requestId, agentId, decision, price, orderId)
  · _retrigger(agentId)
       │
       ▼  (self-re-trigger — no Python needed)
  balance >= deposit × 2?
    YES → platform.createRequest(jsonApiAgentId, ...) → back to handlePriceData
          emit DecisionTriggered(newReqId, agentId)
    NO  → emit LoopStopped(agentId, "Insufficient balance", balance)
```

**`allowedValues`**: constraining LLM output to `["BUY","SELL","HOLD"]` ensures the callback can deterministically parse the response without JSON extraction or fallback logic.

**Deposit**: each cycle consumes 2 deposits — one for the JSON API fetch and one for the LLM inference. `deploy.js` pre-funds the coordinator with 0.05 STT. Top up via `fund()`. When balance drops below `deposit × 2`, `LoopStopped` is emitted and the agent halts gracefully.

**Per-agent system prompts**: stored in `AgentCoordinator.systemPrompts` mapping. Each agent's strategy personality (market maker, momentum trader, arbitrage, risk management) is embedded in the on-chain prompt — the same prompt differentiation that Claude uses in simulation mode.

---

## WebSocket Message Protocol

### Backend → Frontend

| `type`            | Frequency             | Key fields                                                                                                                                                      |
| ----------------- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `market_snapshot` | every 2s              | `price`, `bid`, `ask`, `spread_pct`, `volume_24h`, `order_book` (top 10 levels), `recent_trades` (last 50)                                                      |
| `candle`          | every 5s (bar close)  | `time`, `open`, `high`, `low`, `close`, `volume`                                                                                                                |
| `agent_update`    | per agent loop (~8s)  | `agent_id`, `status` (THINKING/EXECUTING/IDLE), `balance_eth`, `position`, `pnl_session`, `reasoning`, `reasoning_summary`, `last_tx_hash`, `used_somnia_agent` |
| `risk_warning`    | on Risk Mgr trigger   | `severity`, `warning_type`, `message`                                                                                                                           |
| `event_injected`  | on event button click | `event_type`, `price_before`, `price_after`                                                                                                                     |
| `activity_feed`   | real-time             | `id`, `agent_name`, `message`, `category`                                                                                                                       |

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

**Onchain mode** (coordinator live):

```
Risk-Shield (risk_manager agent)
  ↓ execute: calls AgentCoordinator.requestDecision() like all agents
  ↓ broadcast: volatility_estimate > 3%?
      YES → state_bus.set_agent_warning("risk_manager", "Volatility X% — Somnia agent flagging elevated risk")
             broadcast risk_warning WS message (severity: HIGH if vol > 4%, else MEDIUM)
      NO (vol < 2%) → state_bus.clear_agent_warning("risk_manager")

MM-Prime / Momentum-Alpha / Arb-Scanner (next loop, ~8s later)
  ↓ observe: state_bus.get_active_warnings() → includes risk_manager warning
  ↓ execute: AgentCoordinator.requestDecision() — Somnia LLM receives warning in market context
  ↓ decide: order sizes multiplied by 0.5 (hard rule, regardless of LLM output)
```

**Simulation mode** (Claude):

```
Risk-Shield
  ↓ reason: Claude outputs action: "broadcast_warning" with message params
  ↓ broadcast: state_bus.set_agent_warning("risk_manager", message)

Other agents: same warning propagation via MarketStateBus
```

The warning persists until Risk-Shield's `broadcast_node` clears it (volatility drops below threshold).

---

## Key Design Decisions

| Decision                                   | Reason                                                                                                    |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| **Self-re-triggering contract**            | `handleDecision()` calls `_retrigger()` to fire the next cycle — agents run forever with zero Python involvement after startup. Emits `LoopStopped` on low balance for graceful halt. |
| **One startup kick per agent**             | Python's only blockchain interaction in onchain mode. The orchestrator fires `triggerAgentDecision()` once per agent with 1s stagger, then never touches the contracts again. |
| **Hardcoded 6 gwei gas price**             | Dynamic `eth_gasPrice` RPC call returns unreliable values on Somnia testnet and causes tx failures        |
| **Per-wallet `asyncio.Lock`**              | Four agents running concurrently would cause nonce conflicts without exclusive access per wallet          |
| **GBM price engine, not real feed**        | Hackathon demo needs predictable behavior and controllable events (whale buy, crash) for judges           |
| **All 4 agents use `BaseAgent`**           | Strategy differentiation via system prompts, not separate code paths — simpler to reason about and modify |
| **Simulation mode**                        | Testnet reliability is unpredictable; demo must work even if Somnia is down. One env var switches modes.  |
| **Ring buffers in frontend (max 200/100)** | Prevents memory growth during extended demo sessions                                                      |
| **`series.update()` only for chart**       | Calling `setData()` repeatedly on TradingView v5 causes visible flicker and memory leaks                  |
| **Agents staggered 2s apart on startup**   | Spreads Anthropic API calls to avoid hitting rate limits during initialization burst                      |
