# Backend — Agentic Exchange

Python FastAPI server. Fires one `triggerAgentDecision()` per agent at startup (the only Python transactions ever sent for trading), then observes on-chain activity via event polling and broadcasts metrics to the frontend via WebSocket. Also handles user agent discovery and registration.

All five system agents use the deployer key — no individual agent PKs required.

---

## Directory Map

```
backend/
├── main.py                  # FastAPI app, CORS, lifespan startup/shutdown
│                            # calls validate_settings() first — exits on bad/missing deployer key
├── config.py                # Pydantic Settings — only DEPLOYER_PRIVATE_KEY required
│                            # validate_settings(): exits with clear error if key missing on non-localhost
├── .env.example             # ← committed template
├── .env                     # Secret keys — NOT committed
├── agents/
│   ├── orchestrator.py      # AGENT_CONFIGS (5 system agents, no PKs)
│   │                        # _load_local_deployment(): loads contract addresses from somnia-local.json
│   │                        # start_all(): fires triggerAgentDecision() for all 5 via deployer key
│   │                        # _contract_metrics_poll_loop(): detects AgentRegistered events
│   │                        # _on_user_agent_registered(): allocateToAgent → triggerAgentDecision
│   │                        # _reload_user_agents_from_db(): restores state on restart
│   ├── metrics_collector.py # Trade poll (1s) + chain metrics (5s)
│   │                        # _record_pnl_from_trade(): per-agent P&L, net_position, avg_cost
│   │                        # _process_coordinator_events(): win streaks, decisions, order attribution
│   │                        # empty_agent_metrics(): factory shared with orchestrator
│   ├── token_replenisher.py # Coordinator pool top-up only (30s)
│   │                        # Checks coordinator AGT + QUOTE balance; mints if below 1K
│   │                        # No per-agent wallet checks — all agents share coordinator pool
│   ├── watchdog.py          # AgentWatchdog: stall detection + re-trigger with fresh nonce
│   └── user_agents_db.py    # JSON cache at backend/data/user_agents.json (no private keys)
├── market/
│   ├── price_engine.py      # GBM price simulation + OHLCVBuilder (5s bars)
│   ├── price_feed.py        # CoinGecko ETH/USD reference price
│   ├── order_book.py        # In-memory bid/ask depth reconstruction
│   └── state_bus.py         # Async-safe shared state (price, order book, warnings)
├── blockchain/
│   ├── client.py            # Web3 singleton, per-wallet nonce Lock, send_transaction()
│   │                        # Hardcoded 6 gwei gas — dynamic estimation fails on Somnia testnet
│   ├── abis.py              # Fallback ABI definitions
│   └── contracts.py         # _BaseContract (_call/_tx) + typed wrappers:
│                            # ExchangeContract, TreasuryContract, AgentCoordinatorContract,
│                            # AgentRegistryContract, AgentTokenContract, QuoteTokenContract
│                            # Key new methods on AgentCoordinatorContract:
│                            #   allocate_to_agent(pk, agentId, owner, tokenAmt, quoteAmt)
│                            #   get_user_stt_balance(owner)
└── api/
    ├── websocket_hub.py     # ConnectionManager: broadcast() to all WS clients
    ├── routes_ws.py         # /ws WebSocket endpoint
    ├── auth.py              # MetaMask personal_sign admin auth
    │                        # verify_admin_signature(): X-Admin-Sig/Message/Address headers
    │                        # Signer must match deployer_address; timestamps expire after 5 min
    ├── routes_http.py       # REST: health, state, agents, chain-metrics, events/inject,
    │                        # agents/{id}/pause, resume, fund; agents/pause-all, resume-all, fund-all
    └── routes_user_agents.py# GET /user/agents?address=0x... — cached list + live metrics
```

---

## Configuration

Only one secret is required:

```env
DEPLOYER_PRIVATE_KEY=0x...   # The single deployer wallet key
SOMNIA_RPC_URL=https://dream-rpc.somnia.network
SOMNIA_CHAIN_ID=50312
SOMNIA_BLOCK_MS=400          # Used for latency display on dashboard
```

Contract addresses are auto-loaded from `contracts/deployments/somnia-local.json` when `SOMNIA_RPC_URL` points to localhost. For testnet, add them explicitly or they're auto-loaded from the testnet deployment JSON.

On localhost, `validate_settings()` skips the key check (auto-loaded from JSON). On testnet, it exits with a clear error listing exactly what's wrong.

---

## Running Locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill in DEPLOYER_PRIVATE_KEY (auto-populated from somnia-local.json on localhost)
uvicorn main:app --reload --port 8000
```

---

## Startup Sequence

1. `validate_settings()` — exits if deployer key missing/invalid (testnet only)
2. `_load_local_deployment()` — injects contract addresses from `somnia-local.json` (localhost)
3. Derives `deployer_address` from `deployer_private_key`
4. Initialises contract objects (`ExchangeContract`, `AgentCoordinatorContract`, etc.)
5. `_reload_user_agents_from_db()` — restores previously registered user agents from JSON cache
6. `start_all()`:
   - Seeds GBM price engine from live CoinGecko feed
   - Starts 4 background loops (trade poll, snapshot, metrics, token replenisher)
   - Fires `triggerAgentDecision()` for all 5 system agents via deployer key (1s stagger)
   - Starts `AgentWatchdog`

---

## User Agent Registration Flow

When `AgentRegistered` is detected in the 5s metrics poll:

```python
async def _on_user_agent_registered(self, agent_id, owner, name, icon, risk_level):
    # 1. Persist to JSON cache
    UserAgentsDB().upsert_from_event(agent_id, owner, name, icon, risk_level)

    # 2. Register in memory
    self.agents[agent_id] = { agent_id, name, owner, icon, risk_level, is_user_agent=True }
    self._chain_metrics["agents"][agent_id] = empty_agent_metrics(agent_id)

    # 3. Allocate virtual token balances (1000 sETH + 1000 USDC from coordinator pool)
    await self._coordinator.allocate_to_agent(
        deployer_pk, agent_id, owner,
        token_amount=1000.0, quote_amount=1000.0
    )

    # 4. Fire first decision cycle
    await self._coordinator.trigger_decision(deployer_pk, agent_id)
```

The user must separately call `coordinator.fund()` from their wallet to deposit STT. `allocateToAgent` provides synthetic token capital; STT for platform fees comes from the user.

---

## Background Loops

### Trade event poll (1s)

`MetricsCollector.run_trade_poll`:
- Polls `Exchange.TradeExecuted` events and `AgentCoordinator.DecisionExecuted` events
- `_record_pnl_from_trade(agent_id, is_buy, price, amount)`: updates `net_position`, `avg_cost`, `trade_pnl`, `unrealized_pnl`
- Trade attribution: `_order_to_agent[order_id] → agent_id` (built from `DecisionExecuted` events)
- Broadcasts `candle` WS message on 5s bar close

### Snapshot broadcast (3s)

Pushes `market_snapshot` WS message: current price, bid/ask, spread, order book, recent trades.

### Contract metrics poll (5s)

`MetricsCollector.collect`:
- Reads coordinator events: `DecisionExecuted`, `LLMRequestFired`, `CoalitionFormed`, `LoopStopped`
- Reads Exchange state: order book depth, best bid/ask, spread
- Detects new `AgentRegistered` events → calls `_on_user_agent_registered()`
- Broadcasts `chain_metrics` WS message with all per-agent state

### Token replenisher (30s)

`TokenReplenisher.run`:
- Checks coordinator's AGT balance → mints 10K if below 1K
- Checks coordinator's QUOTE balance → mints 10K if below 1K
- No per-agent wallet checks — all agents share the coordinator pool

---

## AgentCoordinatorContract — Key Methods

```python
# Fire the on-chain decision pipeline for one agent
await coordinator.trigger_decision(deployer_pk, agent_id)

# Set virtual sETH/USDC allocation for an agent (call before trigger_decision)
await coordinator.allocate_to_agent(deployer_pk, agent_id, owner, token_amount=1000.0, quote_amount=1000.0)

# Read user's prepaid STT balance
balance = await coordinator.get_user_stt_balance(owner_address)  # returns float in STT

# Pause / resume agent loop
await coordinator.pause_agent(deployer_pk, agent_id)
await coordinator.resume_agent(deployer_pk, agent_id)
```

---

## HTTP Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | — | `{ status, agents_running, ws_connections }` |
| `GET` | `/state` | — | Full market snapshot |
| `GET` | `/agents` | — | Array of 5 agent state summaries |
| `GET` | `/chain-metrics` | — | Latest chain_metrics snapshot |
| `POST` | `/events/inject` | — | `{ event_type }` → triggers simulated market event |
| `POST` | `/agents/trigger` | — | Re-fires triggerAgentDecision for all agents |
| `GET` | `/debug/config` | — | Non-sensitive config + coordinator init status |
| `POST` | `/agents/{id}/pause` | admin_auth | Pauses agent loop on-chain |
| `POST` | `/agents/{id}/resume` | admin_auth | Resumes agent loop + re-triggers |
| `POST` | `/agents/pause-all` | admin_auth | Pauses all system agents |
| `POST` | `/agents/resume-all` | admin_auth | Resumes all system agents |
| `POST` | `/agents/{id}/fund` | admin_auth | `{ amount }` — mints sETH to coordinator |
| `GET` | `/user/agents` | — | `?address=0x...` — cached user agents + live metrics |

**`admin_auth`** (`api/auth.py`): reads `X-Admin-Sig`, `X-Admin-Message`, `X-Admin-Address` headers. Verifies `personal_sign(message, address)` where `message = "admin:<action>:<unix_timestamp>"`. Signer must match deployer address. Requests older than 5 minutes are rejected.

---

## Tuning

**User agent allocation:** `token_amount=1000.0, quote_amount=1000.0` in `_on_user_agent_registered`. Increase/decrease to give users more/less virtual capital per agent.

**Replenishment threshold:** `_TOPUP_THRESHOLD = 1000.0`, `_TOPUP_AMOUNT = 10000.0` in `token_replenisher.py`.

**Watchdog stall timeout:** configured in `watchdog.py` — how long before an agent is considered stalled and re-triggered.

**Gas price:** `GAS_PRICE = 6_000_000_000` (6 gwei) in `blockchain/client.py`. Do not change for Somnia testnet.
