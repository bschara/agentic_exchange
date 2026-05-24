# Architecture — Agentic Exchange

Real-time autonomous trading demo on Somnia (chain 50312). Five agents trade autonomously on-chain — four via Somnia's LLM consensus layer, one (noise_trader) as a pure Python random-order loop. Every order lands on a real on-chain limit order book with automatic matching. A WebSocket-connected dashboard makes the system observable in real-time, anchored by a full-width latency comparison panel (Somnia vs Solana vs Ethereum).

Agents coordinate on-chain without any Python mediation: each agent's LLM prompt includes the previous cycle's decisions from all peers; consecutive wins scale order size automatically; three-agent consensus triggers a coalition order. Every prompt is emitted as the `context` field of `LLMRequestFired` — verifiable on the Somnia explorer.

---

## Component Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Somnia Blockchain (chain 50312)                    │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Exchange.sol  (real on-chain LOB)                           │    │
│  │  placeOrder() → _matchOrder() → TradeExecuted(price,amount) │    │
│  │  cancelOrder() · getOrdersByAgent() · getBestBid/Ask()      │    │
│  └─────────────────────┬──────────────────────┬───────────────┘    │
│                         │ placeOrder (callback)  │ events polled     │
│  ┌──────────────────────┴──┐  ┌────────────────┴──────────────┐    │
│  │ AgentRegistry · Treasury│  │  AgentCoordinator.sol          │    │
│  └─────────────────────────┘  │  triggerAgentDecision() ×1     │    │
│                                │  cancel lastOrderId → placeOrder│   │
│                                │  MM: dual bid+ask per cycle    │    │
│                                │  lastDecision → peer signals   │    │
│                                │  winStreak → _orderAmount()    │    │
│                                │  _coalitionCount==3 → 3× order │    │
│                                │  _retrigger() → self-loop      │    │
│                                └────────────────┬──────────────┘    │
│  ┌─────────────────────────────────────         │ platform fires    │
│  │  Somnia LLM Inference Agent        ──────────┘                  │
│  │  inferString(ctx+peers+streak, systemPrompt, ["BUY","SELL","HOLD"])│
│  │  → multi-validator consensus                                      │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
     ↑ 1 startup tx per agent (6 gwei)  ↑ noise_trader direct orders
┌────────┴─────────────────────────────────────────────────────────────┐
│                         FastAPI Backend                               │
│  ┌─────────────────┐  trade event poll (1s) ──► PriceEngine         │
│  │ MarketStateBus  │  snapshot broadcast (2s) ──────────────────►WS │
│  │ price · book    │  contract metrics poll (5s) ──► chain_metrics  │
│  │ warnings·events │    extracts context+streak from events         │
│  │                 │    coalition_alert broadcast on CoalitionFormed│
│  └─────────────────┘  noise_trader_loop (4-6s) → Exchange.placeOrder│
└──────────────────────────────┬───────────────────────────────────────┘
                               │ WebSocket  ws://localhost:8000/ws
┌──────────────────────────────▼───────────────────────────────────────┐
│                    Next.js Dashboard                                  │
│  LatencyHero (full-width: Somnia vs Solana vs Ethereum latency)      │
│  CandlestickChart · OrderBook · AgentCards (5) · ActivityFeed        │
│  Agent cards: strategy desc, 🔥 streak badge, position badge, P&L   │
│  ReasoningPanel: live LLM prompt per agent (peers + streak visible)  │
│  ActivityFeed: coalition alerts (orange) + tx hash links             │
│  Scoreboard: ranked by total P&L (realized + unrealized)             │
│  Zustand: marketStore · agentStore · feedStore                       │
└──────────────────────────────────────────────────────────────────────┘
```

---

## MarketStateBus (`backend/market/state_bus.py`)

The shared in-memory state layer. Protected by `asyncio.Lock` for safe concurrent access from multiple concurrent loops (4 on-chain agent polls + noise_trader loop + broadcast loops).

Key methods:

- `get_snapshot()` → price, bid/ask, spread, volume, order book (rebuilt from on-chain data), recent trades
- `record_fill(price, volume, buyer_id, seller_id)` → anchors GBM to real on-chain fill, advances OHLCV builder
- `set_order_book(bids, asks)` → rebuilds in-memory book from on-chain order data (called every 5s by metrics loop)
- `inject_event(event_type, params)` → records a market event
- `set_agent_warning(agent_id, warning)` / `clear_agent_warning(agent_id)` → warning state storage

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

### Background loops (`backend/agents/orchestrator.py`)

Three loops run unconditionally.

**`_trade_event_poll_loop`** (1s interval)

Polls `Exchange.TradeExecuted` events. Each fill calls `state_bus.record_fill(price, volume)` to anchor the GBM price to real on-chain data and advances the OHLCV builder. Broadcasts `candle` WS messages when a 5s bar closes and updates the in-progress bar every poll.

**`_snapshot_broadcast_loop`** (2s interval)

Reads `MarketStateBus.get_snapshot()` and broadcasts a `market_snapshot` WS message to keep the dashboard fresh between fills.

**`_contract_metrics_poll_loop`** (5s interval)

Reads on-chain contract state and emits a `chain_metrics` WS message. Also available at `GET /chain-metrics`. Tracks:

| Source                           | Data collected                                                                                                                                                                                                  |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `AgentCoordinator` events        | Per-agent: `decisions_total`, `buy_count`, `sell_count`, `hold_count`, `failures`, `last_decision`, `last_price`, `last_fetched_price`, `last_context` (full LLM prompt), `win_streak`, `loop_stopped` + reason |
| `CoalitionFormed` events         | `coalition_alert` top-level field; also broadcast immediately as `{ type: "coalition_alert" }` WS message; inserted into `recent_fills` with `category: "coalition"`                                            |
| `AgentCoordinator.getBalance()`  | Coordinator STT fuel remaining                                                                                                                                                                                  |
| `Exchange.getActiveBuys/Sells()` | Live order book depth (buy count, sell count)                                                                                                                                                                   |
| `Exchange.getBestBid/Ask()`      | Live spread %                                                                                                                                                                                                   |
| `Exchange.OrderPlaced` events    | Per-agent orders placed count (matched to wallet addresses)                                                                                                                                                     |
| `Treasury.getBalance(addr)`      | Per-agent treasury STT balance                                                                                                                                                                                  |
| `Treasury.totalLocked()`         | Total STT held by treasury contract                                                                                                                                                                             |

The loop advances `from_block` after each poll so events are never double-counted.

**Risk warning emission:** After updating the order book, `_collect_chain_metrics` checks:

- `spread_pct > 2.0` → broadcasts `risk_warning` of type `HIGH_SPREAD`
- log-return stddev of recent closes > 2% → broadcasts `risk_warning` of type `VOLATILITY_SPIKE`

These are immediate WebSocket broadcasts (not stored in `chain_metrics`).

---

## Blockchain Layer (`backend/blockchain/`)

### `client.py` — Web3 singleton

- One `Web3` instance shared across all agents
- Per-wallet `asyncio.Lock`: each agent wallet has its own lock, preventing nonce conflicts when multiple agents submit transactions concurrently
- Hardcoded `GAS_PRICE = 6_000_000_000` (6 gwei) — dynamic estimation (`eth_gasPrice`) causes failures on Somnia testnet
- `send_transaction(private_key, to, data, value)`: builds tx, signs, broadcasts, waits up to 30s for receipt

### `contracts.py` — typed wrappers

- `ExchangeContract`: `get_best_bid()`, `get_best_ask()`, `get_last_trade_price()`, `has_traded()`, `get_recent_trade_events()`, `get_order_book_depth()`, `get_order_placed_events()`
- `AgentCoordinatorContract`: `trigger_decision(agent_pk, agent_id)` → startup kick; `get_balance()` → coordinator STT balance; `get_coordinator_events(from_block)` → polls all 4 event types in one pass
- `TreasuryContract`: `get_balance(addr)`, `get_total_locked()`

All methods are `async` and call through `client.send_transaction()`.

---

## Smart Contracts (`contracts/contracts/`)

### `AgentToken.sol`

Minimal owner-mintable ERC20 (symbol `AGT`). No OpenZeppelin dependency. `deploy.js` mints 10M AGT to the coordinator (shared pool for all 4 on-chain agents) and grants Exchange a max allowance via `coordinator.approveToken()`. `seed.js` mints 1M AGT to each individual agent wallet and approves Exchange — required for noise_trader which calls Exchange directly.

### `Exchange.sol`

Real on-chain limit order book with automatic matching and AGT token settlement. Every `placeOrder()` call triggers the matching engine — no separate `executeTrade` step. SELL orders lock AGT in Exchange escrow on placement; fills settle AGT to the buyer; cancellations refund remaining AGT to the seller. P&L is therefore provable on-chain via token balance changes.

```
placeOrder(bool isBuy, uint256 price, uint256 amount) → orderId
  → for SELL orders: token.transferFrom(msg.sender, Exchange, amount) — locks AGT
  → internally calls _matchOrder() which scans the opposite side for price crossings
  → matching fills are recorded via _recordTrade(), which calls token.transfer(buyer, fill)
  → unmatched remainder stays as an open resting order (tokens remain locked in Exchange)

cancelOrder(uint256 orderId)
  → for SELL orders: token.transfer(order.agent, remaining) — refunds unfilled AGT
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

Routes all 4 agents through Somnia's on-chain LLM inference agent. Self-re-triggers after every decision cycle — no Python involvement after the initial startup kick. Three features enable on-chain multi-agent coordination without any off-chain mediation.

**Three-step pipeline per cycle:**

```
triggerAgentDecision(string agentId)       ← called once by Python on startup
  → reads agentConfigs[agentId] → { priceUrl, selector, decimals }
  → require(balance >= deposit × 2)
  → platform.createRequest(jsonApiAgentId, handlePriceData.selector, fetchUint payload)
  → pendingPriceRequests[reqId] = PriceRequest(agentId, true)
  → emit DecisionTriggered(requestId, agentId)

handlePriceData(requestId, responses, ...)  ← Somnia JSON API agent callback
  → fetchedPrice = abi.decode(responses[0].result, (uint256))
  → context = _buildContext(fetchedPrice, agentId):
      reads Exchange.getLastTradePrice(), getBestBid(), getBestAsk()
      appends _buildPeerSignals(agentId)  →  "Peers: agent2=BUY,agent3=SELL"
      appends streak info if winStreak[agentId] > 0
  → platform.createRequest(llmAgentId, handleDecision.selector, inferString(context,...))
  → emit LLMRequestFired(llmRequestId, agentId, fetchedPrice, context)
  ↑ full prompt is on-chain in the event — verifiable on Somnia explorer

handleDecision(requestId, responses, ...)   ← Somnia LLM validator consensus callback
  → cancel lastOrderId[agentId] if set
  → market_maker: places bid(−0.1%) + ask(+0.1%), emit 2× DecisionExecuted(streak=0), return
  → directional agents:
      decision = abi.decode(responses[0].result, (string))  → "BUY"/"SELL"/"HOLD"
      lastDecision[agentId] = decision   ← peers read this next cycle
      if BUY or SELL: _coalitionCount(decision) == 3? → _fireCoalitionOrder()
      if HOLD: winStreak[agentId] = 0, emit DecisionExecuted(price=0, orderId=0, streak=0)
      else: Exchange.placeOrder(isBuy, price, _orderAmount(agentId))
              → success: winStreak[agentId]++; emit DecisionExecuted(..., streak)
              → revert:  winStreak[agentId] = 0; emit DecisionFailed
  → _retrigger(agentId)

_retrigger(agentId) internal
  → checks address(this).balance >= deposit × 2
  → if funded: fires the next JSON API fetch → loop continues
  → if underfunded: emit LoopStopped(agentId, "Insufficient balance", balance)
  → if no config:   emit LoopStopped(agentId, "No agent config", balance)

_orderAmount(agentId) internal view → ORDER_AMOUNT_BASE × (1 + winStreak/5), cap ORDER_AMOUNT_MAX
_coalitionCount(direction) internal view → count of _agentIdList entries with lastDecision == direction
_fireCoalitionOrder(isBuy, basePrice) → Exchange.placeOrder(isBuy, price, ORDER_AMOUNT_BASE×3)
                                         emit CoalitionFormed(direction, 3, price, orderId)
```

Events:

```
DecisionTriggered(requestId, agentId)
LLMRequestFired(llmRequestId, agentId, fetchedPrice, context)  ← NEW: full prompt on-chain
DecisionExecuted(requestId, agentId, decision, price, orderId, streak)  ← NEW: streak field
CoalitionFormed(direction, agentCount, price, orderId)  ← NEW: 3-agent consensus event
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

## Test Suite (`contracts/test/`)

All contract tests run with Hardhat + Chai and use the `loadFixture` pattern from `@nomicfoundation/hardhat-network-helpers` for deterministic state resets between tests.

```bash
cd contracts && npx hardhat test
```

| File                          | Coverage                                                                                                                                                                      |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Exchange.test.cjs`           | Order placement (BUY/SELL), AGT lock on SELL, matching engine (full and partial fills), `TradeExecuted` event fields, order cancellation with AGT refund, order book queries  |
| `AgentCoordinator.test.cjs`   | Full 3-transaction pipeline (triggerAgentDecision → handlePriceData → handleDecision), coalition detection at 3-agent consensus, win streak counter, peer signal assembly, `LoopStopped` on low balance |
| `AgentRegistry.test.cjs`      | Agent registration (name + strategy), owner-only `updateReputation`, reputation increment/decrement, `getAllAgents` return                                                     |
| `Treasury.test.cjs`           | `deposit()`, `depositFor(address)`, `withdraw()`, `getBalance()`, owner-only `allocate()`, revert on over-withdrawal                                                          |

Each test file deploys a fresh fixture via `loadFixture` so tests are isolated from each other and from deployment state. `AgentCoordinator.test.cjs` deploys the full stack — `AgentToken`, `Exchange`, `MockPlatform`, and `AgentCoordinator` — and drives the callback loop using `MockPlatform.simulatePriceCallback` / `simulateLLMCallback`, the same mechanism the `platform-daemon.js` uses in local dev.

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
│      _buildPeerSignals(agentId) → "arbitrage_agent=BUY,risk_manager=HOLD"  │
│      winStreak[agentId] = 3 → "3-win streak. "                             │
│      returns "ETH/USD: $3245. Last trade: $3244. Bid: $3243. Ask: $3245.   │
│               Peers: arbitrage_agent=BUY,risk_manager=HOLD.                 │
│               3-win streak. Decide: BUY, SELL, or HOLD."                   │
│  · llmPayload = inferString(context, systemPrompts[agentId], false,         │
│                              ["BUY","SELL","HOLD"])                          │
│  · platform.createRequest{value: deposit}(                                  │
│        llmAgentId,                                                          │
│        address(this),                                                       │
│        handleDecision.selector,                                             │
│        llmPayload                                                           │
│      )  → stores pendingLLMRequests[llmRequestId]                           │
│  · emit LLMRequestFired(llmRequestId, agentId, 3245, context)               │
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
│  · cancel lastOrderId[agentId] if set (exchange.cancelOrder)                │
│  · decision = abi.decode(responses[0].result, (string))  → "BUY"           │
│  · lastDecision[agentId] = "BUY"    ← stored for peers next cycle           │
│  · _coalitionCount("BUY") → 3?  → _fireCoalitionOrder(true, basePrice)     │
│      exchange.placeOrder(true, price, ORDER_AMOUNT_BASE×3)                  │
│      emit CoalitionFormed("BUY", 3, price, coalitionOrderId)                │
│  · basePrice = fetchedPrice × 1e18  (decimals=0 → ×1e18)                   │
│  · orderPrice = basePrice × (10000 + 10) / 10000  ← +0.1% for buy         │
│  · exchange.placeOrder(true, orderPrice, _orderAmount(agentId))             │
│      _orderAmount = ORDER_AMOUNT_BASE × (1 + winStreak/5)  → 0.001e18      │
│      → _matchOrder() scans sell book for crossing price                     │
│      → if match: TradeExecuted(price, amount) emitted, lastTradePrice set   │
│      → if no match: resting buy order added to book                         │
│  · winStreak[agentId]++   → 4                                               │
│  · emit DecisionExecuted(requestId, agentId, "BUY", orderPrice, orderId, 4) │
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
  · cancel lastOrderId[agentId] if set
  · decision = abi.decode(responses[0].result, (string))  → "BUY" / "SELL" / "HOLD"
  · lastDecision[agentId] = decision    ← peers read this next cycle
  · _coalitionCount(decision) == 3?  → _fireCoalitionOrder(), emit CoalitionFormed
  · BUY:  price = basePrice × 1.001  → Exchange.placeOrder(true,  price, _orderAmount(agentId))
  · SELL: price = basePrice × 0.999  → Exchange.placeOrder(false, price, _orderAmount(agentId))
  · HOLD: winStreak[agentId] = 0; no order placed
  · on fill: winStreak[agentId]++; emit DecisionExecuted(..., streak)
  · on fail: winStreak[agentId] = 0; emit DecisionFailed
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

**Per-agent system prompts**: stored in `AgentCoordinator.systemPrompts` mapping. Each agent's strategy personality (market maker, momentum trader, arbitrage, risk management) is embedded in the on-chain prompt and set by `deploy.js` at deployment time.

---

## WebSocket Message Protocol

### Backend → Frontend

| `type`            | Frequency             | Key fields                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ----------------- | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `market_snapshot` | every 2s              | `price`, `bid`, `ask`, `spread_pct`, `volume_24h`, `order_book` (top 10 levels), `recent_trades` (last 50, each with `buyer_agent`/`seller_agent`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `candle`          | every 5s (bar close)  | `time`, `open`, `high`, `low`, `close`, `volume`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `chain_metrics`   | every 5s              | `coordinator_balance`, `total_locked`, `spread_pct`, `buy_depth`, `sell_depth`, `loop_stopped_any`, `coalition_alert` (last `CoalitionFormed` event or null), `recent_fills` (each with `tx_hash`, coalition fills have `category: "coalition"`), `somnia_block_ms`; nested `agents` map with per-agent: `decisions_total`, `buy_count`, `sell_count`, `hold_count`, `failures`, `orders_placed`, `treasury_balance`, `last_decision`, `last_price`, `last_fetched_price`, `last_context` (full LLM prompt), `win_streak`, `last_order_id`, `loop_stopped`, `loop_stopped_reason`, `trade_pnl`, `total_buy_volume`, `total_sell_volume`, `avg_decision_latency_ms`, `net_position`, `unrealized_pnl`, `wallet_address` |
| `coalition_alert` | on `CoalitionFormed`  | `direction` (`BUY`/`SELL`), `agent_count` (3), `price`, `order_id`, `block`, `timestamp` — broadcast immediately, not batched with 5s metrics cycle                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `risk_warning`    | on threshold breach   | `from_agent`, `severity` (`HIGH`/`MEDIUM`), `warning_type` (`HIGH_SPREAD`/`VOLATILITY_SPIKE`), `message`, `timestamp`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `event_injected`  | on event button click | `event_type`, `description`, `price_before`, `price_after`, `timestamp`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |

### Frontend → Backend

```json
{ "type": "inject_event", "data": { "event_type": "whale_buy" } }
```

Event types: `whale_buy`, `whale_sell`, `volatility_spike`, `news_event`, `flash_crash`

### HTTP Endpoints

| Method | Path              | Response                                                                           |
| ------ | ----------------- | ---------------------------------------------------------------------------------- |
| `GET`  | `/health`         | `{ status, agents_running, ws_connections }`                                       |
| `GET`  | `/state`          | Full market snapshot                                                               |
| `GET`  | `/agents`         | Array of 5 agent state summaries from `chain_metrics`                              |
| `GET`  | `/chain-metrics`  | Latest `chain_metrics` snapshot (coordinator balance, per-agent on-chain stats)    |
| `POST` | `/events/inject`  | `{ event_type }` → triggers event                                                  |
| `POST` | `/agents/trigger` | Re-fires `triggerAgentDecision()` for all 4 on-chain agents — use if loops stalled |
| `GET`  | `/debug/config`   | Non-sensitive config values + whether `AgentCoordinator` is initialized            |

---

## Frontend State (`frontend/store/`)

### `marketStore`

- `candles`: ring buffer (max 200) of OHLCV bars
- `orderBook`: `{ bids: Level[], asks: Level[] }` (top 10 each)
- `recentTrades`: last 50 trades
- `currentPrice`, `isConnected`

### `agentStore`

- `agents: Record<agent_id, AgentState>` — latest state for each of 5 agents; updated on every `chain_metrics` message
- `decisionHistory: Record<agent_id, string[]>` — last 20 `"BUY @ $3245"` entries per agent, derived from `chain_metrics` diffs
- `coordinatorBalance`, `totalLocked`, `loopStoppedAny`, `recentFills`, `somniaBlockMs` — top-level metrics from `chain_metrics`
- Per-agent fields include: `last_context` (full LLM prompt from `LLMRequestFired.context`), `win_streak` (from `DecisionExecuted.streak`), `net_position`, `unrealized_pnl`, `wallet_address`

`AgentScoreboard` (`components/agents/AgentScoreboard.tsx`) ranks all 5 agents by `trade_pnl + unrealized_pnl` in real-time and displays buy/sell volume and avg decision latency (`avg_decision_latency_ms`).

`AgentCard` displays a `🔥 N` streak badge next to the agent name when `win_streak > 0`, pulsing with an amber border. The tooltip shows the current order size multiplier. `ReasoningPanel` shows the live `last_context` string above the decision history — every cycle judges can read the exact peer signals the agent received.

### `feedStore`

- `items: ActivityFeedItem[]` — ring buffer (max 100, newest first)

---

## Agent Coordination — Risk Manager & Risk Warnings

```
Risk-Shield (risk_manager agent, on-chain)
  ↓ AgentCoordinator fires LLM request via Somnia platform
  ↓ _contract_metrics_poll_loop (5s) computes spread + volatility from on-chain data:
      If spread_pct > 2.0%:
        broadcast risk_warning { warning_type: "HIGH_SPREAD", severity: HIGH/MEDIUM }
      If log-return stddev of recent closes > 2%:
        broadcast risk_warning { warning_type: "VOLATILITY_SPIKE" }

MM-Prime / Momentum-Alpha / Arb-Scanner
  ↓ AgentCoordinator sends market context to Somnia LLM
  ↓ Somnia validators factor the context (spread, last price, best bid/ask) into BUY/SELL/HOLD
```

`risk_warning` messages are immediate WebSocket broadcasts, independent of the `chain_metrics` 5s cycle.

---

## Key Design Decisions

| Decision                                         | Reason                                                                                                                                                                                                                                                                                                                                                                                         |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Real ERC20 settlement (AGT)**                  | Exchange locks AGT on SELL placement, releases to the buyer on fill, and refunds on cancel. P&L is provable on the Somnia explorer via token balance changes — no trust in the backend's simulated bookkeeping needed. Coordinator holds a shared 10M AGT pool approved for Exchange; noise_trader and agent wallets each get 1M AGT via `seed.js`.                                            |
| **Self-re-triggering contract**                  | `handleDecision()` calls `_retrigger()` to fire the next cycle — agents run forever with zero Python involvement after startup. Emits `LoopStopped` on low balance for graceful halt.                                                                                                                                                                                                          |
| **One startup kick per agent**                   | Python's only blockchain interaction. The orchestrator fires `triggerAgentDecision()` once per agent with 1s stagger, then never touches the contracts again.                                                                                                                                                                                                                                  |
| **Cancel-before-place (`lastOrderId`)**          | `AgentCoordinator` tracks the most recent orderId per agent. Before each new order, it calls `exchange.cancelOrder(prev)`. Prevents resting-order book bloat over long demo sessions.                                                                                                                                                                                                          |
| **Market Maker dual-sided quoting**              | MM-Prime short-circuits the LLM decision and places both a bid (−0.1%) and an ask (+0.1%) per cycle, properly acting as a liquidity provider rather than a directional trader.                                                                                                                                                                                                                 |
| **Peer signals in LLM context (`lastDecision`)** | Every agent's LLM prompt includes what every other directional agent decided last cycle, assembled in `_buildPeerSignals()` from the `lastDecision` mapping. The full prompt is emitted in `LLMRequestFired.context` — on-chain verifiable inter-agent communication. Market Maker returns before `lastDecision` is written so it stays non-directional.                                       |
| **Win streak → adaptive order sizing**           | `winStreak[agentId]` increments on each filled order and resets on HOLD or failed `placeOrder`. `_orderAmount()` returns `ORDER_AMOUNT_BASE × (1 + streak/5)`, capped at 5×. Entirely on-chain — no Python configuration change needed. Streak is emitted as the 6th field of `DecisionExecuted` and shown as a live badge on the dashboard.                                                   |
| **Coalition orders at 3-agent consensus**        | `_coalitionCount(direction)` checks `lastDecision` for all registered agents. When exactly 3 agree (momentum, arbitrage, risk_manager), `_fireCoalitionOrder()` places a single 3× order and emits `CoalitionFormed`. Using `== 3` (not `>= 3`) ensures it fires exactly once per convergence event. Backend broadcasts `coalition_alert` immediately without waiting for the 5s metrics poll. |
| **Noise trader as Python coroutine**             | Random orders don't benefit from LLM overhead. `_noise_trader_loop` runs every 4–6s and places orders directly via `ExchangeContract.place_order()`, keeping the book alive between LLM cycles without consuming coordinator STT.                                                                                                                                                              |
| **Noise trader BUY-only in local dev**           | The noise trader calls Exchange directly, bypassing the `AgentCoordinator`'s shared AGT pool. SELL orders require `token.transferFrom` so a wallet with no AGT tokens reverts with "Insufficient balance". `_noise_trader_loop` always places BUY orders; `deploy-local.js` additionally mints 10,000 AGT to the noise trader wallet so a future SELL path is possible without re-deploying. |
| **Deployer key exclusive to daemon**             | `platform-daemon.js` wraps the deployer wallet in `ethers.NonceManager`, tracking nonces in-memory. Any other process sending txs from the same key (e.g. Python registry writes) silently advances the on-chain nonce past the daemon's cache, causing "nonce too low" on every queued callback. Registry write operations (`incrementTrades`, `updateReputation`) were removed from the Python orchestrator to keep the deployer key exclusive to the daemon.                                                |
| **Dedicated contract metrics poll loop**         | Backend observes the on-chain loop via event polling rather than driving it. Gives the dashboard real per-agent stats (decisions, BUY/SELL split, fuel remaining) without coupling Python to the trading cycle.                                                                                                                                                                                |
| **`from_block` advancement in metrics loop**     | Each poll advances `from_block` past the last seen block so coordinator and exchange events are never double-counted across poll cycles.                                                                                                                                                                                                                                                       |
| **Net position & unrealized P&L**                | `_record_pnl_from_trade` updates `net_position` per agent (buyer +amount, seller −amount); `_collect_chain_metrics` marks to market using `current_price`. Frontend scoreboard sorts by `trade_pnl + unrealized_pnl`.                                                                                                                                                                          |
| **`_is_address()` guard on contract init**       | Validates addresses against `r"0x[0-9a-fA-F]{40}"` before instantiating contracts — handles unconfigured `.env` without crashing at startup.                                                                                                                                                                                                                                                   |
| **`_load_local_deployment()`**                   | On startup, reads `contracts/deployments/somnia-local.json` and injects contract addresses + agent PKs into `settings`. When `SOMNIA_RPC_URL` points to `127.0.0.1` or `localhost`, the local JSON **always** takes precedence — this prevents stale-but-real-looking `.env` addresses from bypassing the override guard after a redeploy. On testnet the guard only fires for exact placeholder values. Enables zero-config local dev: deploy with `deploy-local.js`, start with `./start.sh`, done. |
| **Hardcoded 6 gwei gas price**                   | Dynamic `eth_gasPrice` RPC returns unreliable values on Somnia testnet and causes tx failures.                                                                                                                                                                                                                                                                                                 |
| **Per-wallet `asyncio.Lock`**                    | Concurrent startup triggers (1s stagger) would cause nonce conflicts without exclusive access per wallet.                                                                                                                                                                                                                                                                                      |
| **GBM price engine, not real feed**              | Demo needs controllable events (whale buy, crash) — replaced by on-chain prices once fills arrive.                                                                                                                                                                                                                                                                                             |
| **Ring buffers in frontend (max 200/100)**       | Prevents memory growth during extended demo sessions.                                                                                                                                                                                                                                                                                                                                          |
| **`series.update()` only for chart**             | Calling `setData()` repeatedly on TradingView v5 causes visible flicker and memory leaks.                                                                                                                                                                                                                                                                                                      |
| **`key={fillCount}` animation restart**          | `LatencyHero` passes a counter as `key` to the animated latency number — React remounts the element on each fill, restarting the CSS `animate-pulse` as a visual "new trade settled" pop.                                                                                                                                                                                                      |
