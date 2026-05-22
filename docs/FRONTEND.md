# Frontend — Agentic Exchange

Next.js 14 App Router dashboard displaying four autonomous AI trading agents running on the Somnia blockchain in real-time.

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
│   │   └── ActivityFeed.tsx # Horizontal scrolling feed bar (color-coded by category)
│   ├── chart/
│   │   ├── CandlestickChart.tsx  # TradingView Lightweight Charts v5 (SSR-disabled)
│   │   ├── OrderBook.tsx         # Bid/ask depth with proportional size bars
│   │   └── RecentTrades.tsx      # Scrollable recent trades list with buyer/seller agent attribution
│   └── agents/
│       ├── AgentGrid.tsx         # 2-column grid container for 4 agent cards
│       ├── AgentCard.tsx         # Stats + decision history + tx hash per agent
│       ├── AgentScoreboard.tsx   # P&L leaderboard ranked by trade_pnl, shows volume + latency
│       ├── ReasoningPanel.tsx    # Decision history (last 20 entries, fadeIn on newest)
│       └── AgentStatusBadge.tsx  # THINKING / EXECUTING / IDLE badge with animations
├── store/
│   ├── marketStore.ts       # Zustand: candles, orderBook, trades, price, connection
│   ├── agentStore.ts        # Zustand: agent states, decision history, coordinator metrics
│   └── feedStore.ts         # Zustand: activity feed items
├── hooks/
│   └── useWebSocket.ts      # WS connect/reconnect, message dispatch, injectEvent()
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

| Variable                      | Default                                   | Purpose                    |
| ----------------------------- | ----------------------------------------- | -------------------------- |
| `NEXT_PUBLIC_WS_URL`          | `ws://localhost:8000/ws`                  | Backend WebSocket endpoint |
| `NEXT_PUBLIC_API_URL`         | `http://localhost:8000`                   | Backend HTTP base URL      |
| `NEXT_PUBLIC_SOMNIA_EXPLORER` | `https://shannon-explorer.somnia.network` | Base URL for tx hash links |

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

| State field          | Type                           | Description                                              |
| -------------------- | ------------------------------ | -------------------------------------------------------- |
| `agents`             | `Record<agent_id, AgentState>` | Full agent state from latest `chain_metrics`             |
| `decisionHistory`    | `Record<agent_id, string[]>`   | Last 20 `"BUY @ $3245"` entries, derived from diffs      |
| `coordinatorBalance` | `number`                       | STT remaining in coordinator                             |
| `totalLocked`        | `number`                       | Total STT in treasury                                    |
| `loopStoppedAny`     | `boolean`                      | True if any agent's loop has stopped                     |
| `recentFills`        | `Fill[]`                       | Last 20 matched trades with buyer/seller agent IDs       |
| `somniaBlockMs`      | `number`                       | Block time in ms (for latency display)                   |

`updateFromChainMetrics(metrics)` is the single update entry point — called on every `chain_metrics` WS message.

### `store/feedStore.ts`

| State field | Type                 | Description                        |
| ----------- | -------------------- | ---------------------------------- |
| `items`     | `ActivityFeedItem[]` | Ring buffer, max 100, newest first |

---

## WebSocket Message Dispatch

Connection managed in `hooks/useWebSocket.ts`. Auto-reconnects 3s after close. Sends keepalive ping every 30s.

| `msg.type`        | Action                                                                                                                         |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `market_snapshot` | `marketStore.setMarketSnapshot(msg.data)`                                                                                      |
| `candle`          | `marketStore.addCandle(msg.data)`                                                                                              |
| `chain_metrics`   | `agentStore.updateFromChainMetrics(msg.data)` — also diffs per-agent `decisions_total` to push new decision entries to `feedStore` and `loop_stopped` transitions as warnings |
| `risk_warning`    | `feedStore.addItem(...)` as `category: "warning"` — kept for forward-compat; not currently sent by backend                    |
| `event_injected`  | `feedStore.addItem(...)` as `category: "event"`                                                                                |

**Sending events:** `useWebSocket` exports `injectEvent(type)` which POSTs to `POST /events/inject`. Called by the Header buttons.

---

## Component Reference

### `Header.tsx`

- Reads: `marketStore.currentPrice`, `marketStore.isConnected`, `marketStore.priceChange24h`, `marketStore.volume24h`
- Uses: `useWebSocket().injectEvent`
- 5 event buttons (WHALE BUY, WHALE SELL, VOL SPIKE, NEWS EVENT, FLASH CRASH) each with a 10s cooldown after click (shows "INJECTING..." and disables)

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
- Fixed rendering order: `market_maker`, `momentum_trader`, `arbitrage_agent`, `risk_manager`

### `AgentCard.tsx`

- Props: `agent: AgentState`
- Per-agent color coding: market_maker=blue, momentum_trader=emerald, arbitrage_agent=violet, risk_manager=yellow
- Stats: decisions total, BUY/SELL/HOLD counts, treasury balance, last decision + price
- Contains `ReasoningPanel` and `AgentStatusBadge`

### `AgentScoreboard.tsx`

- Reads: `agentStore.agents`
- Ranks all 4 agents by `trade_pnl` (highest first) with medal emojis
- Shows per-agent: P&L (colored green/red), buy volume, sell volume, avg decision latency (`avg_decision_latency_ms`) if non-zero
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

---


## TradingView v5 Notes

This project uses `lightweight-charts@5.x`. The v5 API broke compatibility with v4:

- **Use** `chart.addSeries(CandlestickSeries, options)` — not `chart.addCandlestickSeries()`
- **Use** `series.update(bar)` for live ticks — calling `setData()` repeatedly causes visible flicker
- **Always** import with `dynamic(..., { ssr: false })` — the library accesses `window` and breaks SSR
- `CandlestickSeries` must be imported from `lightweight-charts` as a named export

---

## Adding a New Agent

1. **`store/agentStore.ts`**: Add entry to `AGENT_DEFAULTS`
2. **`components/agents/AgentGrid.tsx`**: Add new `agent_id` to the ordered array
3. **`components/agents/AgentCard.tsx`**: Add emoji to the icon map and color to the color map
4. **`components/agents/AgentScoreboard.tsx`**: Add emoji to `AGENT_ICONS`
5. **`lib/types.ts`**: Add new id to the `AgentState["agent_id"]` union type
6. Backend: add to `AGENT_CONFIGS` in `orchestrator.py` + `config.py` + `.env` + `deploy.js` (`setSystemPrompt`)

---

## Adding a New WebSocket Message Type

1. **`lib/types.ts`**: Add new type to the `WSMessage` discriminated union
2. **`hooks/useWebSocket.ts`**: Add a `case "your_type":` to the dispatch switch, call the appropriate store action
3. If new data needs a store: add state + action to the relevant store (or create a new one)
