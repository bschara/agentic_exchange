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
│   │   ├── LatencyHero.tsx  # Full-width latency comparison: Somnia vs Solana vs Ethereum (NEW)
│   │   └── ActivityFeed.tsx # Horizontal scrolling feed bar; tx hashes link to Somnia explorer
│   ├── chart/
│   │   ├── CandlestickChart.tsx  # TradingView Lightweight Charts v5 (SSR-disabled)
│   │   ├── OrderBook.tsx         # Bid/ask depth with proportional size bars
│   │   └── RecentTrades.tsx      # Scrollable recent trades list with buyer/seller agent attribution
│   └── agents/
│       ├── AgentGrid.tsx         # 2-column grid container for 5 agent cards
│       ├── AgentCard.tsx         # Strategy desc + stats (4 cols incl position) + decision history
│       ├── AgentScoreboard.tsx   # P&L leaderboard ranked by total P&L (realized + unrealized)
│       ├── ReasoningPanel.tsx    # Decision history (last 20 entries, fadeIn on newest)
│       └── AgentStatusBadge.tsx  # THINKING / EXECUTING / IDLE badge with animations
├── store/
│   ├── marketStore.ts       # Zustand: candles, orderBook, trades, price, connection
│   ├── agentStore.ts        # Zustand: agent states, decision history, coordinator metrics
│   └── feedStore.ts         # Zustand: activity feed items
├── hooks/
│   ├── useWebSocket.ts      # WS connect/reconnect, message dispatch, injectEvent()
│   └── useAdminActions.ts   # Wallet connect + MetaMask personal_sign for admin actions
├── types/
│   └── global.d.ts          # EthereumProvider interface + window.ethereum type declaration
├── lib/
│   ├── types.ts             # All TypeScript interfaces (CandleData, AgentState, ChainMetrics, etc.)
│   └── utils.ts             # cn() helper for className merging
└── components/ui/
    ├── badge.tsx            # Simple Badge component (default/outline variants)
    └── button.tsx           # Simple Button component (default/outline/ghost + sizes)
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

| Variable                        | Default                                   | Purpose                                                                                               |
| ------------------------------- | ----------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `NEXT_PUBLIC_WS_URL`            | `ws://localhost:8000/ws`                  | Backend WebSocket endpoint                                                                            |
| `NEXT_PUBLIC_API_URL`           | `http://localhost:8000`                   | Backend HTTP base URL                                                                                 |
| `NEXT_PUBLIC_SOMNIA_EXPLORER`   | `https://shannon-explorer.somnia.network` | Base URL for tx hash links                                                                            |
| `NEXT_PUBLIC_DEPLOYER_ADDRESS`  | `` (empty)                               | Deployer's public address; when a connected wallet matches this, admin controls become visible in the Header |

---

## State Management

Three Zustand stores, all initialized with fake seed data from `lib/fake-data.ts` so the dashboard is never blank:

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
| `agents`             | `Record<agent_id, AgentState>` | Full agent state from latest `chain_metrics` (5 agents)        |
| `decisionHistory`    | `Record<agent_id, string[]>`   | Last 20 `"BUY @ $3245"` entries, derived from diffs            |
| `coordinatorBalance` | `number`                       | STT remaining in coordinator                                   |
| `totalLocked`        | `number`                       | Total STT in treasury                                          |
| `loopStoppedAny`     | `boolean`                      | True if any agent's loop has stopped                           |
| `recentFills`        | `Fill[]`                       | Last 20 matched trades with buyer/seller agent IDs + `tx_hash` |
| `somniaBlockMs`      | `number`                       | Block time in ms (for latency display)                         |

Per-agent `AgentState` also includes: `net_position` (float, positive = long), `unrealized_pnl` (mark-to-market), `wallet_address` (for explorer link fallback).

`updateFromChainMetrics(metrics)` is the single update entry point — called on every `chain_metrics` WS message.

### `store/feedStore.ts`

| State field | Type                 | Description                        |
| ----------- | -------------------- | ---------------------------------- |
| `items`     | `ActivityFeedItem[]` | Ring buffer, max 100, newest first |

---

## WebSocket Message Dispatch

Connection managed in `hooks/useWebSocket.ts`. Auto-reconnects 3s after close. Sends keepalive ping every 30s.

| `msg.type`        | Action                                                                                                                                                                                                         |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `market_snapshot` | `marketStore.setMarketSnapshot(msg.data)`                                                                                                                                                                      |
| `candle`          | `marketStore.addCandle(msg.data)`                                                                                                                                                                              |
| `chain_metrics`   | `agentStore.updateFromChainMetrics(msg.data)` — also diffs per-agent `decisions_total` to push new entries to `feedStore` (including `tx_hash` from `recent_fills`) and `loop_stopped` transitions as warnings |
| `risk_warning`    | `feedStore.addItem(...)` as `category: "warning"` — emitted by backend on spread > 2% (`HIGH_SPREAD`) or volatility spike > 2% (`VOLATILITY_SPIKE`)                                                            |
| `event_injected`  | `feedStore.addItem(...)` as `category: "event"`                                                                                                                                                                |

**Sending events:** `useWebSocket` exports `injectEvent(type)` which POSTs to `POST /events/inject`. Called by the Header buttons.

---

## Admin Actions (`hooks/useAdminActions.ts`)

Handles MetaMask wallet connection and signed admin API calls.

**`connectWallet() → string`** — calls `window.ethereum.request({ method: 'eth_requestAccounts' })`, returns the connected address.

**`isOwnerAddress(address: string) → boolean`** — returns true when `address.toLowerCase() === NEXT_PUBLIC_DEPLOYER_ADDRESS.toLowerCase()`. Used by Header to gate the admin control panel.

**`signAndPost(address, action, url, body?)`** — internal helper:
1. Builds message: `"admin:<action>:<unix_timestamp>"`
2. Calls `window.ethereum.request({ method: 'personal_sign', params: [message, address] })`
3. POSTs to `${API_URL}${url}` with headers `X-Admin-Sig`, `X-Admin-Message`, `X-Admin-Address`

**`pauseAll(address)`** / **`resumeAll(address)`** / **`fundAll(address, amount)`** — thin wrappers over `signAndPost` targeting the corresponding backend endpoints.

**`global.d.ts`** declares the `EthereumProvider` interface (`request()`, `on()`, `removeListener()`, `isMetaMask`) and extends `Window` with `ethereum?: EthereumProvider`, giving the TypeScript compiler a typed `window.ethereum`.

---

## Component Reference

### `Header.tsx`

- Reads: `marketStore.currentPrice`, `marketStore.isConnected`, `marketStore.priceChange24h`, `marketStore.volume24h`
- Uses: `useWebSocket().injectEvent`, `useAdminActions`
- 5 event buttons (WHALE BUY, WHALE SELL, VOL SPIKE, NEWS EVENT, FLASH CRASH) each with a 10s cooldown after click (shows "INJECTING..." and disables)
- **Admin controls** (visible only when deployer wallet is connected):
  - **CONNECT WALLET** button — calls `connectWallet()` via `window.ethereum.request({ method: 'eth_requestAccounts' })`; shows wallet address on success
  - **PAUSE ALL** / **RESUME ALL** — calls `signAndPost()` with action `"pause-all"` / `"resume-all"`; signs a timestamped message via MetaMask
  - **FUND ALL** — input field for AGT amount + button; calls `signAndPost()` with action `"fund-all"` and body `{ amount }`
  - All admin buttons share an `adminLoading` state that disables them during in-flight requests

### `LatencyHero.tsx`

- Full-width panel rendered between `<Header />` and the main content grid in `page.tsx`
- Reads: `agentStore.agents`, `agentStore.recentFills`, `agentStore.somniaBlockMs`
- Computes `avgLatencyMs` = mean of `avg_decision_latency_ms` across agents with at least one recorded decision
- Displays an animated latency number (emerald, tabular-nums) that restarts `animate-pulse` on each new fill via `key={fillKey}` remount trick
- Three proportional comparison bars: Somnia (emerald, actual ms), Solana (~400 ms, fixed 3.3%), Ethereum (~12,000 ms, fixed 100%)
- Shows last fill price and buyer vs seller agent names when fills are available

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
- Time-ago: "5s", "2m", "1h"

### `AgentGrid.tsx`

- Reads: `agentStore.agents`
- Fixed rendering order: `market_maker`, `momentum_trader`, `arbitrage_agent`, `risk_manager`, `noise_trader`
- 5 agents render in a 2-column grid (2+2+1 layout on xl screens)

### `AgentCard.tsx`

- Props: `agent: AgentState`
- Per-agent color coding: market_maker=blue, momentum_trader=emerald, arbitrage_agent=violet, risk_manager=yellow, noise_trader=pink
- Strategy description line rendered below agent name (e.g. "Posts bid AND ask simultaneously. Profits from the spread.")
- Stats: decisions total, BUY/SELL/HOLD counts, **AGT balance** (`agt_balance` — coordinator's pool for on-chain agents, individual wallet for noise_trader), **net position** (LONG/SHORT/FLAT badge)
- Last decision + price shown in header
- Contains `ReasoningPanel` and `AgentStatusBadge`

### `AgentScoreboard.tsx`

- Reads: `agentStore.agents`
- Ranks all 5 agents by `trade_pnl + unrealized_pnl` (highest first) with medal emojis (🥇🥈🥉4️⃣5️⃣)
- Shows per-agent: realized P&L, unrealized P&L (shown when abs > 0.01), buy volume, sell volume, avg decision latency
- Row background tints green (profitable) or red (losing) based on P&L threshold
- Shows "waiting for first trades…" until any agent has fills

### `AgentStatusBadge.tsx`

- Props: `status: 'THINKING' | 'EXECUTING' | 'IDLE'`
- THINKING: yellow pulsing dot
- EXECUTING: emerald ping dot
- IDLE: gray static dot

### `ReasoningPanel.tsx`

- Props: `agentId: string`
- Reads: `agentStore.reasoningHistory[agentId]`
- Shows 4 most recent entries; newest has `fadeIn` animation and brighter text

### `ActivityFeed.tsx`

- Reads: `feedStore.items` (first 20)
- Horizontal scroll, color-coded by category:
  - `order` → blue
  - `trade` → emerald
  - `warning` → yellow
  - `event` → violet
  - `system` → gray
- Items with `tx_hash` render the timestamp as a link to `https://shannon-explorer.somnia.network/tx/{tx_hash}` with an `ExternalLink` icon (configurable via `NEXT_PUBLIC_SOMNIA_EXPLORER`)

---

## TradingView v5 Notes

This project uses `lightweight-charts@5.x`. The v5 API broke compatibility with v4:

- **Use** `chart.addSeries(CandlestickSeries, options)` — not `chart.addCandlestickSeries()`
- **Use** `series.update(bar)` for live ticks — calling `setData()` repeatedly causes visible flicker
- **Always** import with `dynamic(..., { ssr: false })` — the library accesses `window` and breaks SSR
- `CandlestickSeries` must be imported from `lightweight-charts` as a named export

---

## Adding a New Agent

1. **`lib/types.ts`**: Add new id to the `AgentState["agent_id"]` union type
2. **`store/agentStore.ts`**: Add `{ agent_id: 'new_id', agent_name: 'Display Name' }` to `AGENT_DEFAULTS`; `makeDefaultAgent` already initialises all new fields (net_position, unrealized_pnl, wallet_address)
3. **`components/agents/AgentGrid.tsx`**: Add new `agent_id` to the ordered array (grid is xl:grid-cols-2 so odd counts are fine)
4. **`components/agents/AgentCard.tsx`**: Add emoji to `AGENT_ICONS`, color class to `AGENT_COLORS`, hover glow to `AGENT_GLOW`, and strategy description to `AGENT_STRATEGIES`
5. **`components/agents/AgentScoreboard.tsx`**: Add emoji to `AGENT_ICONS`, extend `MEDALS` array
6. Backend: add to `AGENT_CONFIGS` in `orchestrator.py` + `config.py` + `.env` + `deploy.js` (`setSystemPrompt`)

---

## Adding a New WebSocket Message Type

1. **`lib/types.ts`**: Add new type to the `WSMessage` discriminated union
2. **`hooks/useWebSocket.ts`**: Add a `case "your_type":` to the dispatch switch, call the appropriate store action
3. If new data needs a store: add state + action to the relevant store (or create a new one)
