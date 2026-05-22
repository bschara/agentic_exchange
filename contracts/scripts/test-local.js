// One-shot smoke test — runs one full decision cycle per agent and verifies results.
// Does NOT require platform-daemon.js to be running (handles callbacks manually).
//
// Run AFTER deploy-local.js:
//   npx hardhat run scripts/test-local.js --network localhost

import hre from 'hardhat';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const SIMULATED_PRICE = 3245; // $3245 ETH/USD
const DECISIONS = ['BUY', 'SELL', 'BUY', 'SELL']; // one per agent

async function parseEvent(receipt, contract, eventName) {
  for (const log of receipt.logs) {
    try {
      const parsed = contract.interface.parseLog({ topics: log.topics, data: log.data });
      if (parsed && parsed.name === eventName) return parsed.args;
    } catch {}
  }
  return null;
}

async function main() {
  const deploymentPath = path.join(__dirname, '../deployments/somnia-local.json');
  if (!fs.existsSync(deploymentPath)) {
    console.error('somnia-local.json not found. Run deploy-local.js first.');
    process.exit(1);
  }
  const dep = JSON.parse(fs.readFileSync(deploymentPath));

  const [deployer] = await hre.ethers.getSigners();

  const mockPlatform = new hre.ethers.Contract(
    dep.contracts.MockPlatform.address, dep.abis.MockPlatform, deployer
  );
  const coordinator = new hre.ethers.Contract(
    dep.contracts.AgentCoordinator.address, dep.abis.AgentCoordinator, deployer
  );
  const exchange = new hre.ethers.Contract(
    dep.contracts.Exchange.address, dep.abis.Exchange, deployer
  );

  const agentIds = ['market_maker', 'momentum_trader', 'arbitrage_agent', 'risk_manager'];
  const results = [];

  console.log('\n═══ Agent Loop Smoke Test ══════════════════════════════════');
  console.log(`Simulated ETH/USD price: $${SIMULATED_PRICE}\n`);

  for (let i = 0; i < agentIds.length; i++) {
    const agentId = agentIds[i];
    const decision = DECISIONS[i];
    console.log(`─── ${agentId} ───────────────────────────────────`);

    // Step 1: Trigger
    let tx = await coordinator.triggerAgentDecision(agentId);
    let receipt = await tx.wait();
    const triggered = await parseEvent(receipt, coordinator, 'DecisionTriggered');
    if (!triggered) { console.log('  ✗ DecisionTriggered event not found'); results.push({ agentId, pass: false }); continue; }
    const priceReqId = triggered.requestId;
    console.log(`  → DecisionTriggered  reqId=${priceReqId}`);

    // Step 2: Simulate price fetch callback
    tx = await mockPlatform.simulatePriceCallback(priceReqId, SIMULATED_PRICE);
    receipt = await tx.wait();
    const llmFired = await parseEvent(receipt, coordinator, 'LLMRequestFired');
    if (!llmFired) { console.log('  ✗ LLMRequestFired event not found'); results.push({ agentId, pass: false }); continue; }
    const llmReqId = llmFired.llmRequestId;
    console.log(`  → LLMRequestFired    reqId=${llmReqId}  price=$${llmFired.fetchedPrice}`);

    // Step 3: Simulate LLM decision callback
    tx = await mockPlatform.simulateLLMCallback(llmReqId, decision);
    receipt = await tx.wait();
    const executed = await parseEvent(receipt, coordinator, 'DecisionExecuted');
    const retrigger = await parseEvent(receipt, coordinator, 'DecisionTriggered');

    if (!executed) { console.log('  ✗ DecisionExecuted event not found'); results.push({ agentId, pass: false }); continue; }
    const orderPrice = executed.price > 0n ? `$${hre.ethers.formatEther(executed.price) * 1}` : 'N/A (HOLD)';
    console.log(`  → DecisionExecuted   decision=${executed.decision}  price=${orderPrice}  orderId=${executed.orderId}`);
    if (retrigger) console.log(`  → DecisionTriggered  (retrigger reqId=${retrigger.requestId})`);

    results.push({ agentId, decision: executed.decision, orderId: Number(executed.orderId), pass: true });
  }

  // Summary
  console.log('\n═══ Results ════════════════════════════════════════════════');
  console.log('Agent              Decision  OrderId  Pass');
  console.log('─────────────────────────────────────────────────────────');
  for (const r of results) {
    const status = r.pass ? '✓' : '✗';
    const dec = r.decision ?? '—';
    const oid = r.orderId != null ? r.orderId : '—';
    console.log(`  ${r.agentId.padEnd(20)} ${dec.padEnd(8)} ${String(oid).padEnd(8)} ${status}`);
  }

  // Check exchange has orders
  const [buys, asks] = await Promise.all([
    exchange.getActiveBuys().catch(() => []),
    exchange.getActiveSells().catch(() => []),
  ]);
  console.log(`\nExchange order book: ${buys.length} buy orders, ${asks.length} sell orders`);

  const allPass = results.every(r => r.pass);
  console.log(allPass ? '\n✓ All agents completed full decision cycle.' : '\n✗ Some agents failed — check output above.');
  process.exit(allPass ? 0 : 1);
}

main().catch((e) => { console.error(e); process.exit(1); });
