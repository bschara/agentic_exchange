# Agentic Exchange

> Autonomous AI agents trading onchain on Somnia — in real-time.

![Somnia Chain 50312](https://img.shields.io/badge/Somnia-Chain%2050312-6366f1?style=flat-square)
![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square)
![Next.js 14](https://img.shields.io/badge/Next.js-14-black?style=flat-square)
![Hackathon](https://img.shields.io/badge/Somnia-Hackathon-22c55e?style=flat-square)

**The demo answers one question:** Why does Somnia need to exist?  
**Because autonomous AI agents need real-time onchain execution — and Somnia-native AI.** Traditional chains are too slow for agent decision loops. And no other chain lets AI decisions themselves be validated by a decentralized network. Somnia delivers both: sub-second finality and native on-chain LLM consensus via the Somnia Agent platform.

Three features make this more than a trading demo: agents **read each other's decisions** before making their own (every LLM prompt includes live peer signals from the previous cycle), **consecutive wins scale order size** automatically (a 10-win streak trades at 3× base without any Python intervention), and when three agents reach unanimous consensus they fire an on-chain **coalition order at 3× normal size** — autonomous coordination between AI agents, entirely on-chain.

---

## What It Is

Five AI agents autonomously trade on the Somnia blockchain (chain 50312). Every trading decision is validated by Somnia's decentralized LLM inference agent — not an off-chain bot. Every order is matched by a real on-chain limit order book. A live dashboard shows visible decision flow, real-time charts, a full-width latency comparison panel, event injection, and live on-chain metrics.

Agents are not isolated. Before each decision, every agent's LLM prompt includes the previous cycle's decisions from all other agents (`"Peers: momentum_trader=BUY, risk_manager=SELL"`). Win streaks drive adaptive sizing. Three-agent consensus triggers coalition orders. All of this is verifiable on the Somnia explorer — every `LLMRequestFired` event carries the full prompt on-chain.

---

## How It Works

On startup, the orchestrator fires one `triggerAgentDecision()` per agent — that's the only Python transaction ever sent. From that point the `AgentCoordinator` self-loops forever: `handleDecision()` calls `_retrigger()` at the end of every cycle. Python never touches the contracts again.

Three background loops keep the dashboard live:

- **Trade event poll** (1s) — reads `TradeExecuted` events → drives the price chart
- **Snapshot broadcast** (2s) — pushes market state to WebSocket clients
- **Contract metrics poll** (5s) — reads coordinator events and contract state → emits `chain_metrics`

---

## Agents

| Agent              | Name           | Strategy                                    | How it works                                                                     |
| ------------------ | -------------- | ------------------------------------------- | -------------------------------------------------------------------------------- |
| ⚖️ Market Maker    | MM-Prime       | Dual-sided quoting, captures spread         | Places **both** a bid and an ask each cycle; cancels stale orders before placing |
| 📈 Momentum Trader | Momentum-Alpha | Rides trends, enters long/short on momentum | Buys into upward momentum (on-chain ≥ reference), sells into downward            |
| 🔍 Arbitrage Agent | Arb-Scanner    | Exploits reference vs on-chain price gap    | Buys when on-chain is underpriced vs CoinGecko, sells when overpriced            |
| 🛡️ Risk Manager    | Risk-Shield    | Stabilises extremes, provides liquidity     | Buys when on-chain is >$5 below reference; sells when >$5 above                  |
| 🎲 Noise Bot       | Noise-Bot      | Random order flow, keeps book alive         | Python-only loop placing random orders every 4–6 s (no LLM overhead)             |

**4 agents are Somnia-native** when deployed (market_maker, momentum_trader, arbitrage_agent, risk_manager): on startup the orchestrator fires one `triggerAgentDecision()` per agent. From that point the contract is fully self-sustaining — `handleDecision()` calls `_retrigger()` at the end of every cycle. `noise_trader` runs as a pure Python coroutine placing random orders directly via the Exchange contract, keeping the book alive between LLM cycles. If the coordinator runs out of STT, it emits `LoopStopped(agentId, reason, balance)` and halts gracefully.

**Cancel-before-place:** `AgentCoordinator` tracks `lastOrderId` per agent and cancels the previous order before placing a new one, preventing order book bloat. Market Maker places two orders per cycle (bid + ask) at ±0.1% around the reference price.

**Peer signals:** Every agent's LLM prompt is built on-chain in `_buildContext()` and includes the last recorded decision of every other agent. A momentum trader reads `"Peers: market_maker=BUY, arbitrage_agent=SELL, risk_manager=HOLD"` before deciding. The full prompt is emitted in the `context` field of the `LLMRequestFired` event — judges can see the inter-agent communication directly on the Somnia explorer.

**Adaptive order sizing:** Each agent tracks a `winStreak` counter. Every filled order increments it; a HOLD or failed order resets it to zero. Order size scales by `1 + streak / 5` (capped at 5× base), computed entirely on-chain by `_orderAmount()`.

**Coalition orders:** `AgentCoordinator` tracks `lastDecision` for every agent. After each decision is recorded, `_coalitionCount()` checks how many directional agents share the same decision. When exactly 3 agree, `_fireCoalitionOrder()` places a single coordinated order at 3× base size, emitting `CoalitionFormed(direction, agentCount, price, orderId)`. Fires once per convergence event; no Python trigger needed.

**On-chain metrics:** The backend polls coordinator events every 5s — `DecisionExecuted` (now includes `streak`), `LLMRequestFired` (now includes full `context`), `CoalitionFormed`, `DecisionFailed`, `LoopStopped` — and reads live contract state (order book depth, coordinator STT balance, per-agent treasury balances, net positions). Coalition events are broadcast immediately as `coalition_alert` WebSocket messages in addition to the regular `chain_metrics` feed.

---

## Tech Stack

- **Frontend**: Next.js 14 + Tailwind CSS + TradingView Lightweight Charts v5 + Zustand
- **Backend**: Python FastAPI + WebSockets (no off-chain AI — all decisions are on-chain)
- **Contracts**: Solidity (AgentToken ERC20, Exchange LOB, AgentCoordinator, AgentRegistry, Treasury) on Somnia testnet
- **Onchain AI**: Somnia LLM Inference Agent via `IAgentRequester` — BUY/SELL/HOLD consensus from Somnia validators

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Somnia Blockchain (chain 50312)                    │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Exchange.sol  (real on-chain LOB with matching engine)      │    │
│  │  placeOrder() → _matchOrder() → TradeExecuted(price,amount) │    │
│  │  cancelOrder() · getOrdersByAgent() · getBestBid/Ask()      │    │
│  └─────────────────────┬───────────────────────┬──────────────┘    │
│                         │ placeOrder (callback)  │ events polled     │
│  ┌──────────────────────┴──┐  ┌────────────────┴──────────────┐    │
│  │ AgentRegistry · Treasury│  │  AgentCoordinator.sol          │    │
│  └─────────────────────────┘  │  triggerAgentDecision() ×1/agent│   │
│                                │  cancel lastOrderId → placeOrder│   │
│                                │  MM: dual bid+ask per cycle     │    │
│                                │  lastDecision[agentId] for peers│   │
│                                │  winStreak → _orderAmount()    │    │
│                                │  _coalitionCount() == 3 →      │    │
│                                │    CoalitionFormed 3× order     │    │
│                                │  _retrigger() → self-loop       │    │
│                                └────────────────┬──────────────┘    │
│  ┌──────────────────────────────────────         │ platform fires   │
│  │  Somnia LLM Inference Agent                   │                  │
│  │  inferString(ctx+peers+streak, systemPrompt,  │                  │
│  │    ["BUY","SELL","HOLD"])                      │                  │
│  │  → multi-validator consensus ─────────────────┘                  │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
     ↑ 1 startup tx per agent (6 gwei)  ↑ noise_trader direct orders
┌────────┴─────────────────────────────────────────────────────────────┐
│                         FastAPI Backend                               │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  trade event poll (1s)  ──► PriceEngine ──► MarketStateBus   │  │
│  │  snapshot broadcast (2s) ──────────────────────────────────►  │  │
│  │  contract metrics poll (5s) ──► chain_metrics + risk_warning  │  │
│  │    extracts: context (LLMRequestFired), streak (DecisionExecuted)│ │
│  │    broadcasts: coalition_alert on CoalitionFormed             │  │
│  │  noise_trader_loop (4-6s) → random orders directly to Exchange│  │
│  └───────────────────────────────────────────────────────────────┘  │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ WebSocket  ws://localhost:8000/ws
┌──────────────────────────────▼───────────────────────────────────────┐
│                    Next.js Dashboard                                  │
│  LatencyHero (full-width: Somnia vs Solana vs Ethereum latency)      │
│  CandlestickChart · OrderBook · AgentCards (5) · Scoreboard · Feed   │
│  Agent cards: strategy desc, 🔥 streak badge, position badge, P&L   │
│  ReasoningPanel: live LLM prompt (peers + streak) per agent          │
│  ActivityFeed: coalition alerts in orange + tx hash links            │
│  Zustand: marketStore · agentStore · feedStore                       │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Option A — Local Hardhat (no testnet wallet needed)

```bash
git clone <repo>
cd somnia_hackathon

# Install deps
cd backend && pip install -r requirements.txt && cd ..
cd frontend && npm install && cd ..
cd contracts && npm install && cd ..
```

Terminal 1 — start a local Hardhat node:

```bash
cd contracts && npx hardhat node
```

Terminal 2 — deploy contracts and write `somnia-local.json`:

```bash
cd contracts && npx hardhat run scripts/deploy-local.js --network localhost
# Prints env vars — copy them into backend/.env
```

Terminal 3 — start everything (backend + frontend + platform daemon):

```bash
./start.sh
```

`start.sh` auto-detects `SOMNIA_RPC_URL=http://127.0.0.1:8545` in `backend/.env` and starts the `platform-daemon.js` in a third tmux pane alongside the backend and frontend.

Run the contract test suite (optional, Hardhat node must be running):

```bash
cd contracts && npx hardhat test
```

Smoke-test the full decision cycle end-to-end (optional, after contracts are deployed):

```bash
cd contracts && npx hardhat run scripts/test-local.js --network localhost
```

### Option B — Somnia Testnet

Prerequisites: Node.js 18+, Python 3.12+, 6 funded Somnia testnet wallets (1 deployer + 5 agents) — see [Deploying Onchain](#deploying-onchain).

```bash
git clone <repo>
cd somnia_hackathon
cd backend && pip install -r requirements.txt && cd ..
cd frontend && npm install && cd ..
cd contracts && npm install && cd ..
cd backend && cp .env.example .env
# Fill wallet private keys and contract addresses — see Deploying Onchain below
./start.sh
```

Opens backend at `http://localhost:8000` and frontend at `http://localhost:3000`.

---

## Deploying Onchain

### Step 1 — Generate 6 wallets

Run from `contracts/` (ethers is already installed):

```bash
node -e "
const {ethers} = require('ethers');
const labels = ['DEPLOYER','MARKET_MAKER','MOMENTUM_TRADER','ARBITRAGE_AGENT','RISK_MANAGER','NOISE_TRADER'];
for (let i = 0; i < 6; i++) {
  const w = ethers.Wallet.createRandom();
  console.log(labels[i] + '_PK=' + w.privateKey);
  console.log(labels[i] + '_ADDR=' + w.address);
  console.log('');
}
"
```

Save the output — you'll need all 6 private keys.

### Step 2 — Fund wallets via Somnia faucet

Visit **https://testnet.somnia.network/** and request STT for each of the 6 wallet addresses. Each wallet needs at least 0.5 STT (deployer needs ~1 STT for contract deployment).

### Step 3 — Configure contracts and deploy

```bash
cd contracts
cp .env.example .env
# Fill DEPLOYER_PRIVATE_KEY in contracts/.env

npx hardhat run scripts/deploy.js --network somnia
# Deploys Exchange, AgentRegistry, Treasury, AgentCoordinator
# Sets per-agent system prompts on-chain for all 5 agents
# Funds AgentCoordinator with 0.2 STT for LLM request deposits
# Prints the exact env vars to copy
```

### Step 4 — Register agents and fund treasuries

```bash
# Fill the 5 agent PKs in contracts/.env first
npx hardhat run scripts/seed.js --network somnia
# Registers agents in AgentRegistry, deposits 0.1 STT each in Treasury
# Sends 0.05 STT gas to each agent wallet (skips if already funded)
# Mints 1M AGT to each agent wallet and approves Exchange
```

### Step 5 — Configure backend and restart

Copy the printed env vars from deploy.js into `backend/.env`. `AGENT_TOKEN_ADDRESS` and all other contract addresses are **auto-loaded from `somnia-testnet.json`** if you leave them as placeholders — you only need the wallet keys and RPC settings:

```
SOMNIA_RPC_URL=https://dream-rpc.somnia.network
SOMNIA_CHAIN_ID=50312
SOMNIA_BLOCK_MS=400
DEPLOYER_PRIVATE_KEY=0x...
MARKET_MAKER_PK=0x...
MOMENTUM_TRADER_PK=0x...
ARBITRAGE_AGENT_PK=0x...
RISK_MANAGER_PK=0x...
NOISE_TRADER_PK=0x...
```

### Step 6 — Configure frontend

Set the deployer's public address in `frontend/.env.local` (required to show admin controls):

```
NEXT_PUBLIC_DEPLOYER_ADDRESS=0xYourDeployerAddress
```

Then restart:

```bash
./start.sh
```

Verify at the Somnia explorer: **https://shannon-explorer.somnia.network**

---

## Demo Events

Click the event injection buttons to watch agents react in real-time:

| Button         | Effect                          | What to watch                                                      |
| -------------- | ------------------------------- | ------------------------------------------------------------------ |
| WHALE BUY +3%  | Instant +3% price shock         | Momentum Trader enters long; Risk Manager monitors exposure        |
| WHALE SELL -3% | Instant -3% price shock         | Momentum Trader enters short; MM widens spread                     |
| VOL SPIKE      | 5× volatility for 30 seconds    | MM-Prime widens spread; all agents reduce position sizes           |
| NEWS EVENT     | 3× volatility + 1.5% upside     | Mixed agent reactions — some buy, Risk Manager monitors            |
| FLASH CRASH    | -8% price shock + 8× volatility | Risk Manager broadcasts high-severity warning; all agents scramble |

---

## Project Structure

```
somnia_hackathon/
├── contracts/              # Hardhat + Solidity
│   ├── contracts/
│   │   ├── AgentToken.sol       # mintable ERC20 (AGT): owner-mint, unlimited supply, no OZ dependency
│   │   ├── Exchange.sol         # real on-chain LOB: placeOrder → _matchOrder → TradeExecuted
│   │   │                        # SELL orders lock AGT via transferFrom; fills settle to buyer; cancels refund
│   │   ├── AgentCoordinator.sol # IAgentRequester integration — 4 agents Somnia-native
│   │   │                        # lastOrderId: cancel-before-place; MM dual-sided quoting
│   │   │                        # lastDecision: peer signals in every LLM prompt
│   │   │                        # winStreak: adaptive order sizing (1+streak/5, cap 5×)
│   │   │                        # _coalitionCount: CoalitionFormed when 3 agents agree
│   │   │                        # approveToken(): grants Exchange spending allowance
│   │   │                        # pauseAgent()/resumeAgent(): owner pause/resume per agent
│   │   ├── AgentRegistry.sol    # agent registration + reputation + setActive()
│   │   ├── Treasury.sol         # per-agent balances
│   │   └── MockPlatform.sol     # local dev: simulates Somnia platform callbacks
│   ├── scripts/
│   │   ├── deploy.js            # testnet: deploys all contracts, sets on-chain prompts (5 agents)
│   │   ├── seed.js              # testnet: registers agents, funds treasuries, mints AGT
│   │   ├── deploy-local.js      # local: deploys to Hardhat, writes somnia-local.json (6 signers)
│   │   ├── platform-daemon.js   # local: listens for MockPlatform events, fires price + LLM callbacks
│   │   ├── test-local.js        # local: one-shot smoke test for the full decision cycle
│   │   └── verify.js            # testnet: verifies contracts on Somnia explorer
│   ├── test/
│   │   ├── Exchange.test.cjs          # LOB: order placement, matching engine, fills, cancellation
│   │   ├── AgentCoordinator.test.cjs  # full 3-tx pipeline, coalition detection, win streaks, peer signals, LoopStopped
│   │   ├── AgentRegistry.test.cjs     # agent registration, reputation updates
│   │   └── Treasury.test.cjs          # deposit, withdraw, allocate, getBalance
│   └── deployments/
│       └── somnia-local.json    # local addresses + ABIs + agent PKs (auto-generated by deploy-local.js)
│                                # somnia-testnet.json written here by deploy.js after testnet deploy
├── backend/                # Python FastAPI
│   ├── main.py                  # FastAPI app entry point, lifespan, router registration
│   ├── config.py                # Pydantic Settings: loads .env, validates addresses + PKs
│   ├── agents/
│   │   └── orchestrator.py      # AGENT_CONFIGS (5 agents), startup triggers, poll loops, metrics,
│   │                            # _noise_trader_loop(), _load_local_deployment()
│   ├── market/
│   │   ├── state_bus.py         # async-safe shared state (price, order book, events)
│   │   ├── price_engine.py      # GBM price simulation + OHLCV builder
│   │   ├── price_feed.py        # CoinGecko ETH/USD feed (reference price)
│   │   └── order_book.py        # in-memory order book reconstruction from on-chain data
│   ├── blockchain/
│   │   ├── client.py            # Web3 singleton, per-wallet nonce Lock, send_transaction()
│   │   └── contracts.py         # typed wrappers: ExchangeContract, TreasuryContract,
│   │                            # AgentCoordinatorContract, AgentRegistryContract, AgentTokenContract
│   ├── api/
│   │   ├── websocket_hub.py     # ConnectionManager: broadcast to all clients
│   │   ├── routes_ws.py         # /ws WebSocket endpoint
│   │   ├── auth.py              # MetaMask wallet-signature auth (personal_sign + eth_account recovery)
│   │   └── routes_http.py       # REST endpoints (/health, /state, /agents, /chain-metrics,
│   │                            # /events/inject, /agents/{id}/pause, /agents/{id}/resume,
│   │                            # /agents/{id}/fund, /agents/pause-all, /agents/resume-all, /agents/fund-all)
│   └── tests/
│       ├── test_order_book.py   # in-memory order book: placement, matching, cancellation
│       ├── test_price_engine.py # GBM tick, shock, volatility multiplier, OHLCV builder
│       └── test_state_bus.py    # MarketStateBus: concurrent access, snapshot, fills
└── frontend/               # Next.js 14
    ├── app/
    │   ├── page.tsx             # root page — assembles all dashboard panels
    │   ├── layout.tsx           # root layout + font loading
    │   └── providers.tsx        # client-side provider wrapper
    ├── components/
    │   ├── layout/
    │   │   ├── LatencyHero.tsx  # full-width latency comparison: Somnia vs Solana vs Ethereum
    │   │   ├── ActivityFeed.tsx # activity feed with coalition alerts + explorer tx hash links
    │   │   └── Header.tsx       # top nav with connection status
    │   ├── chart/
    │   │   ├── CandlestickChart.tsx  # TradingView Lightweight Charts v5
    │   │   ├── OrderBook.tsx         # live bid/ask depth display
    │   │   └── RecentTrades.tsx      # last 50 fills with agent labels
    │   ├── agents/
    │   │   ├── AgentGrid.tsx         # 5-agent card layout
    │   │   ├── AgentCard.tsx         # strategy desc, streak badge, position, P&L
    │   │   ├── AgentScoreboard.tsx   # ranked by total P&L (realized + unrealized)
    │   │   ├── AgentStatusBadge.tsx  # ACTIVE / WAITING / STOPPED status pill
    │   │   └── ReasoningPanel.tsx    # live LLM prompt (peers + streak) per agent
    │   └── ui/                  # shadcn/ui primitives: badge, button, card, separator
    ├── store/
    │   ├── marketStore.ts       # Zustand: candles, order book, recent trades, current price
    │   ├── agentStore.ts        # Zustand: per-agent state, coordinator balance, coalition alerts
    │   └── feedStore.ts         # Zustand: activity feed ring buffer (max 100)
    ├── hooks/
    │   ├── useWebSocket.ts      # WS connect/reconnect + message dispatch to stores
    │   └── useAdminActions.ts   # wallet connect (MetaMask), sign-and-post for pause/resume/fund
    ├── types/
    │   └── global.d.ts          # EthereumProvider interface + window.ethereum type extension
    └── lib/
        ├── types.ts             # shared TypeScript types (AgentState, Candle, OrderBookLevel, …)
        └── utils.ts             # shadcn cn() helper
```

**To change agent behavior:** update `setSystemPrompt` calls in `contracts/scripts/deploy.js` (testnet) or `deploy-local.js` (local) and redeploy.  
**To add/remove agents:** edit `AGENT_CONFIGS` in `backend/agents/orchestrator.py`.

---

## Troubleshooting

| Symptom                                          | Cause                                            | Fix                                                                                                                                                                                               |
| ------------------------------------------------ | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Chart blank on load                              | Backend not running or WS URL wrong              | Check `NEXT_PUBLIC_WS_URL` in `frontend/.env.local`; verify backend at `http://localhost:8000/health`                                                                                             |
| No tx hashes visible                             | Contracts not deployed                           | Complete the deployment steps above                                                                                                                                                               |
| `deploy.js` / `deploy-local.js` fails            | Placeholder PK or insufficient funds             | Verify `DEPLOYER_PRIVATE_KEY` is a real key with STT (testnet) or that `npx hardhat node` is running (local)                                                                                      |
| `start.sh` exits with "Hardhat node not running" | Forgot to start `npx hardhat node`               | Open a terminal, run `cd contracts && npx hardhat node`, then re-run `./start.sh`                                                                                                                 |
| Agent cards show zeros after startup             | Contracts not configured or still warming up     | Wait 10s for first coordinator poll; check `/debug/config` endpoint to confirm addresses loaded                                                                                                   |
| `/chain-metrics` returns all zeros               | `AGENT_COORDINATOR_ADDRESS` not set              | Check `backend/.env` — if using local dev, `somnia-local.json` auto-loads addresses                                                                                                               |
| `LoopStopped` events in chain-metrics            | Coordinator ran out of STT                       | Call `AgentCoordinator.fund()` with more STT; then POST to `/agents/trigger` to restart loops                                                                                                     |
| platform-daemon not started                      | Running without tmux or manually                 | Run `cd contracts && node scripts/platform-daemon.js` in a separate terminal                                                                                                                      |
| Frontend WS disconnect loop                      | Backend crash                                    | Check backend logs via `tmux attach -t agentic-exchange`                                                                                                                                          |
| Noise trader not placing orders                  | `NOISE_TRADER_PK` not set in `.env`              | Add `NOISE_TRADER_PK=0x...` to `backend/.env`; for local dev it auto-loads from `somnia-local.json`                                                                                               |
| Order book filling with stale orders             | Old coordinator without cancel-before-place      | Recompile and redeploy contracts after pulling latest `AgentCoordinator.sol`                                                                                                                      |
| No coalition alerts in dashboard                 | Fewer than 3 directional agents configured       | market_maker is non-directional; coalition requires 3 of momentum_trader/arbitrage_agent/risk_manager to agree                                                                                    |
| `win_streak` stays 0 in agent cards              | HOLD decisions or failed placeOrder calls        | Normal — streak resets on HOLD; check `DecisionFailed` events via `/chain-metrics`                                                                                                                |
| SELL orders revert with "Token transfer failed"  | Agent wallet has no AGT or Exchange not approved | Run `seed.js` again — it mints AGT and sets approval per wallet; for coordinator call `approveToken()`                                                                                            |
| `seed.js` skips gas funding                      | Agent wallet already above 0.01 STT              | Normal — script skips funding if balance is sufficient                                                                                                                                            |
| Agent cards show zeros after redeploy            | `backend/.env` has stale contract addresses      | Copy addresses printed by `deploy-local.js` into `backend/.env`, or delete the address lines — `_load_local_deployment()` auto-loads from `somnia-local.json` when running against localhost      |
| Noise trader gets "Insufficient balance" reverts | Noise trader wallet has no AGT tokens            | Fixed in current `deploy-local.js` (mints 10k AGT); if on an older deployment run `deploy-local.js` again or mint AGT manually to the noise trader wallet                                         |
| Daemon shows `NONCE_EXPIRED` / "nonce too low"   | Another process used the same deployer key       | Restart the daemon (`Ctrl+C` → `node scripts/platform-daemon.js`) so its `NonceManager` re-fetches the current nonce; ensure no other process signs with the deployer key while daemon is running |
| AGT balance shows 0 for all agents               | On-chain agents hold AGT in the coordinator, not their wallets | Expected — coordinator holds the shared 10M pool. Dashboard now shows coordinator's AGT balance for on-chain agents |
| P&L / orders show 0 for on-chain agents          | AgentCoordinator is `msg.sender` for Exchange, not individual wallets | Fixed — backend now tracks `DecisionExecuted.orderId → agentId` via `_order_to_agent` mapping |
| Admin control buttons (PAUSE ALL etc.) not visible | Deployer wallet not connected or address mismatch | Click CONNECT WALLET in the header; ensure `NEXT_PUBLIC_DEPLOYER_ADDRESS` matches the deployer public key |
| `POST /agents/{id}/pause` returns 403            | Missing or invalid MetaMask signature headers    | Admin endpoints require a `personal_sign` signature; use the dashboard PAUSE/RESUME buttons or sign manually |

---

## Somnia Network

|              |                                         |
| ------------ | --------------------------------------- |
| **Chain**    | Somnia Testnet                          |
| **Chain ID** | 50312                                   |
| **RPC**      | https://dream-rpc.somnia.network        |
| **Explorer** | https://shannon-explorer.somnia.network |
| **Faucet**   | https://testnet.somnia.network/         |

> Gas price is hardcoded at **6 gwei** throughout the codebase. Do not use dynamic gas estimation — it causes tx failures on Somnia testnet.

---

## Docs

- [Architecture](docs/ARCHITECTURE.md) — system design, data flow, component internals
- [Demo Script](docs/DEMO_SCRIPT.md) — 5-minute judge walkthrough with talking points
- [Backend](docs/BACKEND.md) — FastAPI + LangGraph internals, config reference, agent tuning
- [Frontend](docs/FRONTEND.md) — Next.js components, Zustand stores, WS dispatch, TradingView notes
- [Contracts](docs/CONTRACTS.md) — Solidity reference, deployment walkthrough, script docs
