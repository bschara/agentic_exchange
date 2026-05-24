// Platform daemon — keeps agent loops running autonomously on a local Hardhat node.
// Watches MockPlatform.RequestCreated events and immediately fires the appropriate callback,
// simulating what the real Somnia platform does on testnet.
//
// Run AFTER deploy-local.js (in a separate terminal, no Hardhat needed):
//   node scripts/platform-daemon.js
//
// Leave running while testing. The backend's startup triggers kick off the first cycle per agent;
// the daemon keeps all 4 on-chain loops alive indefinitely. (noise_trader uses a Python loop.)

import { ethers } from 'ethers';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const RPC_URL = process.env.SOMNIA_RPC_URL || 'http://127.0.0.1:8545';
const DEPLOYER_PK = '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80';

// Live ETH/USD price fetched from CoinGecko — updated on every price callback request.
// Falls back to previous value if the API is unreachable.
let _latestEthPrice = 3500;
let _lastOnChainPrice = 0; // updated from TradeExecuted events

async function fetchEthPrice() {
  try {
    const res = await fetch(
      'https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd'
    );
    const data = await res.json();
    if (data?.ethereum?.usd) {
      _latestEthPrice = data.ethereum.usd;
    }
  } catch { /* keep previous price on network error */ }
  return Math.round(_latestEthPrice); // coordinator expects whole-dollar integer
}

// Implements each agent's strategy from its system prompt so local decisions
// match what the real on-chain LLM would decide given the same price data.
function makeDecision(agentId, refPrice, onChainPrice) {
  const ref = refPrice;
  const oc  = onChainPrice > 0 ? onChainPrice : refPrice;

  switch (agentId) {
    case 'market_maker':
      // BUY if on-chain is below reference (underpriced), SELL if above
      return oc < ref ? 'BUY' : 'SELL';

    case 'momentum_trader':
      // Follow on-chain strength: BUY when on-chain is at/above reference (contrarian to market_maker)
      return oc >= ref ? 'BUY' : 'SELL';

    case 'arbitrage_agent':
      // BUY if on-chain underpriced vs reference, SELL if overpriced
      return oc < ref ? 'BUY' : 'SELL';

    case 'risk_manager':
      // Support market if on-chain is >$5 below ref; resist spike if >$5 above
      if (oc < ref - 5) return 'BUY';
      if (oc > ref + 5) return 'SELL';
      // Neutral zone: mirror momentum_trader (contrarian to market_maker/arb)
      return oc >= ref ? 'BUY' : 'SELL';

    case 'noise_trader':
      return Math.floor(ref) % 2 === 0 ? 'BUY' : 'SELL';

    default:
      return Math.random() < 0.5 ? 'BUY' : 'SELL';
  }
}

// Maps requestId → agentId so makeDecision can use the right strategy
const _requestToAgent = new Map();

async function main() {
  const deploymentPath = path.join(__dirname, '../deployments/somnia-local.json');
  if (!fs.existsSync(deploymentPath)) {
    console.error('somnia-local.json not found. Run deploy-local.js first.');
    process.exit(1);
  }
  const dep = JSON.parse(fs.readFileSync(deploymentPath));

  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const wallet = new ethers.Wallet(DEPLOYER_PK, provider);
  // NonceManager tracks nonces in-memory after the first fetch, avoiding provider cache staleness
  // that causes "nonce too low" when two queue items fire in rapid succession.
  const managedWallet = new ethers.NonceManager(wallet);

  const mockPlatform = new ethers.Contract(
    dep.contracts.MockPlatform.address,
    dep.abis.MockPlatform,
    managedWallet
  );
  const coordinator = new ethers.Contract(
    dep.contracts.AgentCoordinator.address,
    dep.abis.AgentCoordinator,
    provider
  );
  const exchange = new ethers.Contract(
    dep.contracts.Exchange.address,
    dep.abis.Exchange,
    provider
  );

  // Compute selectors for handlePriceData and handleDecision so we can route requests
  const handlePriceDataSel = coordinator.interface.getFunction('handlePriceData').selector;
  const handleDecisionSel  = coordinator.interface.getFunction('handleDecision').selector;

  console.log('');
  console.log('╔══════════════════════════════════════════════════════╗');
  console.log('║          Somnia MockPlatform Daemon                  ║');
  console.log('║   Auto-firing price + LLM callbacks locally         ║');
  console.log('╚══════════════════════════════════════════════════════╝');
  console.log('');
  console.log('MockPlatform: ', dep.contracts.MockPlatform.address);
  console.log('Coordinator:  ', dep.contracts.AgentCoordinator.address);
  console.log('RPC:          ', RPC_URL);
  console.log('');
  console.log('Listening for RequestCreated events...');
  console.log('');

  // Sequential processing queue with per-request deduplication.
  // _inFlight prevents the same requestId from being enqueued twice (live listener + replay race).
  let queue = Promise.resolve();
  const _inFlight = new Set();
  const enqueue = (reqId, fn) => {
    const key = String(reqId);
    if (_inFlight.has(key)) {
      console.log(`[Skip  ] reqId=${key} already in-flight — duplicate suppressed`);
      return;
    }
    _inFlight.add(key);
    queue = queue
      .then(fn)
      .catch((err) => console.error('Queue error:', err.message))
      .finally(() => _inFlight.delete(key));
  };

  // On startup, check the coordinator's on-chain pending mappings and only replay requests
  // that are actually awaiting a callback. Avoids nonce collisions from redundant transactions.
  async function replayPending() {
    try {
      const events = await mockPlatform.queryFilter(mockPlatform.filters.RequestCreated(), 0, 'latest');
      if (events.length === 0) { console.log('No historical requests found.'); return; }

      const pending = [];
      for (const ev of events) {
        const { requestId, callbackSelector: sel } = ev.args;
        try {
          if (sel === handlePriceDataSel) {
            const req = await coordinator.pendingPriceRequests(requestId);
            if (req.exists) pending.push({ requestId, sel });
          } else if (sel === handleDecisionSel) {
            const req = await coordinator.pendingLLMRequests(requestId);
            if (req.exists) pending.push({ requestId, sel });
          }
        } catch { /* skip — can't read state */ }
      }

      if (pending.length === 0) { console.log('No pending requests to replay.'); return; }
      console.log(`Replaying ${pending.length} pending request(s)...`);

      for (const { requestId, sel } of pending) {
        const rid = requestId;
        const s = sel;
        enqueue(rid, async () => {
          try {
            if (s === handlePriceDataSel) {
              const price = await fetchEthPrice();
              await (await mockPlatform.simulatePriceCallback(rid, price)).wait();
              console.log(`[Replay] priceReqId=${rid}  price=$${price}`);
            } else {
              const agentId  = _requestToAgent.get(rid.toString()) ?? 'unknown';
              const decision = makeDecision(agentId, _latestEthPrice, _lastOnChainPrice);
              await (await mockPlatform.simulateLLMCallback(rid, decision)).wait();
              console.log(`[Replay] llmReqId=${rid}  decision=${decision}`);
            }
          } catch (e) {
            console.error(`[Replay] reqId=${rid} failed:`, e.shortMessage || e.message.slice(0, 80));
          }
        });
      }
    } catch (e) {
      console.error('Replay scan failed:', e.message);
    }
  }

  // Track agentId per request so makeDecision can use the right strategy.
  // DecisionTriggered gives us the price-step requestId; LLMRequestFired gives us the LLM-step requestId.
  coordinator.on('DecisionTriggered', (requestId, agentId) => {
    _requestToAgent.set(requestId.toString(), agentId);
  });
  coordinator.on('LLMRequestFired', (llmRequestId, agentId) => {
    _requestToAgent.set(llmRequestId.toString(), agentId);
  });

  // Keep _lastOnChainPrice updated for strategy decisions.
  exchange.on('TradeExecuted', (_tradeId, _buyId, _sellId, _buyer, _seller, price) => {
    _lastOnChainPrice = Number(price) / 1e18;
  });

  mockPlatform.on('RequestCreated', (requestId, agentIdNum, callbackAddress, callbackSelector) => {
    enqueue(requestId, async () => {
      const reqIdStr = requestId.toString();

      if (callbackSelector === handlePriceDataSel) {
        const price = await fetchEthPrice();
        console.log(`[Price ] reqId=${reqIdStr}  price=$${price}  (${callbackAddress.slice(0, 10)}...)`);
        try {
          const tx = await mockPlatform.simulatePriceCallback(requestId, price);
          await tx.wait();
        } catch (e) {
          console.error(`[Price ] reqId=${reqIdStr} FAILED:`, e.message);
        }

      } else if (callbackSelector === handleDecisionSel) {
        const agentId  = _requestToAgent.get(reqIdStr) ?? 'unknown';
        const decision = makeDecision(agentId, _latestEthPrice, _lastOnChainPrice);
        console.log(`[LLM   ] reqId=${reqIdStr}  agent=${agentId}  decision=${decision}  ref=$${_latestEthPrice}  onChain=$${_lastOnChainPrice.toFixed(2)}`);
        try {
          const tx = await mockPlatform.simulateLLMCallback(requestId, decision);
          await tx.wait();
          _requestToAgent.delete(reqIdStr);
        } catch (e) {
          console.error(`[LLM   ] reqId=${reqIdStr} FAILED:`, e.message);
        }

      } else {
        console.log(`[?     ] reqId=${reqIdStr}  unknown selector=${callbackSelector} — skipping`);
      }
    });
  });

  // Replay any events that fired before this daemon subscribed
  await replayPending();

  // Listen for key coordinator events and log them
  coordinator.on('DecisionExecuted', (requestId, agentId, decision, price, orderId) => {
    const priceUsd = price > 0n ? `$${(Number(price) / 1e18).toFixed(2)}` : 'HOLD';
    console.log(`  ✓ DecisionExecuted  agent=${agentId}  decision=${decision}  price=${priceUsd}  orderId=${orderId}`);
  });

  coordinator.on('LoopStopped', (agentId, reason, balance) => {
    console.log(`  ✗ LoopStopped       agent=${agentId}  reason="${reason}"  balance=${ethers.formatEther(balance)} ETH`);
  });

  // Keep process alive
  await new Promise(() => {});
}

main().catch((e) => { console.error(e); process.exit(1); });
