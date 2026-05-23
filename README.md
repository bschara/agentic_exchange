# Agentic Exchange

> Autonomous AI agents trading onchain on Somnia — in real-time.

![Somnia Chain 50312](https://img.shields.io/badge/Somnia-Chain%2050312-6366f1?style=flat-square)
![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square)
![Next.js 14](https://img.shields.io/badge/Next.js-14-black?style=flat-square)
![Hackathon](https://img.shields.io/badge/Somnia-Hackathon-22c55e?style=flat-square)

**The demo answers one question:** Why does Somnia need to exist?  
**Because autonomous AI agents need real-time onchain execution — and Somnia-native AI.** Traditional chains are too slow for agent decision loops. And no other chain lets AI decisions themselves be validated by a decentralized network. Somnia delivers both: sub-second finality and native on-chain LLM consensus via the Somnia Agent platform.

---

## What It Is

Five AI agents autonomously trade on the Somnia blockchain (chain 50312). Every trading decision is validated by Somnia's decentralized LLM inference agent — not an off-chain bot. Every order is matched by a real on-chain limit order book. A live dashboard shows visible decision flow, real-time charts, a full-width latency comparison panel, event injection, and live on-chain metrics.

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

**On-chain metrics:** The backend polls coordinator events every 5s — `DecisionExecuted`, `DecisionFailed`, `LLMRequestFired`, `LoopStopped` — and reads live contract state (order book depth, coordinator STT balance, per-agent treasury balances, net positions). These are broadcast as `chain_metrics` WebSocket messages and available at `GET /chain-metrics`.

---

## Tech Stack

- **Frontend**: Next.js 14 + Tailwind CSS + TradingView Lightweight Charts v5 + Zustand
- **Backend**: Python FastAPI + WebSockets (no off-chain AI — all decisions are on-chain)
- **Contracts**: Solidity (Exchange LOB, AgentCoordinator, AgentRegistry, Treasury) on Somnia testnet
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
│                                │  _retrigger() → self-loop       │    │
│                                └────────────────┬──────────────┘    │
│  ┌──────────────────────────────────────         │ platform fires   │
│  │  Somnia LLM Inference Agent                   │                  │
│  │  inferString(ctx, systemPrompt,               │                  │
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
│  │  noise_trader_loop (4-6s) → random orders directly to Exchange│  │
│  └───────────────────────────────────────────────────────────────┘  │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ WebSocket  ws://localhost:8000/ws
┌──────────────────────────────▼───────────────────────────────────────┐
│                    Next.js Dashboard                                  │
│  LatencyHero (full-width: Somnia vs Solana vs Ethereum latency)      │
│  CandlestickChart · OrderBook · AgentCards (5) · Scoreboard · Feed   │
│  Agent cards: strategy desc, net position (LONG/SHORT/FLAT), P&L     │
│  ActivityFeed: tx hashes link to shannon-explorer.somnia.network     │
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

Smoke-test the contracts (optional, before starting the backend):

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
```

### Step 5 — Configure backend and restart

Copy the printed env vars from deploy.js into `backend/.env`:

```
EXCHANGE_ADDRESS=0x...
AGENT_REGISTRY_ADDRESS=0x...
TREASURY_ADDRESS=0x...
AGENT_COORDINATOR_ADDRESS=0x...
MARKET_MAKER_PK=0x...
MOMENTUM_TRADER_PK=0x...
ARBITRAGE_AGENT_PK=0x...
RISK_MANAGER_PK=0x...
NOISE_TRADER_PK=0x...
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
│   │   ├── Exchange.sol         # real on-chain LOB: placeOrder → _matchOrder → TradeExecuted
│   │   │                        # getOrdersByAgent() view for per-agent active order IDs
│   │   ├── AgentCoordinator.sol # IAgentRequester integration — 4 agents Somnia-native
│   │   │                        # lastOrderId mapping: cancel-before-place, MM dual-sided
│   │   ├── AgentRegistry.sol    # agent registration + reputation
│   │   ├── Treasury.sol         # per-agent balances
│   │   └── MockPlatform.sol     # local dev: simulates Somnia platform callbacks
│   ├── scripts/
│   │   ├── deploy.js            # testnet: deploys all contracts, sets on-chain prompts (5 agents)
│   │   ├── seed.js              # testnet: registers agents, funds treasuries
│   │   ├── deploy-local.js      # local: deploys to Hardhat, writes somnia-local.json (6 signers)
│   │   ├── platform-daemon.js   # local: listens for MockPlatform events, fires price + LLM callbacks
│   │   └── test-local.js        # local: one-shot smoke test for the full decision cycle
│   └── deployments/
│       ├── somnia-testnet.json  # testnet addresses + ABIs (auto-generated by deploy.js)
│       └── somnia-local.json    # local addresses + ABIs + agent PKs (auto-generated by deploy-local.js)
├── backend/                # Python FastAPI
│   ├── agents/
│   │   └── orchestrator.py      # AGENT_CONFIGS (5 agents), startup triggers, poll loops, metrics,
│   │                            # _noise_trader_loop(), _load_local_deployment()
│   ├── market/
│   │   ├── state_bus.py         # async-safe shared state
│   │   └── price_engine.py      # GBM price simulation + OHLCV builder
│   ├── blockchain/
│   │   ├── client.py            # Web3 singleton, per-wallet nonce Lock
│   │   └── contracts.py         # typed wrappers: ExchangeContract, TreasuryContract, AgentCoordinatorContract
│   └── api/
│       ├── websocket_hub.py     # ConnectionManager: broadcast to all clients
│       ├── routes_ws.py         # /ws WebSocket endpoint
│       └── routes_http.py       # REST endpoints
└── frontend/               # Next.js 14
    ├── components/
    │   ├── layout/
    │   │   ├── LatencyHero.tsx  # full-width latency comparison: Somnia vs Solana vs Ethereum
    │   │   └── ActivityFeed.tsx # activity feed with explorer tx hash links
    │   ├── chart/               # CandlestickChart (TradingView v5), OrderBook, RecentTrades
    │   └── agents/              # AgentGrid (5 agents), AgentCard (strategy desc + position),
    │                            # AgentScoreboard (total P&L incl unrealized), ReasoningPanel, StatusBadge
    ├── store/                   # Zustand: marketStore, agentStore, feedStore
    └── hooks/
        └── useWebSocket.ts      # WS connect/reconnect + message dispatch
```

**To change agent behavior:** update `setSystemPrompt` calls in `contracts/scripts/deploy.js` (testnet) or `deploy-local.js` (local) and redeploy.  
**To add/remove agents:** edit `AGENT_CONFIGS` in `backend/agents/orchestrator.py`.

---

## Troubleshooting

| Symptom                                          | Cause                                        | Fix                                                                                                          |
| ------------------------------------------------ | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Chart blank on load                              | Backend not running or WS URL wrong          | Check `NEXT_PUBLIC_WS_URL` in `frontend/.env.local`; verify backend at `http://localhost:8000/health`        |
| No tx hashes visible                             | Contracts not deployed                       | Complete the deployment steps above                                                                          |
| `deploy.js` / `deploy-local.js` fails            | Placeholder PK or insufficient funds         | Verify `DEPLOYER_PRIVATE_KEY` is a real key with STT (testnet) or that `npx hardhat node` is running (local) |
| `start.sh` exits with "Hardhat node not running" | Forgot to start `npx hardhat node`           | Open a terminal, run `cd contracts && npx hardhat node`, then re-run `./start.sh`                            |
| Agent cards show zeros after startup             | Contracts not configured or still warming up | Wait 10s for first coordinator poll; check `/debug/config` endpoint to confirm addresses loaded              |
| `/chain-metrics` returns all zeros               | `AGENT_COORDINATOR_ADDRESS` not set          | Check `backend/.env` — if using local dev, `somnia-local.json` auto-loads addresses                          |
| `LoopStopped` events in chain-metrics            | Coordinator ran out of STT                   | Call `AgentCoordinator.fund()` with more STT; then POST to `/agents/trigger` to restart loops                |
| platform-daemon not started                      | Running without tmux or manually             | Run `cd contracts && node scripts/platform-daemon.js` in a separate terminal                                 |
| Frontend WS disconnect loop                      | Backend crash                                | Check backend logs via `tmux attach -t agentic-exchange`                                                     |
| Noise trader not placing orders                  | `NOISE_TRADER_PK` not set in `.env`          | Add `NOISE_TRADER_PK=0x...` to `backend/.env`; for local dev it auto-loads from `somnia-local.json`          |
| Order book filling with stale orders             | Old coordinator without cancel-before-place  | Recompile and redeploy contracts after pulling latest `AgentCoordinator.sol`                                 |

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
