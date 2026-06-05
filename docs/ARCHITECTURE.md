# Architecture — Agentic Exchange

Real-time autonomous trading demo on Somnia (chain 50312). Five system agents trade autonomously on-chain — four via Somnia's LLM consensus layer, one (noise_trader) via a fully on-chain mean-reversion rule. Any user can also deploy their own **composable user agent** via a single MetaMask transaction.

All five agents share a **single coordinator pool** of synthetic tokens (`AgentCoordinator` holds the sETH and USDC). Each agent has a virtual token balance tracked on-chain via fill/cancel callbacks from `Exchange`. STT fees for Somnia platform calls are tracked per user wallet — all agents owned by the same address share one prepaid STT pool.

---

## Component Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Somnia Blockchain (chain 50312)                    │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Exchange.sol  (real on-chain LOB)                           │    │
│  │  placeOrderForAgent(isBuy, price, amount, agentId)          │    │
│  │    → _matchOrder → TradeExecuted                            │    │
│  │    → onAgentFill(agentId, isBuy, tokenFill, quoteFill)      │    │
│  │  cancelOrder → onAgentCancel(agentId, isBuy, ...)            │    │
│  └─────────────────────┬──────────────────────────────────────┘    │
│                         │ coordinator is msg.sender for all orders   │
│  ┌──────────────────────┴──────────────────────────────────────┐   │
│  │  AgentCoordinator.sol  (shared pool + execution engine)      │   │
│  │                                                              │   │
│  │  agentTokenBalance[agentId]  agentQuoteBalance[agentId]      │   │
│  │  userSttBalance[ownerAddress]   agentOwner[agentId]          │   │
│  │                                                              │   │
│  │  LLM agents:  trigger → price fetch → LLM → handleDecision  │   │
│  │  Noise trader: trigger → price fetch → _executeRuleDecision  │   │
│  │                                                              │   │
│  │  winStreak, lastDecision, peer signals, coalition orders     │   │
│  │  _retrigger() → self-loop                                    │   │
│  └──────────────────────┬──────────────────────────────────────┘   │
│                          │ reads config via IAgentRegistry           │
│  ┌───────────────────────┴─────────────────────────────────────┐   │
│  │  AgentRegistry.sol  (source of truth — all agents)           │   │
│  │  registerAgent() · pauseAgent/resumeAgent · config getters   │   │
│  └─────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Somnia LLM Inference Agent                                   │   │
│  │  inferString(ctx+peers+streak, systemPrompt, ["BUY","SELL","HOLD"])│
│  └─────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
     ↑ 1 startup tx per agent  ↑ user registerAgent() from MetaMask
┌────────┴──────────────────────────────────────────────────────────────┐
│                         FastAPI Backend                                │
│  trade event poll (1s) ──► PriceEngine ──► MarketStateBus            │
│  snapshot broadcast (3s)                                              │
│  contract metrics poll (5s) ──► chain_metrics                        │
│    detects AgentRegistered → allocateToAgent → triggerAgentDecision  │
│  token replenisher (30s) → tops up coordinator pool only             │
└──────────────────────────────┬────────────────────────────────────────┘
                               │ WebSocket
┌──────────────────────────────▼────────────────────────────────────────┐
│  Next.js Dashboard                                                    │
│  System + user agent cards · Scoreboard · Chart · OrderBook           │
│  MY AGENTS: Create (register + fund STT) / Pause / Resume            │
└───────────────────────────────────────────────────────────────────────┘
```

---

## Per-Agent Virtual Balance Accounting

All orders are placed by the coordinator contract as `msg.sender`. Individual agent wallets do not exist — instead each agent has virtual token balances within the coordinator's shared pool.

### At registration

```
allocateToAgent(agentId, ownerAddress, 10K sETH, 10K USDC)
  → agentTokenBalance[agentId] = 10K sETH
  → agentQuoteBalance[agentId] = 10K USDC
  → agentOwner[agentId] = ownerAddress
```

### At order placement (handleDecision / _executeRuleDecision)

```
BUY order:
  agentQuoteBalance[agentId] -= price * amount / 1e18   (USDC locked in Exchange)
  placeOrderForAgent(true, price, amount, agentId)
  → Exchange stores _orderAgentId[orderId] = agentId

SELL order:
  agentTokenBalance[agentId] -= amount   (sETH locked in Exchange)
  placeOrderForAgent(false, price, amount, agentId)
```

### On fill (Exchange callback to coordinator)

```
onAgentFill(agentId, true, tokenFill, quoteFill):
  agentTokenBalance[agentId] += tokenFill    (received sETH)
  // USDC already deducted at placement

onAgentFill(agentId, false, tokenFill, quoteFill):
  agentQuoteBalance[agentId] += quoteFill    (received exact USDC from locked ratio)
  // sETH already deducted at placement
```

### On cancel (Exchange callback to coordinator)

```
onAgentCancel(agentId, true, 0, remainingQuote):
  agentQuoteBalance[agentId] += remainingQuote   (unfilled USDC returned)

onAgentCancel(agentId, false, unfilledTokens, 0):
  agentTokenBalance[agentId] += unfilledTokens   (unfilled sETH returned)
```

**Note:** `quoteFill` in `onAgentFill` is the exact USDC computed by Exchange (`lockedQuote * fill / totalAmount`), not `fillPrice * fill`. This avoids rounding discrepancies on partial fills.

---

## Per-User STT Accounting

Each Somnia platform call costs one deposit of STT. `userSttBalance[ownerAddress]` tracks how much each user has prepaid. All agents owned by the same wallet share one balance.

### Funding

```
coordinator.fund() payable
  → userSttBalance[msg.sender] += msg.value
  → emit SttDeposited(msg.sender, msg.value)
```

Frontend `fundAgent()` calls `fund()` via MetaMask — `msg.sender` = user wallet = correct pool automatically.

### Deduction per cycle

```
triggerAgentDecision / _retrigger (JSON API call):
  owner = agentOwner[agentId]
  require(userSttBalance[owner] >= deposit * 2)   // reserve for JSON API + LLM
  userSttBalance[owner] -= deposit

_fireLLMRequest (LLM call):
  userSttBalance[agentOwner[agentId]] -= deposit

_executeRuleDecision (noise_trader, rule-based):
  // only 1 deposit consumed (JSON API) — LLM call skipped
```

When `userSttBalance` drops below `deposit * 2`, the agent loop emits `LoopStopped(agentId, "Insufficient STT", balance)` and halts gracefully.

---

## Noise Trader — On-Chain Rule

Noise-Bot is the only agent with an empty `systemPrompt` in `AgentRegistry`. The coordinator detects this in `handlePriceData` and routes to `_executeRuleDecision` instead of `_fireLLMRequest`:

```
if (bytes(IAgentRegistry(registry).getSystemPrompt(req.agentId)).length == 0) {
    _executeRuleDecision(req.agentId, fetchedPrice);
    return;
}
_fireLLMRequest(req.agentId, fetchedPrice);
```

**Rule (order-book balance):**
- `getActiveSells().length > getActiveBuys().length` → BUY (asks outnumber bids — provide buy side)
- `getActiveBuys().length > getActiveSells().length` → SELL (bids outnumber asks — provide sell side)
- Balanced or no prior trades → `block.prevrandao % 2 == 0`

This guarantees noise bot always counterbalances the market: when all LLM agents cluster on SELL, asks pile up and noise bot flips to BUY immediately on its next cycle.

This keeps the exchange price anchored to the oracle without LLM overhead. No Python involvement after the initial trigger.

---

## Three-Step Agent Pipeline (LLM agents)

```
triggerAgentDecision(agentId)   ← called once by Python at startup
  check userSttBalance[owner] >= deposit * 2
  deduct 1 deposit from userSttBalance[owner]
  platform.createRequest{value: deposit}(jsonApiAgentId, handlePriceData.selector, fetchUint(...))
  → pendingPriceRequests[reqId] = PriceRequest(agentId, true)

handlePriceData(requestId, ...)   ← Somnia JSON API callback
  fetchedPrice = abi.decode(...)
  if systemPrompt empty → _executeRuleDecision(agentId, fetchedPrice) [noise trader]
  else → _fireLLMRequest(agentId, fetchedPrice)
    deduct 1 deposit from userSttBalance[agentOwner[agentId]]
    context = _buildContext(fetchedPrice, agentId)
      → reads Exchange.getLastTradePrice(), getBestBid/Ask()
      → _buildPeerSignals() → "market_maker=BUY, momentum_trader=SELL"
      → streak info if winStreak[agentId] > 0
    platform.createRequest{value: deposit}(llmAgentId, handleDecision.selector,
      inferString(context, systemPrompt, false, ["BUY","SELL","HOLD"]))

handleDecision(requestId, ...)   ← Somnia LLM validator callback
  cancel lastOrderId + lastBidOrderId (cancel-before-place)
  market_maker: places bid(−0.1%) + ask(+0.1%) → return
  directional agents:
    decision = abi.decode(...) → "BUY" / "SELL" / "HOLD"
    lastDecision[agentId] = decision  ← read by peers next cycle
    _coalitionCount(decision) == 3 → _fireCoalitionOrder() (3× order)
    deduct from agentTokenBalance / agentQuoteBalance
    exchange.placeOrderForAgent(isBuy, price, amount, agentId)
      → on fill: onAgentFill callback updates virtual balance
      → on cancel: onAgentCancel callback restores locked balance
    winStreak[agentId]++  or  = 0 on HOLD/fail
  _retrigger(agentId)
    check userSttBalance[agentOwner[agentId]] >= deposit * 2
    deduct 1 deposit, fire next JSON API request → loop continues
    OR emit LoopStopped if balance insufficient
```

---

## Background Loops

| Loop | Interval | Responsibility |
|------|----------|----------------|
| `MetricsCollector.run_trade_poll` | 1s | Polls `TradeExecuted` events → anchors GBM price, builds OHLCV |
| `_snapshot_broadcast_loop` | 3s | Pushes `market_snapshot` WS message |
| `MetricsCollector.collect` | 5s | Reads coordinator events, Exchange state, P&L → `chain_metrics` WS |
| `TokenReplenisher.run` | 30s | Polls coordinator pool balance → mints if below 1K tokens |

---

## Smart Contracts

### Exchange.sol

Real on-chain LOB. Key additions vs standard exchange:

- `placeOrderForAgent(isBuy, price, amount, agentId)` — stores `_orderAgentId[orderId] = agentId`; triggers fill/cancel callbacks to coordinator
- `IAgentFillCallback` interface — `onAgentFill(agentId, isBuy, tokenFill, quoteFill)` and `onAgentCancel(agentId, isBuy, unfilledTokens, remainingQuote)`
- `quoteFill` in callbacks is computed from `_lockedQuote[buyId]` ratio, not from `fillPrice * fill` — ensures accounting accuracy on partial fills
- `try/catch` on all callbacks — a failing callback never reverts the trade

### AgentCoordinator.sol

Execution engine — pure runtime state, reads all config from `AgentRegistry`.

**State:**
- `winStreak[agentId]`, `lastDecision[agentId]`, `agentPaused[agentId]`
- `lastOrderId[agentId]`, `lastBidOrderId[agentId]`
- `agentTokenBalance[agentId]`, `agentQuoteBalance[agentId]` — virtual pool shares
- `userSttBalance[ownerAddress]` — prepaid STT per user wallet
- `agentOwner[agentId]` — cached at `allocateToAgent` time

**Functions:**
- `allocateToAgent(agentId, owner, tokenAmt, quoteAmt)` — sets virtual balances + caches owner
- `fund() payable` / `depositStt(forOwner) payable` — STT deposit
- `getUserSttBalance(owner)` — view
- `onAgentFill` / `onAgentCancel` — called by Exchange only
- `_executeRuleDecision` — mean-reversion rule for noise_trader (no LLM)

### AgentRegistry.sol

Unified registry for all agents. `registerAgent()` is open to any wallet. `agentOwner` = `msg.sender`. `pauseAgent/resumeAgent` check `msg.sender == agentOwner`. Config stored here (`systemPrompt`, `priceUrl`, `selector`, `decimals`, `riskLevel`); coordinator reads via view getters each cycle.

---

## WebSocket Messages

| `type` | Frequency | Key fields |
|--------|-----------|------------|
| `market_snapshot` | 3s | `price`, `bid`, `ask`, `spread_pct`, `order_book`, `recent_trades` |
| `candle` | 5s (bar close) | `time`, `open`, `high`, `low`, `close`, `volume` |
| `chain_metrics` | 5s | `coordinator_balance`, per-agent `agentTokenBalance`/`agentQuoteBalance`/`userSttBalance`, `win_streak`, `last_decision`, `trade_pnl`, `unrealized_pnl`, `loop_stopped` |
| `coalition_alert` | on `CoalitionFormed` | `direction`, `agent_count`, `price`, `order_id` |
| `risk_warning` | on threshold | `warning_type`, `severity`, `message` |

---

## Key Design Decisions

| Decision | Reason |
|----------|--------|
| **All agents share coordinator pool** | Users can't manage 5+ EOA wallets. Virtual balance accounting gives isolation without per-agent keys. |
| **agentOwner cached in coordinator** | Avoids a registry cross-call on every `_retrigger` cycle. Set once at `allocateToAgent` time. |
| **Per-user STT pool (not per-agent)** | A user with 3 agents shouldn't need to fund each separately. One wallet → one STT pool covering all owned agents. |
| **fund() tracks msg.sender** | Frontend calls `fund()` from user wallet — `msg.sender` = user address = correct pool owner automatically. |
| **quoteFill from locked ratio** | Exchange computes `lockedQuote * fill / totalAmount` — not `fillPrice * fill`. This is the actual USDC the seller receives; using the ratio prevents virtual balance drift on partial fills. |
| **Empty systemPrompt = rule-based** | No new mapping needed. Noise-bot registered with `systemPrompt = ""`. Coordinator detects this in `handlePriceData`. |
| **Noise-bot order-book balance rule** | LLMs aren't random — a prompt can't produce true noise. Mean-reversion against oracle failed in practice: when all LLM agents SELL, the exchange price drops with the oracle (correlated), so the condition never flips. Order-book depth comparison is more robust: when sells outnumber bids, noise bot BUYs unconditionally regardless of price level. |
| **UUPS proxies for all 6 contracts** | Deploy once to testnet, upgrade implementations without changing addresses or losing state. |
| **Self-re-triggering contract** | `_retrigger()` fires the next cycle on-chain after every decision. Python fires one tx per agent at startup. Zero off-chain computation in the decision loop thereafter. |
| **Cancel-before-place** | `lastOrderId` + `lastBidOrderId` per agent. Both cancelled before each new cycle — prevents resting-order bloat in long demo sessions. |
| **6 gwei hardcoded gas** | Dynamic `eth_gasPrice` causes tx failures on Somnia testnet. |
| **_order_to_agent in backend** | `AgentCoordinator` is `msg.sender` for all Exchange orders — individual agents never appear in `OrderPlaced.agent`. `DecisionExecuted` carries both `agentId` and `orderId`, so backend builds `{order_id → agent_id}` for trade attribution. |
