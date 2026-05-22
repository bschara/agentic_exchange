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

If chain metrics are blank: wait 30s after startup for the first coordinator event poll cycle. If still blank, verify contract addresses are set in `backend/.env` and the coordinator has sufficient STT balance.

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

- **Chart (top left):** "Live candlestick chart — each bar is 5 seconds. When we're onchain, this chart is driven by real matched trades from the Exchange contract."
- **Order Book (bottom left):** "Live bid-ask depth from the on-chain LOB. These are real orders sitting in `Exchange.sol`."
- **Agent Cards (right):** "Four agents, each with a different strategy. Notice the `⬡ ON-CHAIN LLM` badge on each card — that lights up violet when the last decision was validated by Somnia's on-chain LLM agent, not just an off-chain bot."
- **Activity Feed (bottom):** "Every line is a real agent action from the last few seconds."

---

## Minute 1:00 — Show a transaction on Somnia explorer

Point to an agent card that has a tx hash visible.

> "Every agent decision ends in a real onchain transaction. Watch this."

Click the tx hash → Somnia explorer opens.

> "That's chain 50312. Somnia testnet. The transaction is permanent, on-chain, indexed."

> "When we started the backend, Python fired one transaction per agent — `triggerAgentDecision()`. That's the last time Python ever touches the contracts. From that point, the agents run themselves."

> "Each cycle is three transactions, all on-chain. First: a JSON API agent fetches the real ETH price. Second: the price and on-chain order book state are fed to Somnia's LLM inference agent — validators reach consensus on BUY, SELL, or HOLD. Third: `handleDecision()` places the order on the Exchange LOB, then immediately fires `_retrigger()` to start the next cycle."

> "So the AI decision is on-chain, validated by a decentralized network. And the loop never stops — unless the coordinator runs out of STT, at which point it emits a `LoopStopped` event and halts gracefully."

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

> "Momentum-Alpha just went long — reference price is above the on-chain last trade, pure momentum."

> "Arb-Scanner is buying — it sees the on-chain price is below CoinGecko reference, gap to close."

> "Risk-Shield held steady — its on-chain price check was within $5 of reference, so it follows momentum."

> "Four agents. Four autonomous decisions. Four onchain transactions. No human input."

---

## Minute 3:00 — Inject FLASH CRASH

Click **FLASH CRASH**.

> "Let's stress-test this. Flash crash."

Watch agents scramble — activity feed lights up.

> "Watch the scoreboard — P&L is shifting. Arb-Scanner is buying the dip. Momentum-Alpha just flipped short."

> "Risk-Shield's on-chain price is now more than $5 below reference — it kicks in to support the market with a buy order."

> "Each agent is reacting to the same market signal but through a different strategy lens. All autonomous. All on-chain."

---

## Minute 4:00 — Tie it back to Somnia

> "Why Somnia? Two things no other chain can do."

> "First: an on-chain limit order book that matches orders in the same block they're placed. 12-15 second block times make that impossible — by the time the order lands, the market has moved. Somnia's sub-second finality makes real-time price discovery onchain possible."

> "Second: AI decisions validated by a decentralized network of validators. These agents aren't just off-chain bots pushing orders — their BUY/SELL/HOLD decisions go through Somnia's LLM inference agent, where validators reach consensus before the order is placed. That's verifiable, auditable, on-chain AI."

> "Autonomous AI needs fast finality AND trustless AI execution. That's exactly what Somnia delivers. We built this to prove both."

---

## Minute 5:00 — Close strong

> "Agentic Exchange: autonomous AI agents, on-chain LLM consensus, real onchain transactions, real-time dashboard. Live right now on Somnia chain 50312."

> "The future of DeFi isn't humans clicking buttons. It's agents like these, running 24/7, collaborating and competing, executing in real-time."

> "Somnia makes that possible."

---

## Backup talking points

- **"Is this simulated?"** → No. Every tx hash links to a real Somnia explorer entry. The price engine is GBM-based (for smooth animation), but when onchain, it anchors to real fill prices from Exchange.sol every 5 seconds. All orders and trades are onchain.
- **"Does Python keep calling the contract every loop?"** → No. Python fires one `triggerAgentDecision()` per agent at startup — that's it. After that, `handleDecision()` calls `_retrigger()` at the end of each cycle to fire the next one on-chain. The backend's only remaining jobs are the WebSocket dashboard and the event injection buttons.
- **"What happens if the coordinator runs out of STT?"** → It emits `LoopStopped(agentId, "Insufficient balance", balance)` and stops gracefully. No crash. Just fund it again via `AgentCoordinator.fund()` and fire a new `triggerAgentDecision()` to restart.
- **"What is the `⬡ ON-CHAIN LLM` badge?"** → Each agent card shows this badge indicating the agent's decisions are validated by Somnia's decentralized LLM inference agent — multi-validator consensus, fully on-chain. The Agent Scoreboard below shows real-time P&L ranking.
- **"What model powers the agents?"** → Somnia's on-chain LLM Inference Agent (base agent ID 2) — multi-validator consensus across Somnia's decentralized network. Each agent's strategy system prompt is stored in `AgentCoordinator.systemPrompts` and set at deploy time.
- **"How does agent coordination work?"** → Each agent uses a different strategy encoded in its on-chain system prompt. They don't communicate directly — they all react to the same on-chain market state (last trade price vs CoinGecko reference, best bid/ask). The interplay emerges naturally from their different strategies acting on the same data.
- **"What happens if the coordinator runs out of fuel?"** → `_retrigger()` checks `address(this).balance >= deposit × 2` before firing the next cycle. If underfunded, it emits `LoopStopped(agentId, "Insufficient balance", balance)` and halts gracefully. Fund via `AgentCoordinator.fund()` and restart.
