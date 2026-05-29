# Frontend — Agentic Exchange

Next.js 14 App Router dashboard displaying five autonomous AI trading agents running on the Somnia blockchain in real-time. The dashboard opens with a full-width `LatencyHero` panel comparing Somnia's decision latency against Solana (~400 ms) and Ethereum (~12,000 ms).

---

## Directory Map

```
frontend/
├── app/
│   ├── layout.tsx           # Root layout: Inter font, dark bg, wraps with Providers
│   ├── page.tsx             # Main dashboard: Header + left panel + right panel + feed
│   ├── providers.tsx        # Client-side init: calls useWebSocket() to open WS connection
│   └── globals.css          # CSS variables, Tailwind directives, fadeIn animation
├── components/
│   ├── layout/
│   │   ├── Header.tsx       # Logo, live ticker (price + volume + spread), 5 event injection buttons
│   │   ├── LatencyHero.tsx  # Full-width latency comparison: Somnia vs Solana vs Ethereum
│   │   └── ActivityFeed.tsx # Horizontal scrolling feed bar; tx hashes link to Somnia explorer
│   ├── chart/
│   │   ├── CandlestickChart.tsx  # TradingView Lightweight Charts v5 (SSR-disabled)
│   │   ├── OrderBook.tsx         # Bid/ask depth with proportional size bars
│   │   └── RecentTrades.tsx      # Scrollable recent trades list with buyer/seller agent attribution
│   ├── agents/
│   │   ├── AgentGrid.tsx         # 2-column grid container for 5 system agent cards
│   │   ├── AgentCard.tsx         # Strategy desc + stats (decisions, BUY/SELL/HOLD, P&L, position)
│   │   ├── AgentScoreboard.tsx   # P&L leaderboard ranked by total P&L (realized + unrealized)
│   │   ├── AgentStatusBadge.tsx  # ACTIVE / WAITING / STOPPED badge with status dot
│   │   ├── ReasoningPanel.tsx    # Live LLM prompt + last 5 decision history entries per agent
│   │   ├── MyAgentsPanel.tsx     # Wallet-gated panel: user's own agents + CREATE AGENT button
│   │   ├── UserAgentCard.tsx     # User agent card with live metrics + PAUSE / RESUME / FUND controls
│   │   ├── CreateAgentModal.tsx  # Two-step modal: define strategy prompt → fund with STT
│   │   ├── AdminPanel.tsx        # Deployer-only bulk pause/resume/fund panel
│   │   └── AdminAgentRow.tsx     # Single-agent row within AdminPanel (per-agent controls)
│   └── ui/
│       ├── badge.tsx            # Badge component (default/outline variants)
│       ├── button.tsx           # Button component (default/outline/ghost + sizes)
│       ├── card.tsx             # Card + CardHeader + CardContent primitives
│       └── separator.tsx        # Horizontal/vertical separator line
├── store/
│   ├── marketStore.ts       # Zustand: candles, orderBook, trades, price, connection
│   ├── agentStore.ts        # Zustand: agent states, decision history, coordinator metrics
│   ├── feedStore.ts         # Zustand: activity feed items
│   └── userStore.ts         # Zustand: connected wallet address (shared Header → page)
├── hooks/
│   ├── useWebSocket.ts      # WS connect/reconnect, message dispatch, injectEvent()
│   ├── useAdminActions.ts   # Wallet connect + MetaMask personal_sign for admin API calls
│   └── useUserAgents.ts     # User agent CRUD: createAgent (on-chain), pause/resume/fund via MetaMask
├── types/
│   └── global.d.ts          # EthereumProvider interface + window.ethereum type declaration
└── lib/
    ├── types.ts             # All TypeScript interfaces (CandleData, AgentState, ChainMetrics, UserAgentRecord, …)
    └── utils.ts             # cn() helper for className merging
```

---

## Running Locally

```bash
npm install
npm run dev
# Dashboard at http://localhost:3000
```

The dashboard renders with zeroed-out defaults until the WebSocket connects and the first `chain_metrics` message arrives (within ~5s of backend startup).

### Environment Variables (`.env.local`)

| Variable                          | Default                                   | Purpose                                                                                                  |
| --------------------------------- | ----------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `NEXT_PUBLIC_WS_URL`              | `ws://localhost:8000/ws`                  | Backend WebSocket endpoint                                                                               |
| `NEXT_PUBLIC_API_URL`             | `http://localhost:8000`                   | Backend HTTP base URL                                                                                    |
| `NEXT_PUBLIC_SOMNIA_EXPLORER`     | `https://shannon-explorer.somnia.network` | Base URL for tx hash links in the activity feed                                                          |
| `NEXT_PUBLIC_DEPLOYER_ADDRESS`    | `` (empty)                                | Deployer's public address; when a connected wallet matches this, the ⚡ ADMIN tab becomes visible        |
| `NEXT_PUBLIC_REGISTRY_ADDRESS`    | `` (empty)                                | `AgentRegistry` contract address; `registerAgent()`, `pauseAgent()`, `resumeAgent()` are called here     |
| `NEXT_PUBLIC_COORDINATOR_ADDRESS` | `` (empty)                                | `AgentCoordinator` address; only `fund()` is called here (user agents funding their agent's STT balance) |

---

## State Management

Four Zustand stores, all exported from their respective files in `store/`.

### `store/marketStore.ts`

| State field      | Type           | Description                 |
| ---------------- | -------------- | --------------------------- |
| `candles`        | `CandleData[]` | Ring buffer, max 200 bars   |
| `orderBook`      | `OrderBook`    | Top 10 bids + top 10 asks   |
| `recentTrades`   | `Trade[]`      | Last 50 trades              |
| `currentPrice`   | `number`       | Latest mid price            |
| `priceChange24h` | `number`       | 24h % change                |
| `volume24h`      | `number`       | 24h volume                  |
| `spreadPct`      | `number`       | Current bid-ask spread %    |
| `isConnected`    | `boolean`      | WebSocket connection status |

Key actions: `addCandle(candle)` (appends or updates last bar, caps at 200), `setMarketSnapshot(snap)` (batch update from WS).

### `store/agentStore.ts`

| State field          | Type                           | Description                                                    |
| -------------------- | ------------------------------ | -------------------------------------------------------------- |
| `agents`             | `Record<agent_id, AgentState>` | Full agent state from latest `chain_metrics` (system + user)   |
| `decisionHistory`    | `Record<agent_id, string[]>`   | Last 20 `"BUY @ $3245"` entries, derived from diffs            |
| `coordinatorBalance` | `number`                       | STT remaining in coordinator                                   |
| `totalLocked`        | `number`                       | Total STT in treasury                                          |
| `loopStoppedAny`     | `boolean`                      | True if any agent's loop has stopped (excluding paused agents) |
| `recentFills`        | `Fill[]`                       | Last 20 matched trades with buyer/seller agent IDs + `tx_hash` |
| `somniaBlockMs`      | `number`                       | Block time in ms (for latency display in LatencyHero)          |

Per-agent `AgentState` also includes: `last_context` (full LLM prompt from `LLMRequestFired.context`), `win_streak`, `net_position` (float, positive = long), `unrealized_pnl` (mark-to-market), `wallet_address`.

`updateFromChainMetrics(metrics)` is the single update entry point — called on every `chain_metrics` WS message.

### `store/feedStore.ts`

| State field | Type                 | Description                        |
| ----------- | -------------------- | ---------------------------------- |
| `items`     | `ActivityFeedItem[]` | Ring buffer, max 100, newest first |

### `store/userStore.ts`

| State field     | Type             | Description                                                                     |
| --------------- | ---------------- | ------------------------------------------------------------------------------- |
| `walletAddress` | `string \| null` | Connected MetaMask wallet address; written by Header, read by page to gate tabs |

---

## WebSocket Message Dispatch

Connection managed in `hooks/useWebSocket.ts`. Auto-reconnects 3s after close. Sends keepalive ping every 30s.

| `msg.type`        | Action                                                                                                                                                                                                         |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `market_snapshot` | `marketStore.setMarketSnapshot(msg.data)`                                                                                                                                                                      |
| `candle`          | `marketStore.addCandle(msg.data)`                                                                                                                                                                              |
| `chain_metrics`   | `agentStore.updateFromChainMetrics(msg.data)` — also diffs per-agent `decisions_total` to push new entries to `feedStore` (including `tx_hash` from `recent_fills`) and `loop_stopped` transitions as warnings |
| `coalition_alert` | `feedStore.addItem(...)` as `category: "coalition"` — broadcast immediately on `CoalitionFormed`; not batched with the 5s metrics cycle                                                                        |
| `risk_warning`    | `feedStore.addItem(...)` as `category: "warning"` — emitted by backend on spread > 2% (`HIGH_SPREAD`) or volatility spike > 2% (`VOLATILITY_SPIKE`)                                                            |
| `event_injected`  | `feedStore.addItem(...)` as `category: "event"`                                                                                                                                                                |

**Sending events:** `useWebSocket` exports `injectEvent(type)` which POSTs to `POST /events/inject`. Called by the Header buttons.

---

## Hooks

### `hooks/useAdminActions.ts`

Standalone utility functions (not a React hook) for MetaMask wallet connection and signed admin API calls.

**`connectWallet() → string | null`** — calls `window.ethereum.request({ method: 'eth_requestAccounts' })`, returns the connected address.

**`isOwnerAddress(address: string) → boolean`** — returns true when `address.toLowerCase() === NEXT_PUBLIC_DEPLOYER_ADDRESS.toLowerCase()`. Used by `page.tsx` to show the ⚡ ADMIN tab.

**`signAndPost(address, action, url, body?)`** — internal helper:

1. Builds message: `"admin:<action>:<unix_timestamp>"`
2. Calls `window.ethereum.request({ method: 'personal_sign', params: [message, address] })`
3. POSTs to `${API_URL}${url}` with headers `X-Admin-Sig`, `X-Admin-Message`, `X-Admin-Address`

**`pauseAll(address)`** / **`resumeAll(address)`** / **`fundAll(address, amount)`** — thin wrappers over `signAndPost` targeting the corresponding backend endpoints.

**`global.d.ts`** declares the `EthereumProvider` interface (`request()`, `on()`, `removeListener()`, `isMetaMask`) and extends `Window` with `ethereum?: EthereumProvider`.

### `hooks/useUserAgents.ts`

React hook managing the full lifecycle of a user's composable agents. Takes `walletAddress: string | null`.

- **`fetchAgents()`** — GETs `/user/agents?address=0x...` and merges the cached records with live `agentStore` metrics
- **`createAgent(name, icon, riskLevel, prompt)`** — ABI-encodes `registerAgent()` via ethers `Interface`, sends the tx from the user's wallet via `window.ethereum`, then calls `fetchAgents()` to refresh
- **`pauseAgent(agentId)`** / **`resumeAgent(agentId)`** — calls `AgentRegistry.pauseAgent/resumeAgent` directly via MetaMask (ownership verified on-chain)
- **`fundAgent(agentId, amountEth)`** — calls `AgentCoordinator.fund()` with `value = parseEther(amountEth)` directly via MetaMask

Returns `{ agents, loading, error, fetchAgents, createAgent, pauseAgent, resumeAgent, fundAgent }`.

---

## Component Reference

### `Header.tsx`

- Reads: `marketStore.currentPrice`, `marketStore.isConnected`, `marketStore.priceChange24h`, `marketStore.volume24h`
- Uses: `useWebSocket().injectEvent`, `useAdminActions`, `userStore.setWalletAddress`
- 5 event buttons (WHALE BUY, WHALE SELL, VOL SPIKE, NEWS EVENT, FLASH CRASH) each with a 10s cooldown after click
- **CONNECT WALLET** button — calls `connectWallet()`, stores result in `userStore`; once connected shows the wallet address
- Admin controls (⚡ ADMIN tab, visible only when deployer wallet is connected) are rendered in `AdminPanel`

### `LatencyHero.tsx`

- Full-width panel rendered between `<Header />` and the main content grid in `page.tsx`
- Reads: `agentStore.agents`, `agentStore.recentFills`, `agentStore.somniaBlockMs`
- Computes `avgLatencyMs` = mean of `avg_decision_latency_ms` across agents with at least one recorded decision
- Displays an animated latency number (emerald, tabular-nums) that restarts `animate-pulse` on each new fill via `key={fillKey}` remount trick
- Three proportional comparison bars: Somnia (emerald, actual ms), Solana (~400 ms, fixed 3.3%), Ethereum (~12,000 ms, fixed 100%)

### `CandlestickChart.tsx`

- Reads: `marketStore.candles`
- **SSR-disabled**: imported via `dynamic(() => import(...), { ssr: false })` in `page.tsx`
- TradingView Lightweight Charts v5 API: `chart.addSeries(CandlestickSeries, {...})`
- Initial render: `series.setData(candles)` then `chart.timeScale().fitContent()`
- Live updates: `series.update(candle)` only — never call `setData()` again after init
- Responsive via `ResizeObserver` on the container div

### `OrderBook.tsx`

- Reads: `marketStore.orderBook`, `marketStore.currentPrice`
- Displays 8 asks (reversed, lowest at bottom) + mid price + 8 bids
- Background width bar proportional to size relative to max level size

### `RecentTrades.tsx`

- Reads: `marketStore.recentTrades`
- Shows first 30 trades: price (colored by side), size, age, and buyer/seller agent names when available

### `AgentGrid.tsx`

- Reads: `agentStore.agents`
- Fixed rendering order: `market_maker`, `momentum_trader`, `arbitrage_agent`, `risk_manager`, `noise_trader`
- 5 system agents rendered in a 2-column grid (xl:grid-cols-2, odd count is fine)

### `AgentCard.tsx`

- Props: `agent: AgentState`
- Per-agent color coding: market_maker=blue, momentum_trader=emerald, arbitrage_agent=violet, risk_manager=yellow, noise_trader=pink
- Strategy description line rendered below agent name
- Stats: decisions total, BUY/SELL/HOLD counts, sETH inventory + USDC cash balances, net position (LONG/SHORT/FLAT badge)
- 🔥 streak badge (pulsing amber border) when `win_streak > 0`; tooltip shows current order size multiplier
- Contains `ReasoningPanel` and `AgentStatusBadge`

### `AgentScoreboard.tsx`

- Reads: `agentStore.agents`
- Ranks all agents by `trade_pnl + unrealized_pnl` (highest first) with medal emojis (🥇🥈🥉4️⃣5️⃣)
- Shows per-agent: realized P&L, unrealized P&L (shown when abs > 0.01), buy volume, sell volume, avg decision latency
- Row background tints green (profitable) or red (losing) based on P&L threshold
- Covers both system and user agents — unified scoreboard

### `AgentStatusBadge.tsx`

- Props: `status: 'ACTIVE' | 'WAITING' | 'STOPPED'`
- ACTIVE: pulsing emerald dot
- WAITING: static gray dot
- STOPPED: static red dot

### `ReasoningPanel.tsx`

- Props: `agentId: string`
- Reads: `agentStore.decisionHistory[agentId]` (last 5 entries), `agentStore.agents[agentId]?.last_context` (full LLM prompt from `LLMRequestFired.context`)
- Shows the live `last_context` string first (monospace, subtle bg) — what Somnia validators actually received
- Below that, up to 5 most recent decision history entries; newest has `fadeIn` animation and brighter color

### `MyAgentsPanel.tsx`

- Props: `walletAddress: string`
- Uses `useUserAgents(walletAddress)` to fetch and manage the user's agents
- Shows a list of `UserAgentCard` components for agents owned by the connected wallet
- **CREATE AGENT** button opens `CreateAgentModal`
- Empty state prompts the user to create their first agent

### `UserAgentCard.tsx`

- Props: user agent record + live metrics from `agentStore`
- Shows: icon, name, risk level badge, strategy prompt excerpt, live P&L, win streak, loop status
- **PAUSE** / **RESUME** — calls `registry.pauseAgent/resumeAgent` via MetaMask; ownership enforced on-chain
- **FUND** — input for STT amount; calls `coordinator.fund()` via MetaMask

### `CreateAgentModal.tsx`

- Props: `walletAddress: string`, `onClose: () => void`
- Step 1 — Define: emoji icon picker, risk level slider (1–5), free-text strategy prompt textarea
- Step 2 — Deploy: calls `useUserAgents.createAgent()` which sends the `AgentRegistry.registerAgent()` tx via MetaMask; shows tx hash on success

### `AdminPanel.tsx`

- Props: `walletAddress: string`
- Visible only when the connected wallet matches `NEXT_PUBLIC_DEPLOYER_ADDRESS`
- Reads: `agentStore.agents` for per-agent status
- Bulk controls: **PAUSE ALL** / **RESUME ALL** via signed `signAndPost()` to backend admin endpoints
- Renders one `AdminAgentRow` per system agent

### `AdminAgentRow.tsx`

- Props: `agentId: string`, `walletAddress: string`
- Per-agent PAUSE / RESUME / FUND controls using `signAndPost()` for each action
- Shows current loop status and coordinator balance

### `ActivityFeed.tsx`

- Reads: `feedStore.items` (first 20)
- Horizontal scroll, color-coded by category:
  - `order` → blue
  - `trade` → emerald
  - `coalition` → orange
  - `warning` → yellow
  - `event` → violet
  - `system` → gray
- Items with `tx_hash` render the timestamp as a link to `${NEXT_PUBLIC_SOMNIA_EXPLORER}/tx/{tx_hash}` with an `ExternalLink` icon

---

## TradingView v5 Notes

This project uses `lightweight-charts@5.x`. The v5 API broke compatibility with v4:

- **Use** `chart.addSeries(CandlestickSeries, options)` — not `chart.addCandlestickSeries()`
- **Use** `series.update(bar)` for live ticks — calling `setData()` repeatedly causes visible flicker
- **Always** import with `dynamic(..., { ssr: false })` — the library accesses `window` and breaks SSR
- `CandlestickSeries` must be imported from `lightweight-charts` as a named export

---

## Adding a New System Agent

1. **`lib/types.ts`**: Add new id to the `AgentState["agent_id"]` union type
2. **`store/agentStore.ts`**: Add `{ agent_id: 'new_id', agent_name: 'Display Name' }` to `AGENT_DEFAULTS`; `makeDefaultAgent` already initialises all new fields
3. **`components/agents/AgentGrid.tsx`**: Add new `agent_id` to the ordered array
4. **`components/agents/AgentCard.tsx`**: Add emoji to `AGENT_ICONS`, color class to `AGENT_COLORS`, hover glow to `AGENT_GLOW`, and strategy description to `AGENT_STRATEGIES`
5. **`components/agents/AgentScoreboard.tsx`**: Add emoji to `AGENT_ICONS`, extend `MEDALS` array
6. Backend: add to `AGENT_CONFIGS` in `orchestrator.py` + `config.py` + `.env` + `deploy.js` (`registerAgent`)

---

## Adding a New WebSocket Message Type

1. **`lib/types.ts`**: Add new type to the `WSMessage` discriminated union
2. **`hooks/useWebSocket.ts`**: Add a `case "your_type":` to the dispatch switch, call the appropriate store action
3. If new data needs a store: add state + action to the relevant store (or create a new one)
