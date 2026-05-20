# Agentic Exchange

> Autonomous AI agents trading onchain on Somnia — in real-time.

![Somnia Chain 50312](https://img.shields.io/badge/Somnia-Chain%2050312-6366f1?style=flat-square)
![Claude claude-sonnet-4-6](https://img.shields.io/badge/Claude-claude--sonnet--4--6-orange?style=flat-square)
![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square)
![Next.js 14](https://img.shields.io/badge/Next.js-14-black?style=flat-square)
![Hackathon](https://img.shields.io/badge/Somnia-Hackathon-22c55e?style=flat-square)

**The demo answers one question:** Why does Somnia need to exist?  
**Because autonomous AI agents need real-time onchain execution.** Traditional chains are too slow — 12-15s block times mean an agent loop takes 30+ seconds per decision. Somnia's sub-second finality makes 8-second autonomous loops possible.

---

## What It Is

Four AI agents (powered by Claude claude-sonnet-4-6) autonomously trade on the Somnia blockchain (chain 50312). Every decision is made by Claude, every trade is recorded permanently onchain. A live dashboard shows visible reasoning, real-time charts, event injection, and agent-to-agent coordination.

---

## How It Works

Each agent runs a continuous **LangGraph** state machine:

```
observe → reason → decide → execute → broadcast
   ↑___________________________________________↑
              (loops every ~8 seconds)
```

| Node | What it does |
|------|-------------|
| **observe** | Reads price, order book, trend, volatility, and any warnings from Risk Manager via `MarketStateBus` |
| **reason** | Sends market context to Claude claude-sonnet-4-6 with a strategy-specific system prompt. Claude returns a JSON decision block. |
| **decide** | Parses Claude's JSON. Validates against risk limits. Falls back to `hold` if parse fails. |
| **execute** | Submits onchain tx to `Exchange.sol` (`placeOrder` / `cancelOrder`). Skips gracefully if testnet is unreachable. |
| **broadcast** | Sends `agent_update` WebSocket message to dashboard. Risk Manager additionally writes warnings to the shared state bus. |

All 4 agents run the same graph — differentiated only by their strategy system prompt in `backend/graph/nodes.py`.

---

## Agents

| Agent | Name | Strategy | Triggers |
|-------|------|----------|----------|
| 🏦 Market Maker | MM-Prime | Places bid/ask, captures spread | Widens spread when volatility > 3% or Risk warning received |
| 📈 Momentum Trader | Momentum-Alpha | Enters long/short on breakouts | 5-bar consecutive UP/DOWN trend → enter position |
| 🔍 Arbitrage Agent | Arb-Scanner | Exploits pricing gaps | Bid-ask spread > 0.5% with no active orders → place order at midpoint |
| 🛡️ Risk Manager | Risk-Shield | Monitors exposure, coordinates agents | Position > 40% of treasury → broadcasts reduce-size warning to all agents |

**Agent coordination:** Risk-Shield writes warnings to a shared `MarketStateBus`. Every other agent reads these warnings in their `observe` step and passes them to Claude as context. This is the agent-to-agent communication layer.

---

## Tech Stack

- **Frontend**: Next.js 14 + Tailwind CSS + TradingView Lightweight Charts v5 + Zustand
- **Backend**: Python FastAPI + WebSockets + LangGraph + Anthropic SDK
- **Contracts**: Solidity (Exchange, AgentRegistry, Treasury) on Somnia testnet
- **AI**: Claude claude-sonnet-4-6 (400 tokens per reasoning step, strategy system prompts)

---

## System Architecture

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

## Quick Start

### Prerequisites

- Node.js 18+, Python 3.12+
- Anthropic API key
- 5 Somnia testnet wallets (funded via faucet) — see [Activating Onchain Mode](#activating-onchain-mode) below

### 1. Clone and install

```bash
git clone <repo>
cd somnia_hackathon

# Backend
cd backend && pip install -r requirements.txt && cd ..

# Frontend
cd frontend && npm install && cd ..

# Contracts (only needed for onchain mode)
cd contracts && npm install && cd ..
```

### 2. Configure backend

```bash
cd backend
cp .env.example .env
# Edit .env — minimum required:
#   ANTHROPIC_API_KEY=sk-ant-...
#
# For onchain mode, also fill wallet PKs and contract addresses (see below)
```

### 3. Start everything

```bash
./start.sh
```

Opens backend at `http://localhost:8000` and frontend at `http://localhost:3000`.

> The dashboard works immediately in simulation mode — agents reason with Claude and fake tx hashes are generated. No wallet setup required.

---

## Activating Onchain Mode

By default the system runs in **simulation mode** (fake tx hashes). To enable real Somnia onchain transactions:

### Step 1 — Generate 5 wallets

Run from `contracts/` (ethers is already installed):

```bash
node -e "
const {ethers} = require('ethers');
const labels = ['DEPLOYER','MARKET_MAKER','MOMENTUM_TRADER','ARBITRAGE_AGENT','RISK_MANAGER'];
for (let i = 0; i < 5; i++) {
  const w = ethers.Wallet.createRandom();
  console.log(labels[i] + '_PK=' + w.privateKey);
  console.log(labels[i] + '_ADDR=' + w.address);
  console.log('');
}
"
```

Save the output — you'll need all 5 private keys.

### Step 2 — Fund wallets via Somnia faucet

Visit **https://testnet.somnia.network/** and request STT for each of the 5 wallet addresses. Each wallet needs at least 0.5 STT (deployer needs ~1 STT for contract deployment).

### Step 3 — Configure contracts and deploy

```bash
cd contracts
cp .env.example .env
# Fill DEPLOYER_PRIVATE_KEY in contracts/.env

npx hardhat run scripts/deploy.js --network somnia
# Prints contract addresses and the exact env vars to copy
```

### Step 4 — Register agents and fund treasuries

```bash
# Fill the 4 agent PKs in contracts/.env first
npx hardhat run scripts/seed.js --network somnia
# Registers agents in AgentRegistry, deposits 0.1 STT each in Treasury
```

### Step 5 — Configure backend and restart

Copy the printed env vars from deploy.js into `backend/.env`:
```
EXCHANGE_ADDRESS=0x...
AGENT_REGISTRY_ADDRESS=0x...
TREASURY_ADDRESS=0x...
MARKET_MAKER_PK=0x...
MOMENTUM_TRADER_PK=0x...
ARBITRAGE_AGENT_PK=0x...
RISK_MANAGER_PK=0x...
```

Remove or comment out `SIMULATION_MODE=true` if it was set, then restart:
```bash
./start.sh
```

Verify at the Somnia explorer: **https://shannon-explorer.somnia.network**

---

## Demo Events

Click the event injection buttons to watch agents react in real-time:

| Button | Effect | What to watch |
|--------|--------|--------------|
| WHALE BUY +3% | Instant +3% price shock | Momentum Trader enters long; Risk Manager monitors exposure |
| WHALE SELL -3% | Instant -3% price shock | Momentum Trader enters short; MM widens spread |
| VOL SPIKE | 5× volatility for 30 seconds | MM-Prime widens spread; all agents reduce position sizes |
| NEWS EVENT | 3× volatility + 1.5% upside | Mixed agent reactions — some buy, Risk Manager monitors |
| FLASH CRASH | -8% price shock + 8× volatility | Risk Manager broadcasts high-severity warning; all agents scramble |

---

## Project Structure

```
somnia_hackathon/
├── contracts/              # Hardhat + Solidity
│   ├── contracts/
│   │   ├── Exchange.sol        # placeOrder / cancelOrder / executeTrade
│   │   ├── AgentRegistry.sol   # agent registration + reputation
│   │   └── Treasury.sol        # per-agent balances
│   ├── scripts/
│   │   ├── deploy.js           # deploys all 3 contracts, writes addresses
│   │   └── seed.js             # registers agents, funds treasuries
│   └── deployments/
│       └── somnia-testnet.json # contract addresses + ABIs (auto-generated)
├── backend/                # Python FastAPI + LangGraph
│   ├── agents/
│   │   ├── base_agent.py       # shared LangGraph runner (all 4 agents use this)
│   │   └── orchestrator.py     # AGENT_CONFIGS, startup, event injection
│   ├── graph/
│   │   ├── state.py            # AgentState TypedDict
│   │   ├── nodes.py            # 5 node functions — SYSTEM_PROMPTS defined here
│   │   └── builder.py          # build_agent_graph() → CompiledGraph
│   ├── market/
│   │   ├── state_bus.py        # async-safe shared state, agent warnings
│   │   └── price_engine.py     # GBM price simulation + OHLCV builder
│   ├── blockchain/
│   │   ├── client.py           # Web3 singleton, per-wallet nonce Lock
│   │   └── contracts.py        # typed contract wrappers
│   └── api/
│       ├── websocket_hub.py    # ConnectionManager: broadcast to all clients
│       ├── routes_ws.py        # /ws WebSocket endpoint
│       └── routes_http.py      # GET /health, GET /agents, POST /events/inject
└── frontend/               # Next.js 14
    ├── components/
    │   ├── chart/              # CandlestickChart (TradingView v5), OrderBook
    │   └── agents/             # AgentGrid, AgentCard, ReasoningPanel, StatusBadge
    ├── store/                  # Zustand: marketStore, agentStore, feedStore
    └── hooks/
        └── useWebSocket.ts     # WS connect/reconnect + message dispatch
```

**To change agent behavior:** edit `SYSTEM_PROMPTS` in `backend/graph/nodes.py`.  
**To add/remove agents:** edit `AGENT_CONFIGS` in `backend/agents/orchestrator.py`.

---

## Simulation Mode

Set `SIMULATION_MODE=true` in `backend/.env` to skip real blockchain transactions — fake tx hashes are generated instead. The dashboard looks identical and all Claude reasoning still runs. Use this as a fallback if Somnia testnet is unreachable or wallets aren't set up yet.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Chart blank on load | Backend not running or WS URL wrong | Check `NEXT_PUBLIC_WS_URL` in `frontend/.env.local`; verify backend is up at `http://localhost:8000/health` |
| Agent cards show IDLE forever | `ANTHROPIC_API_KEY` not set | Fill `ANTHROPIC_API_KEY` in `backend/.env` and restart |
| No tx hashes visible | Onchain mode not activated | Either set `SIMULATION_MODE=true` or complete the 5-step onchain setup above |
| `deploy.js` fails | Placeholder PK or insufficient STT | Verify `DEPLOYER_PRIVATE_KEY` is a real key with STT balance |
| Agent reasoning repeats "hold" | Claude rate limit hit | Agents stagger 2s apart; check Anthropic dashboard for rate limit status |
| Frontend WS disconnect loop | Backend crash | Check backend logs via `tmux attach -t agentic-exchange` |

---

## Somnia Network

| | |
|-|-|
| **Chain** | Somnia Testnet |
| **Chain ID** | 50312 |
| **RPC** | https://dream-rpc.somnia.network |
| **Explorer** | https://shannon-explorer.somnia.network |
| **Faucet** | https://testnet.somnia.network/ |

> Gas price is hardcoded at **6 gwei** throughout the codebase. Do not use dynamic gas estimation — it causes tx failures on Somnia testnet.

---

## Docs

- [Architecture](docs/ARCHITECTURE.md) — system design, data flow, component internals
- [Demo Script](docs/DEMO_SCRIPT.md) — 5-minute judge walkthrough with talking points
- [Backend](docs/BACKEND.md) — FastAPI + LangGraph internals, config reference, agent tuning
- [Frontend](docs/FRONTEND.md) — Next.js components, Zustand stores, WS dispatch, TradingView notes
- [Contracts](docs/CONTRACTS.md) — Solidity reference, deployment walkthrough, script docs
