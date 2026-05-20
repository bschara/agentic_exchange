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
│   │   ├── Header.tsx       # Logo, live ticker, 5 event injection buttons
│   │   └── ActivityFeed.tsx # Horizontal scrolling feed bar (color-coded by category)
│   ├── chart/
│   │   ├── CandlestickChart.tsx  # TradingView Lightweight Charts v5 (SSR-disabled)
│   │   ├── OrderBook.tsx         # Bid/ask depth with proportional size bars
│   │   └── RecentTrades.tsx      # Scrollable recent trades list
│   └── agents/
│       ├── AgentGrid.tsx         # 2-column grid container for 4 agent cards
│       ├── AgentCard.tsx         # Stats + reasoning + tx hash per agent
│       ├── ReasoningPanel.tsx    # Reasoning history (4 entries, fadeIn on newest)
│       └── AgentStatusBadge.tsx  # THINKING / EXECUTING / IDLE badge with animations
├── store/
│   ├── marketStore.ts       # Zustand: candles, orderBook, trades, price, connection
│   ├── agentStore.ts        # Zustand: agent states, reasoning history
│   └── feedStore.ts         # Zustand: activity feed items
├── hooks/
│   └── useWebSocket.ts      # WS connect/reconnect, message dispatch, injectEvent()
├── lib/
│   ├── types.ts             # All TypeScript interfaces (CandleData, AgentState, etc.)
│   ├── fake-data.ts         # GBM seed data: candles, orderbook, agents, feed items
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

The dashboard renders immediately from fake seed data. Connect to the backend to see live agent updates.

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

| State field        | Type                           | Description                       |
| ------------------ | ------------------------------ | --------------------------------- |
| `agents`           | `Record<agent_id, AgentState>` | Latest state for each of 4 agents |
| `reasoningHistory` | `Record<agent_id, string[]>`   | Last 20 reasoning texts per agent |

`updateAgent(state)` updates by `agent_id`. `appendReasoning(id, text)` prepends and caps at 20.

### `store/feedStore.ts`

| State field | Type                 | Description                        |
| ----------- | -------------------- | ---------------------------------- |
| `items`     | `ActivityFeedItem[]` | Ring buffer, max 100, newest first |

---

## WebSocket Message Dispatch

Connection managed in `hooks/useWebSocket.ts`. Auto-reconnects 3s after close. Sends keepalive ping every 30s.

| `msg.type`        | Action                                                                           |
| ----------------- | -------------------------------------------------------------------------------- |
| `market_snapshot` | `marketStore.setMarketSnapshot(msg.data)`                                        |
| `candle`          | `marketStore.addCandle(msg.data)`                                                |
| `agent_update`    | `agentStore.updateAgent(msg.data)` + `agentStore.appendReasoning(id, reasoning)` |
| `activity_feed`   | `feedStore.addItem(msg.data)`                                                    |
| `risk_warning`    | `feedStore.addItem(...)` formatted as `category: "warning"`                      |
| `event_injected`  | `feedStore.addItem(...)` formatted as `category: "event"`                        |
| `pong`            | no-op                                                                            |

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
- Shows first 30 trades: price (colored by side), size, age
- Time-ago: "5s", "2m", "1h"

### `AgentGrid.tsx`

- Reads: `agentStore.agents`
- Fixed rendering order: `market_maker`, `momentum_trader`, `arbitrage_agent`, `risk_manager`

### `AgentCard.tsx`

- Props: `agent: AgentState`
- Per-agent color coding: market_maker=blue, momentum_trader=emerald, arbitrage_agent=violet, risk_manager=yellow
- Stats: balance (STT), position (with directional icon), session PnL (colored)
- Tx hash: truncated `0xabcd...1234`, links to `${NEXT_PUBLIC_SOMNIA_EXPLORER}/tx/${hash}`
- Contains `ReasoningPanel` and `AgentStatusBadge`

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

## Fake Seed Data (`lib/fake-data.ts`)

Generated once at module load — seeds stores so the dashboard is visually complete before the WebSocket connects:

- **`FAKE_CANDLES`**: 120 GBM candles starting at $100, σ=0.015, 5s bars
- **`FAKE_ORDER_BOOK`**: 10 bid/ask levels around the last fake candle close
- **`FAKE_TRADES`**: 20 trades with randomized side, price, and size
- **`FAKE_AGENTS`**: 4 `AgentState` objects with realistic reasoning text and varying positions
- **`FAKE_FEED_ITEMS`**: 5 sample activity items across different categories

---

## TradingView v5 Notes

This project uses `lightweight-charts@5.x`. The v5 API broke compatibility with v4:

- **Use** `chart.addSeries(CandlestickSeries, options)` — not `chart.addCandlestickSeries()`
- **Use** `series.update(bar)` for live ticks — calling `setData()` repeatedly causes visible flicker
- **Always** import with `dynamic(..., { ssr: false })` — the library accesses `window` and breaks SSR
- `CandlestickSeries` must be imported from `lightweight-charts` as a named export

---

## Adding a New Agent

1. **`lib/fake-data.ts`**: Add entry to `FAKE_AGENTS` with a new `agent_id`
2. **`store/agentStore.ts`**: No change needed — store is keyed by `agent_id` dynamically
3. **`components/agents/AgentGrid.tsx`**: Add new `agent_id` to the ordered array
4. **`components/agents/AgentCard.tsx`**: Add emoji to the icon map and color to the color map
5. **`lib/types.ts`**: Add new id to the `AgentState["agent_id"]` union type
6. Backend: add to `AGENT_CONFIGS` + `SYSTEM_PROMPTS` + config + .env

---

## Adding a New WebSocket Message Type

1. **`lib/types.ts`**: Add new type to the `WSMessage` discriminated union
2. **`hooks/useWebSocket.ts`**: Add a `case "your_type":` to the dispatch switch, call the appropriate store action
3. If new data needs a store: add state + action to the relevant store (or create a new one)
