# Backend — Agentic Exchange

Python FastAPI server that kicks off five system autonomous agents on Somnia, observes their activity, and supports any number of **user-defined composable agents**. Four system agents (market_maker, momentum_trader, arbitrage_agent, risk_manager) are validated by Somnia's LLM inference agent (multi-validator consensus). A fifth (noise_trader) runs as a pure Python coroutine. User agents are discovered automatically by polling `AgentOwnerSet` events — no backend API call required to create them.

---

## Directory Map

```
backend/
├── main.py                  # FastAPI app, CORS, lifespan startup/shutdown
│                            # calls validate_settings() first — hard-exits on missing/bad PKs
├── config.py                # Pydantic Settings — env vars; no usable PK defaults
│                            # validate_settings(): exits with clear error if PKs missing on non-localhost
├── .env.example             # ← committed template: copy to .env and fill in values
├── .env                     # Secret keys — NOT committed (.gitignore)
├── agents/
│   ├── orchestrator.py      # AGENT_CONFIGS (5 system), poll loops, metrics loop, _noise_trader_loop(),
│   │                        # _load_local_deployment(), polls AgentOwnerSet events,
│   │                        # _on_user_agent_registered(), _reload_user_agents_from_db(), watchdog for user agents
│   └── user_agents_db.py    # JSON cache: backend/data/user_agents.json (no private keys)
├── market/
│   ├── price_engine.py      # GBM price simulation + OHLCVBuilder (5s bars)
│   ├── price_feed.py        # CoinGecko + Binance ETH/USD feed (reference price fallback)
│   ├── order_book.py        # In-memory bid/ask depth (BookEntry, OrderBook)
│   └── state_bus.py         # Async-safe shared state: price, order book, warnings, events
├── blockchain/
│   ├── client.py            # Web3 singleton, per-wallet nonce Lock, send_transaction()
│   └── contracts.py         # Typed wrappers: ExchangeContract, TreasuryContract,
│                            # AgentCoordinatorContract, AgentRegistryContract, AgentTokenContract, QuoteTokenContract
└── api/
    ├── websocket_hub.py     # ConnectionManager: broadcast() to all WS clients
    ├── routes_ws.py         # /ws WebSocket endpoint + message dispatch
    ├── auth.py              # MetaMask wallet-signature auth: verify_admin_signature() + admin_auth FastAPI dep
    ├── routes_http.py       # REST endpoints (health, state, agents, chain-metrics, events, trigger,
    │                        # agents/{id}/pause, agents/{id}/resume, agents/{id}/fund,
    │                        # agents/pause-all, agents/resume-all, agents/fund-all)
    └── routes_user_agents.py# GET /user/agents?address=0x... — cached user agent list + live metrics
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
# Fill in all 6 private keys (+ contract addresses for testnet)
# The backend will not start if any key is missing when pointing at non-localhost

# 4. Start
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 5. Health check
curl http://localhost:8000/health
# → {"status":"ok","agents_running":0,"ws_connections":0}
```

---

## Configuration Reference

All settings live in `config.py` (Pydantic Settings) and are loaded from `backend/.env`.

| Variable                    | Default                            | Required       | Purpose                                                                                                                                |
| --------------------------- | ---------------------------------- | -------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `SOMNIA_RPC_URL`            | `https://dream-rpc.somnia.network` | No             | Somnia RPC endpoint (`http://127.0.0.1:8545` for local Hardhat)                                                                        |
| `SOMNIA_CHAIN_ID`           | `50312`                            | No             | Somnia chain ID (`31337` for local Hardhat)                                                                                            |
| `EXCHANGE_ADDRESS`          | zero address                       | **Yes**†       | Deployed Exchange.sol address                                                                                                          |
| `AGENT_REGISTRY_ADDRESS`    | zero address                       | **Yes**†       | Deployed AgentRegistry.sol address                                                                                                     |
| `TREASURY_ADDRESS`          | zero address                       | **Yes**†       | Deployed Treasury.sol address                                                                                                          |
| `AGENT_COORDINATOR_ADDRESS` | zero address                       | **Yes**†       | Deployed AgentCoordinator.sol address                                                                                                  |
| `AGENT_TOKEN_ADDRESS`       | zero address                       | **Yes**†       | Deployed AgentToken (sETH) address                                                                                                     |
| `QUOTE_TOKEN_ADDRESS`       | zero address                       | **Yes**†       | Deployed QuoteToken (USDC) address                                                                                                     |
| `DEPLOYER_PRIVATE_KEY`      | *(empty)*                          | **Yes**‡       | Deployer wallet — signs `triggerAgentDecision()`, mints USDC top-ups                                                                   |
| `MARKET_MAKER_PK`           | *(empty)*                          | **Yes**‡       | Market Maker agent wallet private key                                                                                                  |
| `MOMENTUM_TRADER_PK`        | *(empty)*                          | **Yes**‡       | Momentum Trader wallet private key                                                                                                     |
| `ARBITRAGE_AGENT_PK`        | *(empty)*                          | **Yes**‡       | Arb Scanner wallet private key                                                                                                         |
| `RISK_MANAGER_PK`           | *(empty)*                          | **Yes**‡       | Risk Shield wallet private key                                                                                                         |
| `NOISE_TRADER_PK`           | *(empty)*                          | **Yes**‡       | Noise Bot wallet — direct Exchange orders                                                                                              |
| `INITIAL_PRICE`             | `3500.0`                           | No             | Starting price for GBM chart (until real trades come in)                                                                               |
| `SOMNIA_BLOCK_MS`           | `0`                                | No             | Somnia block time in ms for latency display. Set to `400` for testnet, `0` for Hardhat.                                                |
| `FRONTEND_URL`              | `http://localhost:3000`            | No             | Allowed CORS origin                                                                                                                    |

† **Address auto-load:** on localhost `_load_local_deployment()` reads `contracts/deployments/somnia-local.json` and injects real addresses. On testnet it reads `somnia-testnet.json`. Zero-address defaults are safe — contracts simply won't activate until real addresses are present.

‡ **Private key validation:** defaults are empty strings — no usable fallback. `validate_settings()` (called in `lifespan` before anything starts) enforces:
- **localhost** — missing PKs are allowed; `_load_local_deployment()` fills them from `somnia-local.json`
- **non-localhost** — any missing or malformed PK causes an immediate `sys.exit(1)` with a clear error listing exactly which variables need to be set. Copy `backend/.env.example` to `backend/.env` for the full template.

**`deployer_address`** is not an env var — it is derived at startup from `DEPLOYER_PRIVATE_KEY` via `Account.from_key().address`. The admin auth middleware compares incoming wallet addresses against this derived value.

**Contracts activate automatically** when addresses in `.env` are valid 20-byte hex strings (not placeholders). On startup the orchestrator fires one `triggerAgentDecision()` per agent; after that the contract self-re-triggers and Python never touches the contracts again.

---

## Orchestrator Background Loops

`AgentOrchestrator.start_all()` always starts these loops:

| Loop                          | Interval | Purpose                                                                                                                                                                           |
| ----------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `_trade_event_poll_loop`      | 1s       | Reads `TradeExecuted` events, updates `PriceEngine` and `MarketStateBus`, broadcasts `candle` WS messages                                                                         |
| `_snapshot_broadcast_loop`    | 2s       | Reads `MarketStateBus.get_snapshot()`, broadcasts `market_snapshot` WS message                                                                                                    |
| `_contract_metrics_poll_loop` | 5s       | Reads coordinator events + contract state, broadcasts `chain_metrics` WS message; emits `risk_warning` on spread > 2% or volatility spike > 2%                                    |
| `_noise_trader_loop`          | 4–6s     | Places a random buy or sell order directly via `ExchangeContract.place_order()` using `NOISE_TRADER_PK`. No LLM, no coordinator. Random price ±0.5%, random amount 0.03–0.08 ETH. |

When `_coordinator` is set, it additionally fires one `triggerAgentDecision()` per agent (the 4 on-chain agents) at startup (staggered 1s apart). After that, the on-chain loop is self-sustaining.

### Contract Metrics Poll

`_contract_metrics_poll_loop` runs every 5s and accumulates the following into `self._chain_metrics`:

```python
{
  "coordinator_balance": float,       # STT remaining in AgentCoordinator
  "total_locked": float,              # total STT in Treasury
  "spread_pct": float,                # live (ask - bid) / bid × 100
  "buy_depth": int,                   # active buy order count in Exchange
  "sell_depth": int,                  # active sell order count in Exchange
  "loop_stopped_any": bool,           # true if any agent emitted LoopStopped
  "somnia_block_ms": int,             # from config — used by frontend for latency display
  "recent_fills": [                   # last 20 matched trades, newest first
    {
      "price": float,
      "amount": float,
      "buyer_agent": str,             # agent_id or "external"
      "seller_agent": str,
      "block": int,
      "tx_hash": str,                 # transaction hash (empty string if unavailable)
    }
  ],
  "agents": {
    "<agent_id>": {
      "decisions_total": int,         # total DecisionExecuted events
      "buy_count": int,
      "sell_count": int,
      "hold_count": int,
      "failures": int,                # DecisionFailed events
      "orders_placed": int,           # DecisionExecuted events with a non-zero orderId (on-chain agents)
                                      # or OrderPlaced events from wallet (noise_trader)
      "agt_balance": float,           # sETH token balance — coordinator's balance for on-chain agents,
                                      # individual wallet balance for noise_trader
      "paused": bool,                 # true if pauseAgent() was called and loop is halted
      "treasury_balance": float,      # Treasury.getBalance(wallet) in ETH
      "last_decision": str,           # "BUY" | "SELL" | "HOLD" | null
      "last_price": float,            # price from last DecisionExecuted
      "last_fetched_price": float,    # raw ETH/USD oracle from last LLMRequestFired (context-only)
      "quote_balance": float,         # USDC cash balance — payment currency for BUY orders
      "last_order_id": int | null,    # orderId from last DecisionExecuted
      "loop_stopped": bool,
      "loop_stopped_reason": str,
      "trade_pnl": float,             # running P&L from TradeExecuted events (sell vol - buy vol)
      "total_buy_volume": float,      # cumulative USD value of buy fills
      "total_sell_volume": float,     # cumulative USD value of sell fills
      "avg_decision_latency_ms": float, # avg blocks(trigger→executed) × somnia_block_ms
      "decision_latency_count": int,
      "net_position": float,          # running net position: buyer += amount, seller -= amount
      "unrealized_pnl": float,        # net_position × current_price (mark-to-market)
      "wallet_address": str,          # agent's on-chain wallet address
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

In-memory bid/ask book (`dict[order_id, BookEntry]`). Rebuilt from real on-chain order data every 5s via `MarketStateBus.set_order_book(bids, asks)`.

### MarketStateBus (`market/state_bus.py`)

The shared state layer — the metrics loop writes real on-chain order book data here every 5s.

| Method                                 | Description                                                                  |
| -------------------------------------- | ---------------------------------------------------------------------------- |
| `get_snapshot()`                       | Price, bid/ask, spread, volume, order book (top 10), recent trades (last 50) |
| `inject_event(event_type, params)`     | Records a market event (updates GBM display)                                 |
| `set_agent_warning(agent_id, warning)` | Writes a warning visible in MarketStateBus                                   |
| `clear_agent_warning(agent_id)`        | Removes an active warning                                                    |
| `get_active_warnings()`                | Returns list of current active warnings                                      |

All methods protected by `asyncio.Lock` for safe concurrent access from multiple concurrent loops (agent polls, noise_trader, broadcast loops).

---

## Blockchain Integration

### `blockchain/client.py`

- **Single Web3 instance** shared across all agents (cached, thread-safe)
- **POA middleware** (`ExtraDataToPOAMiddleware`) applied for Somnia's PoA consensus
- **Hardcoded gas price: 6 gwei** — dynamic `eth_gasPrice` RPC calls cause failures on Somnia testnet
- **Per-wallet `asyncio.Lock`**: 5 agents each own a wallet; the lock prevents nonce reuse when agents transact concurrently
- **30s receipt timeout**: if confirmation doesn't arrive, logs a warning and the agent continues (never blocks)

### `blockchain/contracts.py`

ABI loading strategy: tries `contracts/deployments/somnia-testnet.json` first (deployed ABIs), falls back to minimal inline ABIs. This means the backend works before deployment with reduced functionality.

**`AgentCoordinatorContract`** — wraps `AgentCoordinator.sol`:

- `trigger_decision(agent_pk, agent_id)` → ABI-encodes `triggerAgentDecision(agentId)`, submits signed tx from the agent's wallet. Called once per agent at startup by `orchestrator.start_all()`. After this the contract self-loops.
- `get_balance()` → reads the coordinator's STT balance (must stay funded; each cycle costs 2 deposits)
- `get_coordinator_events(from_block)` → polls `DecisionExecuted`, `DecisionFailed`, `LoopStopped`, `LLMRequestFired`, `AgentPaused`, `AgentResumed` events in one pass, returns them sorted by block number
- `get_decision_executed_events(from_block)` → targeted single-event poll for `DecisionExecuted` only; called at the top of each 1s trade loop iteration to populate `_order_to_agent` before trade attribution
- `pause_agent(deployer_pk, agent_id)` → calls `pauseAgent(agentId)` on-chain
- `resume_agent(deployer_pk, agent_id)` → calls `resumeAgent(agentId)` on-chain
- `is_paused(agent_id) -> bool` → view call to `agentPaused[agentId]`

**`AgentTokenContract`** — wraps `AgentToken.sol` (sETH):

- `mint(deployer_pk, to_address, amount_seth)` → mints sETH to any address (owner-only on-chain)

**`QuoteTokenContract`** — wraps `QuoteToken.sol` (USDC):

- `get_balance(address)` → USDC balance
- `mint(deployer_pk, to_address, amount)` → mints USDC (owner-only); used for auto-replenishment
- `faucet(caller_pk)` → permissionless self-top-up (10K USDC per call)
- `get_balance(address) -> float` → `balanceOf(address)` scaled from wei
- `get_total_supply() -> float` → `totalSupply()` scaled from wei

**`AgentRegistryContract`** — wraps `AgentRegistry.sol`:

- `set_active(deployer_pk, agent_address, active)` → calls `setActive(agent, active)` on-chain

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

| `type`            | Frequency           | Fields                                                                                                                                      |
| ----------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `market_snapshot` | every 2s            | `price`, `bid`, `ask`, `spread_pct`, `volume_24h`, `order_book` (top 10), `recent_trades` (last 50, each with `buyer_agent`/`seller_agent`) |
| `candle`          | every 5s            | `time`, `open`, `high`, `low`, `close`, `volume`                                                                                            |
| `chain_metrics`   | every 5s            | Full `chain_metrics` object — see schema above                                                                                              |
| `risk_warning`    | on threshold breach | `from_agent`, `severity` (`HIGH`/`MEDIUM`), `warning_type` (`HIGH_SPREAD`/`VOLATILITY_SPIKE`), `message`, `timestamp`                       |
| `event_injected`  | on button click     | `event_type`, `description`, `price_before`, `price_after`, `timestamp`                                                                     |

### Frontend → Backend

```json
{ "type": "inject_event", "data": { "event_type": "whale_buy" } }
{ "type": "ping" }
```

### HTTP Endpoints

| Method | Path                        | Auth       | Description                                                                                           |
| ------ | --------------------------- | ---------- | ----------------------------------------------------------------------------------------------------- |
| `GET`  | `/health`                   | —          | `{ status, agents_running, ws_connections }`                                                          |
| `GET`  | `/state`                    | —          | Full market snapshot from `MarketStateBus`                                                            |
| `GET`  | `/agents`                   | —          | Array of 5 agent state summaries from `chain_metrics`                                                 |
| `GET`  | `/chain-metrics`            | —          | Latest `chain_metrics` snapshot (live coordinator/exchange/treasury state)                            |
| `POST` | `/events/inject`            | —          | Body: `{ "event_type": "...", "params": {} }`                                                         |
| `POST` | `/agents/trigger`           | —          | Re-fires `triggerAgentDecision()` for all 4 on-chain agents; returns per-agent tx hashes or errors    |
| `GET`  | `/debug/config`             | —          | Non-sensitive settings + `coordinator_initialized` flag — useful for diagnosing misconfigured `.env`  |
| `POST` | `/agents/{agent_id}/pause`  | admin_auth | Calls `coordinator.pause_agent(deployer_pk, agent_id)`; loop stops at next `_retrigger()` call        |
| `POST` | `/agents/{agent_id}/resume` | admin_auth | Calls `coordinator.resume_agent(deployer_pk, agent_id)` then re-fires `trigger_decision()` to restart |
| `POST` | `/agents/pause-all`         | admin_auth | Pauses all 4 on-chain agents in sequence                                                              |
| `POST` | `/agents/resume-all`        | admin_auth | Resumes all 4 on-chain agents and restarts each loop                                                  |
| `POST` | `/agents/{agent_id}/fund`   | admin_auth | Body: `{ "amount": float }` — mints sETH to the agent (or coordinator for on-chain agents)            |
| `POST` | `/agents/fund-all`          | admin_auth | Body: `{ "amount": float }` — mints sETH to all on-chain agents (via coordinator)                     |

**Admin auth** (`admin_auth` FastAPI dependency in `api/auth.py`): reads `X-Admin-Sig`, `X-Admin-Message`, `X-Admin-Address` headers. Message format: `"admin:<action>:<unix_timestamp>"`. Recovers the signer via `eth_account.Account.recover_message()` and compares against `settings.deployer_address`. Requests older than 5 minutes are rejected to prevent replay attacks. Returns HTTP 403 on any mismatch.

---

## Tuning Agent Behavior

### Change a strategy prompt

Edit the `setSystemPrompt` calls in `contracts/scripts/deploy.js` and redeploy. System prompts are stored on-chain in `AgentCoordinator` and passed to the Somnia LLM inference agent on each decision cycle.

### Add a new agent

**Option A — Somnia-native (LLM decisions on-chain):**

1. Add entry to `AGENT_CONFIGS` in `agents/orchestrator.py`
2. Add `new_agent_pk` field to `config.py`
3. Add wallet PK to `backend/.env`
4. Add `setSystemPrompt` + `setAgentConfig` calls in `contracts/scripts/deploy.js`
5. Register + fund in `contracts/scripts/seed.js`
6. The orchestrator fires `triggerAgentDecision()` automatically for all `AGENT_CONFIGS` entries at startup

**Option B — Python-only (no LLM, like noise_trader):**

1. Add `new_agent_pk` field to `config.py`
2. Add wallet PK to `backend/.env`
3. Add a `_new_agent_loop()` coroutine in `agents/orchestrator.py`
4. Start the task in `start_all()` and cancel it in `stop_all()`

### Change initial price or volatility

Set `INITIAL_PRICE` and `PRICE_VOLATILITY` in `backend/.env`. Volatility (`σ`) of `0.025` produces ~2.5% price swings per tick under normal conditions. These only affect the GBM chart display — actual trade prices come from on-chain fills.

---

## Key Design Decisions

| Decision                                     | Reason                                                                                                                                                                                                                                                                                                                                                          |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Contract metrics poll, not agent push        | Backend observes the on-chain loop via event polling rather than driving it. Decouples dashboard from the trading cycle and never blocks the contract's self-trigger cadence.                                                                                                                                                                                   |
| `from_block` advances in metrics loop        | After each poll the loop stores `max_block_seen + 1` so events are counted exactly once across poll cycles.                                                                                                                                                                                                                                                     |
| `_is_address()` guard on init                | Validates addresses against `r"0x[0-9a-fA-F]{40}"` before instantiating contracts — gracefully handles unconfigured `.env` without raising at startup.                                                                                                                                                                                                          |
| `validate_settings()` at startup             | Called in `lifespan()` before the orchestrator starts. On non-localhost chains, any missing or malformed private key causes `sys.exit(1)` with a precise error message. On localhost the check is skipped — `_load_local_deployment()` fills keys from `somnia-local.json`. No usable PK defaults exist in `config.py`; the `0x000...000x` placeholder keys were removed to prevent accidental testnet use. |
| `asyncio.Lock` per wallet                    | Concurrent startup triggers (1s stagger) could cause nonce conflicts; per-wallet lock prevents dropped txs.                                                                                                                                                                                                                                                     |
| GBM price, not a real feed                   | Demo needs controllable events (whale buy, crash) — a real feed can't be scripted. Replaced by on-chain prices once fills start arriving.                                                                                                                                                                                                                       |
| Hardcoded 6 gwei gas                         | `eth_gasPrice` RPC returns unreliable values on Somnia testnet; hardcoding avoids tx failures.                                                                                                                                                                                                                                                                  |
| 30s receipt timeout (not infinite)           | A stuck startup trigger should never block the orchestrator — log and continue.                                                                                                                                                                                                                                                                                 |
| Agents stagger 1s at startup                 | Spreads the burst of `triggerAgentDecision()` transactions to avoid nonce collisions during the initial on-chain kickoff.                                                                                                                                                                                                                                       |
| `_order_to_agent` dict for attribution       | `AgentCoordinator` is `msg.sender` for all `Exchange.placeOrder()` calls — individual agent wallets never appear in `OrderPlaced`. `DecisionExecuted` carries both `agentId` and `orderId`, so the backend builds a `{order_id → agent_id}` map from these events and uses it as a fallback in `_trade_event_poll_loop` when the wallet lookup returns nothing. |
| `get_decision_executed_events` in trade loop | `DecisionExecuted` and `TradeExecuted` can fire in the same block (order auto-matches on placement). The 5s metrics loop might not have processed `DecisionExecuted` yet when the 1s trade loop tries to attribute a trade. Polling `DecisionExecuted` at the top of each 1s iteration keeps `_order_to_agent` current.                                         |
| sETH balance from coordinator                | On-chain agents hold no sETH in their own wallets — the coordinator holds a shared 10M pool. `_collect_chain_metrics` polls `AgentToken.balanceOf(coordinator_address)` and assigns the coordinator's balance to all 4 on-chain agents. Only `noise_trader` gets its own wallet balance.                                                                         |
| Wallet signature auth (admin_auth)           | Admin endpoints (pause/resume/fund) require a `personal_sign` MetaMask signature with a timestamped message. The deployer address is derived server-side from `DEPLOYER_PRIVATE_KEY` — never stored in env as a config value — and the signature is verified on every request. 5-minute window prevents replay.                                                 |
