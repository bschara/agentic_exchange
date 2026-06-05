# Agentic Exchange

> Autonomous AI agents trading onchain on Somnia — in real-time.

![Somnia Chain 50312](https://img.shields.io/badge/Somnia-Chain%2050312-6366f1?style=flat-square)
![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square)
![Next.js 14](https://img.shields.io/badge/Next.js-14-black?style=flat-square)
![Hackathon](https://img.shields.io/badge/Somnia-Hackathon-22c55e?style=flat-square)

**The demo answers one question:** Why does Somnia need to exist?  
**Because autonomous AI agents need real-time onchain execution — and Somnia-native AI.** Traditional chains are too slow for agent decision loops. And no other chain lets AI decisions themselves be validated by a decentralized network. Somnia delivers both: sub-second finality and native on-chain LLM consensus via the Somnia Agent platform.

Three features make this more than a trading demo: agents **read each other's decisions** before making their own (every LLM prompt includes live peer signals from the previous cycle), **consecutive wins scale order size** automatically (a 10-win streak trades at 3× base without any Python intervention), and when three agents reach unanimous consensus they fire an on-chain **coalition order at 3× normal size** — autonomous coordination between AI agents, entirely on-chain.

A fourth feature — **composable user agents** — lets anyone connect their MetaMask wallet and deploy their own autonomous trading agent with a custom strategy prompt, pick an icon, set a risk level, fund it with STT for LLM cycles, and pause/resume it, all trustlessly on-chain.

---

## What It Is

Five system AI agents autonomously trade on the Somnia blockchain. Every trading decision for four of them is validated by Somnia's decentralized LLM inference agent — not an off-chain bot. The fifth (Noise-Bot) runs a fully on-chain mean-reversion rule with no LLM overhead. Every order is matched by a real on-chain limit order book. A live dashboard shows visible decision flow, real-time charts, a full-width latency comparison panel, event injection, and live on-chain metrics.

All five agents share a single coordinator pool of synthetic tokens. Each agent has a **virtual sETH and USDC balance** tracked on-chain, updated on every fill and cancel via callbacks from the Exchange. The coordinator enforces per-agent limits — an agent that runs out of virtual balance skips orders without affecting others.

STT fees (for Somnia platform JSON API + LLM calls) are tracked **per user wallet**: all agents owned by the same address share one prepaid STT pool. Users fund their pool via `coordinator.fund()` — the existing step in the Create Agent flow.

---

## How It Works

On startup, the orchestrator fires one `triggerAgentDecision()` per agent — that's the only Python transaction ever sent. From that point the `AgentCoordinator` self-loops forever: `handleDecision()` (or `_executeRuleDecision()` for rule-based agents) calls `_retrigger()` at the end of every cycle. Python never touches the contracts again for any trading decision.

Four background loops keep the dashboard live:

- **Trade event poll** (1s) — reads `TradeExecuted` events → drives the price chart
- **Snapshot broadcast** (3s) — pushes market state to WebSocket clients
- **Contract metrics poll** (5s) — reads coordinator events and contract state → emits `chain_metrics`
- **Token replenisher** (30s) — polls the coordinator's QUOTE/AGT pool balance and auto-mints when below threshold

---

## Agents

### System Agents (pre-deployed)

All five agents share the coordinator's token pool. Each gets a virtual 10K sETH + 10K USDC allocation at deploy time.

| Agent              | Name           | Strategy                                    | Decision source                                                                  |
| ------------------ | -------------- | ------------------------------------------- | -------------------------------------------------------------------------------- |
| ⚖️ Market Maker    | MM-Prime       | Dual-sided quoting, captures spread         | Somnia LLM — places **both** a bid and an ask each cycle                         |
| 📈 Momentum Trader | Momentum-Alpha | Rides trends, enters long/short on momentum | Somnia LLM — buys into upward momentum, sells into downward                      |
| 🔍 Arbitrage Agent | Arb-Scanner    | Exploits reference vs on-chain price gap    | Somnia LLM — buys when on-chain is underpriced vs oracle, sells when overpriced  |
| 🛡️ Risk Manager    | Risk-Shield    | Stabilises extremes, provides liquidity     | Somnia LLM — buys/sells to contain ±$5 deviation from oracle                    |
| 🎲 Noise Bot       | Noise-Bot      | Order-book balancing, keeps both sides live | On-chain rule — no LLM: more asks than bids → BUY; more bids than asks → SELL   |

### Composable User Agents

Any wallet can create their own autonomous agent:

1. **Connect** MetaMask in the dashboard → click **MY AGENTS** tab → **CREATE AGENT**
2. **Define** — pick an emoji icon, set a risk level (1 = conservative → 5 = aggressive, scales order size), write a strategy prompt. All stored on-chain in `AgentRegistry`
3. **Deploy** — one MetaMask transaction calls `AgentRegistry.registerAgent()`; the registry configures the coordinator and emits `AgentRegistered`; the backend detects it, calls `allocateToAgent` (1000 sETH + 1000 USDC from pool), then fires the LLM loop
4. **Fund** — send STT to `AgentCoordinator.fund()` from your wallet; all your agents draw from your shared STT balance. Each LLM cycle consumes 2 STT deposits (1 JSON API + 1 LLM)
5. **Pause/Resume** — call `AgentRegistry.pauseAgent(agentId)` / `resumeAgent(agentId)` directly; ownership verified by `agents[agentId].agentOwner == msg.sender`

User agents participate in the same on-chain LLM pipeline as system agents, read peer signals from all other agents, and appear in the scoreboard and activity feed.

**STT accounting:** `userSttBalance[walletAddress]` in the coordinator tracks how much STT each user has prepaid. All agents owned by the same wallet draw from one pool. The deployer's pool covers all 5 system agents.

---

## Tech Stack

- **Frontend**: Next.js 14 + Tailwind CSS + TradingView Lightweight Charts v5 + Zustand + ethers.js
- **Backend**: Python FastAPI + WebSockets (no off-chain AI — all decisions are on-chain)
- **Contracts**: Solidity — all six contracts are upgradeable UUPS proxies: `AgentToken` (sETH ERC20), `QuoteToken` (USDC ERC20), `Exchange` (LOB), `Treasury`, `AgentCoordinator`, `AgentRegistry`
- **Onchain AI**: Somnia LLM Inference Agent via `IAgentRequester` — BUY/SELL/HOLD consensus from Somnia validators
- **User Agent Auth**: trustless — `agentOwner` in `AgentRegistry` enforces ownership on pause/resume

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Somnia Blockchain (chain 50312)                    │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Exchange.sol  (real on-chain LOB)                           │    │
│  │  placeOrderForAgent(isBuy, price, amount, agentId)          │    │
│  │    → _matchOrder → TradeExecuted                            │    │
│  │    → onAgentFill(agentId, isBuy, tokenFill, quoteFill)      │    │
│  │    cancelOrder → onAgentCancel(agentId, ...)                 │    │
│  └──────────────────────┬───────────────────────────────────────┘   │
│                          │ all orders from coordinator (msg.sender)   │
│  ┌───────────────────────┴─────────────────────────────────────┐    │
│  │  AgentCoordinator.sol   (shared coordinator pool)            │    │
│  │                                                              │    │
│  │  Token pool: 50K sETH + 50K USDC (5 agents × 10K each)      │    │
│  │  agentTokenBalance[agentId] / agentQuoteBalance[agentId]     │    │
│  │  userSttBalance[ownerAddress]  (STT per user wallet)         │    │
│  │  agentOwner[agentId]  (cached at allocateToAgent time)       │    │
│  │                                                              │    │
│  │  LLM pipeline (4 agents):                                    │    │
│  │    triggerAgentDecision → JSON API price fetch               │    │
│  │    handlePriceData → LLM inference (deducts STT)             │    │
│  │    handleDecision → placeOrderForAgent → _retrigger          │    │
│  │                                                              │    │
│  │  Rule-based pipeline (noise_trader, empty systemPrompt):     │    │
│  │    triggerAgentDecision → JSON API price fetch               │    │
│  │    handlePriceData → _executeRuleDecision (mean-reversion)   │    │
│  │    → placeOrderForAgent → _retrigger                         │    │
│  │                                                              │    │
│  │  winStreak → _orderAmount()  |  _coalitionCount → 3× order   │    │
│  └──────────────────────┬───────────────────────────────────────┘   │
│                          │ reads config                               │
│  ┌───────────────────────┴─────────────────────────────────────┐    │
│  │  AgentRegistry.sol  (source of truth for ALL agents)         │    │
│  │  registerAgent(agentId, name, icon, riskLevel, prompt, ...)  │    │
│  │  → stores agentOwner, systemPrompt, priceConfig, riskLevel   │    │
│  │  → calls coordinator.addAgentToList(agentId)                 │    │
│  │  → emits AgentRegistered                                      │    │
│  │  pauseAgent / resumeAgent: onlyOwner OR agentOwner[id]       │    │
│  └─────────────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Somnia LLM Inference Agent                                   │    │
│  │  inferString(ctx+peers+streak, systemPrompt, ["BUY","SELL","HOLD"])│
│  └─────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
     ↑ registerAgent() from frontend MetaMask
     ↑ 1 startup tx per agent (triggerAgentDecision)
┌────────┴──────────────────────────────────────────────────────────────┐
│                         FastAPI Backend                                │
│  · trade event poll (1s) ──► PriceEngine ──► MarketStateBus          │
│  · snapshot broadcast (3s)                                            │
│  · contract metrics poll (5s) ──► chain_metrics                      │
│      detects AgentRegistered → allocateToAgent → triggerAgentDecision │
│  · token replenisher (30s) → tops up coordinator pool only           │
│  · watchdog → re-triggers stalled agents                             │
└──────────────────────────────┬────────────────────────────────────────┘
                               │ WebSocket  ws://localhost:8000/ws
┌──────────────────────────────▼────────────────────────────────────────┐
│                    Next.js Dashboard                                   │
│  SYSTEM AGENTS tab: 5 system agent cards (all owned by deployer)      │
│  MY AGENTS tab (wallet-gated):                                        │
│    Create Agent modal → icon picker + risk slider + prompt            │
│    MetaMask → registry.registerAgent() on-chain                       │
│    UserAgentCard: icon, risk badge, live metrics, PAUSE/RESUME/FUND   │
│    pause/resume → registry  |  fund → coordinator.fund()              │
│  ⚡ ADMIN tab (deployer only): per-agent + bulk pause/resume/fund     │
│  Scoreboard: ALL agents ranked by P&L (system + user unified)        │
└───────────────────────────────────────────────────────────────────────┘
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
# Prints env vars — copy DEPLOYER_PRIVATE_KEY + contract addresses into backend/.env
```

Terminal 3 — start everything (backend + frontend + platform daemon):

```bash
./start.sh
```

`start.sh` auto-detects `SOMNIA_RPC_URL=http://127.0.0.1:8545` in `backend/.env` and starts the `platform-daemon.js` alongside the backend and frontend.

### Option B — Somnia Testnet

Prerequisites: Node.js 18+, Python 3.12+, **one funded deployer wallet** (~1 STT for deployment gas).

```bash
git clone <repo>
cd somnia_hackathon
cd backend && pip install -r requirements.txt && cd ..
cd frontend && npm install && cd ..
cd contracts && npm install && cd ..
cd backend && cp .env.example .env
# Fill DEPLOYER_PRIVATE_KEY + contract addresses (see Deploying Onchain below)
./start.sh
```

---

## Deploying Onchain

### Step 1 — Generate 1 deployer wallet

```bash
node -e "
const {ethers} = require('ethers');
const w = ethers.Wallet.createRandom();
console.log('DEPLOYER_PK=' + w.privateKey);
console.log('DEPLOYER_ADDR=' + w.address);
"
```

### Step 2 — Fund via Somnia faucet

Visit **https://testnet.somnia.network/** and request STT for the deployer address (~1 STT needed for deployment).

### Step 3 — Deploy contracts

```bash
cd contracts
cp .env.example .env
# Fill DEPLOYER_PRIVATE_KEY in contracts/.env

npx hardhat run scripts/deploy.js --network somnia
# Deploys all 6 contracts as UUPS proxies
# Registers all 5 system agents + allocates 10K sETH / 10K USDC each
# Funds coordinator with 0.5 STT for platform deposits
# Prints proxy addresses to paste into backend/.env
```

To upgrade any contract after a code change:

```bash
npx hardhat run scripts/upgrade.js --network somnia
# Address unchanged, all storage preserved
```

### Step 4 — Configure backend

```bash
cd backend && cp .env.example .env
```

```
SOMNIA_RPC_URL=https://dream-rpc.somnia.network
SOMNIA_CHAIN_ID=50312
SOMNIA_BLOCK_MS=400
DEPLOYER_PRIVATE_KEY=0x<your_deployer_key>
```

All contract addresses are auto-loaded from the deployment JSON if left blank.

### Step 5 — Configure frontend

```
NEXT_PUBLIC_DEPLOYER_ADDRESS=0xYourDeployerAddress
NEXT_PUBLIC_REGISTRY_ADDRESS=0xYourAgentRegistryAddress
NEXT_PUBLIC_COORDINATOR_ADDRESS=0xYourAgentCoordinatorAddress
```

---

## Demo Events

| Button         | Effect                          | What to watch                                               |
| -------------- | ------------------------------- | ----------------------------------------------------------- |
| WHALE BUY +3%  | Instant +3% price shock         | Momentum Trader enters long; Arb-Scanner detects deviation  |
| WHALE SELL -3% | Instant -3% price shock         | Momentum Trader enters short; MM widens spread              |
| VOL SPIKE      | 5× volatility for 30 seconds    | MM-Prime widens spread; Risk-Shield monitors exposure       |
| NEWS EVENT     | 3× volatility + 1.5% upside     | Mixed agent reactions via peer signals                      |
| FLASH CRASH    | -8% price shock + 8× volatility | Risk Manager broadcasts warning; all agents scramble        |

---

## Project Structure

```
somnia_hackathon/
├── contracts/
│   ├── contracts/
│   │   ├── AgentToken.sol          # Upgradeable ERC20 (sETH) — minted to coordinator pool
│   │   ├── QuoteToken.sol          # Upgradeable ERC20 (USDC) — BUY order payment currency
│   │   ├── Exchange.sol            # Upgradeable LOB — placeOrderForAgent with fill/cancel callbacks
│   │   │                           # IAgentFillCallback: onAgentFill / onAgentCancel
│   │   │                           # _orderAgentId[orderId] → per-order agentId for attribution
│   │   ├── AgentCoordinator.sol    # Upgradeable execution engine
│   │   │                           # agentTokenBalance[agentId] / agentQuoteBalance[agentId]
│   │   │                           # userSttBalance[ownerAddr] — prepaid STT per user wallet
│   │   │                           # agentOwner[agentId] — cached at allocateToAgent time
│   │   │                           # allocateToAgent(agentId, owner, tokenAmt, quoteAmt)
│   │   │                           # fund() / depositStt(forOwner) — STT deposit
│   │   │                           # LLM pipeline: trigger → handlePriceData → handleDecision
│   │   │                           # Rule pipeline: trigger → handlePriceData → _executeRuleDecision
│   │   │                           # winStreak, coalitions, cancel-before-place, peer signals
│   │   ├── AgentRegistry.sol       # Upgradeable registry for all agents (system + user)
│   │   │                           # agentOwner — deployer for system, user wallet for custom
│   │   │                           # pauseAgent/resumeAgent: onlyOwner OR agentOwner[id]
│   │   ├── Treasury.sol            # Upgradeable per-agent ETH balance tracker
│   │   └── MockPlatform.sol        # Local dev: simulates Somnia platform callbacks
│   ├── scripts/
│   │   ├── deploy-local.js         # Local: deploys + registers + allocates 5 agents, writes somnia-local.json
│   │   ├── deploy.js               # Testnet: deploys all 6 UUPS proxies, registers + allocates agents
│   │   ├── upgrade.js              # Testnet/local: upgrades proxy implementations (address unchanged)
│   │   ├── platform-daemon.js      # Local: fires MockPlatform price + LLM callbacks
│   │   ├── test-local.js           # Local: one-shot smoke test for the full decision cycle
│   │   └── verify.js               # Testnet: sanity-check live contracts
│   └── deployments/
│       ├── somnia-local.json        # Local addresses + ABIs (no PKs — only deployer key needed)
│       └── somnia-testnet.json      # Testnet addresses + ABIs
├── backend/
│   ├── main.py                      # FastAPI entry point, lifespan, router registration
│   ├── config.py                    # Pydantic Settings — only DEPLOYER_PRIVATE_KEY required
│   │                                # validate_settings() exits if deployer key missing/invalid
│   ├── agents/
│   │   ├── orchestrator.py          # AGENT_CONFIGS (5 system agents, no PKs),
│   │   │                            # startup triggers (all 5 via deployer key),
│   │   │                            # _on_user_agent_registered() → allocateToAgent + triggerAgentDecision,
│   │   │                            # _reload_user_agents_from_db() on restart
│   │   ├── metrics_collector.py     # Trade poll (1s) + chain metrics (5s): P&L, per-agent stats
│   │   ├── token_replenisher.py     # Coordinator pool top-up only (30s) — no per-agent wallet checks
│   │   ├── watchdog.py              # Stall detection + re-trigger for all 5 agents
│   │   └── user_agents_db.py        # JSON cache at backend/data/user_agents.json
│   ├── market/
│   │   ├── state_bus.py             # Async-safe shared market state
│   │   ├── price_engine.py          # GBM simulation + OHLCV builder
│   │   ├── price_feed.py            # CoinGecko ETH/USD reference price
│   │   └── order_book.py            # In-memory order book reconstruction
│   ├── blockchain/
│   │   ├── client.py                # Web3 singleton, nonce Lock, send_transaction()
│   │   ├── abis.py                  # Fallback ABI definitions
│   │   └── contracts.py             # Typed contract wrappers including allocate_to_agent(),
│   │                                # get_user_stt_balance(), place_order_for_agent()
│   └── api/
│       ├── websocket_hub.py
│       ├── routes_ws.py
│       ├── auth.py                  # MetaMask personal_sign admin auth
│       ├── routes_http.py           # REST: health, agents, chain-metrics, pause/resume/fund
│       └── routes_user_agents.py    # GET /user/agents?address=0x...
└── frontend/
    ├── components/agents/
    │   ├── CreateAgentModal.tsx      # 2-step: define (prompt/icon/risk) → fund STT
    │   ├── UserAgentCard.tsx         # PAUSE / RESUME / FUND controls
    │   ├── MyAgentsPanel.tsx         # Wallet-gated user agent panel
    │   ├── AgentCard.tsx             # System agent card with streak badge + P&L
    │   ├── AgentScoreboard.tsx       # All agents ranked by realized + unrealized P&L
    │   └── AdminPanel.tsx            # Deployer-only bulk controls
    ├── hooks/
    │   ├── useUserAgents.ts          # createAgent → registerAgent() on-chain
    │   │                             # fundAgent → coordinator.fund() (sets userSttBalance)
    │   └── useAdminActions.ts        # Admin MetaMask sign-and-post
    └── store/
        ├── marketStore.ts / agentStore.ts / feedStore.ts / userStore.ts
```

**To change system agent behavior:** update `PROMPTS` in `contracts/scripts/deploy-local.js` (local) or `deploy.js` (testnet) and redeploy.  
**Noise trader behavior:** controlled by `_executeRuleDecision` in `AgentCoordinator.sol` — compares active buy vs sell order counts; BUYs when asks outnumber bids, SELLs when bids outnumber asks, random when balanced. Registered with empty `systemPrompt` in the registry.  
**Token economics:** 50K sETH + 50K USDC minted to coordinator (5 agents × 10K each). Token replenisher auto-mints to the coordinator pool when total balance drops below 1,000. sETH/USDC price is determined by order book activity.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Backend exits with `[config] Missing or invalid secrets` | `DEPLOYER_PRIVATE_KEY` not set (testnet only) | Copy `.env.example` to `.env` and fill in deployer key |
| Agent shows "Insufficient STT" and loop stops | User's STT pool depleted | Call `coordinator.fund()` with more STT from the agent owner's wallet |
| User agent never starts after creation | `allocateToAgent` failed or coordinator underfunded | Check backend logs; ensure coordinator has token balance; user must also fund STT |
| Noise trader not placing orders | Rule decision failing due to zero virtual balance | Ensure deploy script called `allocateToAgent("noise_trader", ...)` |
| Chart blank on load | Backend not running or WS URL wrong | Check `NEXT_PUBLIC_WS_URL`; verify backend at `http://localhost:8000/health` |
| `deploy-local.js` fails | Hardhat node not running or insufficient funds | Start `npx hardhat node` first |
| Agent cards show zeros after startup | Contracts not configured or warming up | Wait 10s; check `/debug/config` endpoint |
| `LoopStopped` events for a user agent | User's STT balance exhausted | Fund via FUND button on agent card |
| Coalition alerts missing | Fewer than 3 directional agents agree | Normal — market_maker is non-directional; needs 3 of momentum/arb/risk to agree |
| MY AGENTS tab empty after creating agent | Backend hasn't detected `AgentRegistered` event yet | Wait ~5s for metrics poll loop |
| `registerAgent` tx reverts | Agent ID already taken | Modal generates random suffix — try again |
| `pauseAgent` reverts for user agent | Calling from wrong wallet | Only the wallet that called `registerAgent()` can pause |
| sETH balance shows 0 for all agents | On-chain agents share coordinator pool, no individual wallets | Expected — dashboard shows virtual balance per agent via `agentTokenBalance` |

---

## Somnia Network

|              |                                         |
| ------------ | --------------------------------------- |
| **Chain**    | Somnia Testnet                          |
| **Chain ID** | 50312                                   |
| **RPC**      | https://dream-rpc.somnia.network        |
| **Explorer** | https://shannon-explorer.somnia.network |
| **Faucet**   | https://testnet.somnia.network/         |

> Gas price is hardcoded at **6 gwei** throughout the codebase.

---

## Docs

- [Architecture](docs/ARCHITECTURE.md) — system design, data flow, accounting model, component internals
- [Contracts](docs/CONTRACTS.md) — Solidity reference, deployment walkthrough, script docs
- [Backend](docs/BACKEND.md) — FastAPI internals, config reference, agent tuning
- [Frontend](docs/FRONTEND.md) — Next.js components, Zustand stores, WS dispatch
- [Demo Script](docs/DEMO_SCRIPT.md) — 5-minute judge walkthrough
