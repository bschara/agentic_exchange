# Demo Script — Agentic Exchange

**Duration:** 5 minutes  
**Audience:** Hackathon judges / Somnia hiring managers

---

## Pre-Flight Checklist (5 minutes before)

- [ ] `curl http://localhost:8000/health` → `{"status":"ok","agents_running":4}`
- [ ] All 4 agent cards show reasoning text (not blank)
- [ ] At least one tx hash is visible and clickable in an agent card
- [ ] Somnia explorer opens correctly when tx hash is clicked
- [ ] Chart is rendering live candles (not frozen)
- [ ] Activity feed is scrolling with new entries

If any agent is blank: wait 30s after startup for all 4 to complete their first loop (they stagger 2s apart). If still blank after 60s, check `ANTHROPIC_API_KEY` in `backend/.env`.

---

## Setup (before demo)

1. Run `./start.sh` — both services running
2. Open http://localhost:3000 in Chrome (full screen)
3. Verify agents have been running for 2+ minutes (reasoning panels show text)
4. Confirm at least one tx hash is visible in an agent card

---

## Minute 0:00 — Open with the narrative

> "What you're looking at is **Agentic Exchange** — four autonomous AI agents running real trades on the Somnia blockchain, right now, without any human input."

> "The question we're answering: **Why does Somnia need to exist?**"
> "Because autonomous AI agents need real-time onchain execution. Traditional chains are too slow for this."

---

## Minute 0:30 — Walk through the dashboard

Point to each section:

- **Chart (top left):** "Live candlestick chart — each bar is 5 seconds of real price movement driven by our price engine"
- **Order Book (bottom left):** "Live bid-ask depth. Every level you see is an order placed or modified by an agent."
- **Agent Cards (right):** "Four agents, each with a different strategy. Each one is running a LangGraph loop — observe market → reason with Claude claude-sonnet-4-6 → decide → execute onchain → broadcast reasoning."
- **Activity Feed (bottom):** "Every line is a real agent action from the last few seconds."

---

## Minute 1:00 — Show a transaction on Somnia explorer

Point to an agent card that has a tx hash visible.

> "Every reasoning step ends in a real onchain transaction. Watch this."

Click the tx hash → Somnia explorer opens.

> "That's chain 50312. Somnia testnet. The transaction is permanent, on-chain, indexed."
> "This agent placed a limit order. The reasoning panel shows exactly why."

---

## Minute 1:30 — Let agents run, narrate what you see

Watch the reasoning panels update naturally.

> "Notice how the reasoning changes between loops. The market maker is adjusting its spread. The momentum trader is watching for a trend. The risk manager is monitoring everyone's exposure."

> "This is fully autonomous — I'm not touching anything."

---

## Minute 2:00 — Inject WHALE BUY event

Click the **WHALE BUY +3%** button.

> "Now I'm going to inject a market event. Watch."

_Chart spikes +3% immediately._

Wait 8-16 seconds for agents to react. Then point to the reasoning panels:

> "Momentum-Alpha: 'Price breakout detected above 5-bar high, entering long position.'"

> "Risk-Shield just sent a warning: 'Elevated volatility, all agents reduce position sizes.'"

> "MM-Prime received that warning and widened its spread from 0.2% to 0.8%."

> "Three agents. Three autonomous decisions. Three onchain transactions. No human input."

---

## Minute 3:00 — Inject FLASH CRASH

Click **FLASH CRASH**.

> "Let's stress-test this. Flash crash."

Watch agents scramble — activity feed lights up.

> "The risk manager just triggered a high-severity warning. The momentum trader is cancelling its long. The arbitrage agent is looking for gaps to exploit."

> "This is what agent-to-agent coordination looks like. Risk Shield broadcasts a message into the shared state bus. Every other agent observes it on their next loop."

---

## Minute 4:00 — Tie it back to Somnia

> "Why Somnia? Traditional EVM chains have 12-15 second block times. An agent loop that places an order and waits for confirmation takes 30+ seconds per decision."

> "Somnia's real-time execution means agents can run at 8-second loops — fast enough to actually react to market events. That's not possible anywhere else."

> "Autonomous AI needs fast, cheap, finalized transactions. That's Somnia's exact value proposition. We built this to prove it."

---

## Minute 5:00 — Close strong

> "Agentic Exchange: autonomous AI agents, real Claude reasoning, real onchain transactions, real-time dashboard. Live right now on Somnia chain 50312."

> "The future of DeFi isn't humans clicking buttons. It's agents like these, running 24/7, collaborating and competing, executing in real-time."

> "Somnia makes that possible."

---

## Backup talking points

- **"Is this simulated?"** → No. Every tx hash links to a real Somnia explorer entry. The price engine is synthetic (GBM), but all orders and trades are onchain.
- **"What model powers the agents?"** → Claude claude-sonnet-4-6 by Anthropic. Each agent has a unique system prompt defining its strategy.
- **"How does agent coordination work?"** → Risk Manager writes warnings to a shared `MarketStateBus` (in-memory async-safe state). Every other agent reads those warnings in their `observe` step and passes them to Claude as context. Decide node also enforces 50% order size reduction on any active warning, regardless of what Claude says. So it's both LLM-level coordination (Claude knows about the warning) and rule-level enforcement.
- **"What happens if Somnia testnet is down?"** → Simulation mode: flip one env var (`SIMULATION_MODE=true` in `backend/.env`), fake tx hashes are generated. Dashboard looks identical. We built this specifically as a demo reliability fallback.
- **"How does agent coordination work in detail?"** → There are three layers: (1) `MarketStateBus` — shared in-memory state that all agents observe each loop; (2) warning propagation — Risk Manager writes a structured warning object that other agents receive as part of their Claude context; (3) rule enforcement — `decide_node` automatically halves order sizes when a warning is active, regardless of Claude's output. So even if Claude doesn't act on the warning, the system enforces safe behavior.
- **"What happens if an agent wallet runs out of gas?"** → The `observe_node` checks the onchain balance each loop. If it drops below 0.01 STT, the agent is forced to `hold` — no orders are placed. This is a hard guard in `decide_node` before any tx is attempted. The agent continues running (reasoning is still visible), it just sits out until refunded.
