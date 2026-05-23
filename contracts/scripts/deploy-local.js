// Deploy all contracts to a local Hardhat node for E2E testing.
//
// Run:
//   npx hardhat node                                          (Terminal 1)
//   npx hardhat run scripts/deploy-local.js --network localhost  (Terminal 2)
//
// Writes deployments/somnia-local.json and prints backend .env vars.

import hre from 'hardhat';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Well-known Hardhat default account private keys (deterministic from test mnemonic).
// These are printed by `npx hardhat node`. Safe to use for local testing only.
const HARDHAT_PKS = [
  '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80', // Account #0 deployer
  '0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d', // Account #1 market_maker
  '0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a', // Account #2 momentum_trader
  '0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6', // Account #3 arbitrage_agent
  '0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926b', // Account #4 risk_manager
  '0x92db14e403b83dfe3df233f83dfa3a0d7096f21ca9b0d6d6b8d88b2b4ec1564e', // Account #5 noise_trader
];

const AGENT_IDS = ['market_maker', 'momentum_trader', 'arbitrage_agent', 'risk_manager', 'noise_trader'];

const AGENT_META = {
  market_maker:    { name: 'MM-Prime',       strategy: 'Market Making' },
  momentum_trader: { name: 'Momentum-Alpha', strategy: 'Momentum Trading' },
  arbitrage_agent: { name: 'Arb-Scanner',    strategy: 'Arbitrage' },
  risk_manager:    { name: 'Risk-Shield',    strategy: 'Risk Management' },
  noise_trader:    { name: 'Noise-Bot',      strategy: 'Random Noise' },
};

const PROMPTS = {
  market_maker:
    'You are MM-Prime, an autonomous market maker on the Somnia blockchain. ' +
    'You receive: ETH reference price, on-chain last trade price, best bid, best ask. ' +
    'Goal: profit from the bid-ask spread by always providing liquidity on both sides. ' +
    'BUY if best ask exists and ask price is at or above reference price (capture sell-side spread). ' +
    'SELL if best bid exists and bid price is at or below reference price (capture buy-side spread). ' +
    'If no clear signal, alternate: BUY if last trade is below reference, SELL if above. ' +
    'Respond with exactly one word: BUY or SELL.',
  momentum_trader:
    'You are Momentum-Alpha, an autonomous momentum trader on the Somnia blockchain. ' +
    'You receive: ETH reference price, on-chain last trade price, best bid, best ask. ' +
    'Goal: ride price trends for directional profit. ' +
    'BUY if ETH reference price is higher than or equal to the on-chain last trade price (upward momentum). ' +
    'SELL if ETH reference price is lower than the on-chain last trade price (downward momentum). ' +
    'Respond with exactly one word: BUY or SELL.',
  arbitrage_agent:
    'You are Arb-Scanner, an autonomous arbitrage agent on the Somnia blockchain. ' +
    'You receive: ETH reference price (from CoinGecko), on-chain last trade price, best bid, best ask. ' +
    'Goal: exploit price gaps between the reference market and the on-chain exchange. ' +
    'BUY if the on-chain last trade price is below the ETH reference price (on-chain underpriced). ' +
    'SELL if the on-chain last trade price is above or equal to the ETH reference price (on-chain overpriced or at parity). ' +
    'Respond with exactly one word: BUY or SELL.',
  risk_manager:
    'You are Risk-Shield, an autonomous risk management agent on the Somnia blockchain. ' +
    'You receive: ETH reference price, on-chain last trade price, best bid, best ask. ' +
    'Goal: maintain market stability by providing liquidity and hedging risk. ' +
    'BUY if there is no best bid, or if the on-chain last trade price is more than $5 below ETH reference (support the market). ' +
    'SELL if there is no best ask, or if the on-chain last trade price is more than $5 above ETH reference (resist the spike). ' +
    'If both conditions are neutral, BUY if last trade is below reference, SELL if above. ' +
    'Respond with exactly one word: BUY or SELL.',
  noise_trader:
    'You are Noise-Bot, a random noise trading agent on the Somnia blockchain. ' +
    'Your goal is to keep the market active with unpredictable orders. ' +
    'If the ETH reference price ends in an even digit, BUY. If odd, SELL. ' +
    'Respond with exactly one word: BUY or SELL.',
};

async function main() {
  const [deployer, mm, momentum, arb, risk, noise] = await hre.ethers.getSigners();
  const agentSigners = [mm, momentum, arb, risk, noise];

  console.log('\n═══ Local Hardhat Deployment ══════════════════════════════');
  console.log('Deployer:', deployer.address);

  // 1. MockPlatform — must deploy before coordinator (address needed in constructor)
  const MockPlatform = await hre.ethers.getContractFactory('MockPlatform');
  const mockPlatform = await MockPlatform.deploy();
  await mockPlatform.waitForDeployment();
  const mockPlatformAddr = await mockPlatform.getAddress();
  console.log('MockPlatform:      ', mockPlatformAddr);

  // 2. Exchange
  const Exchange = await hre.ethers.getContractFactory('Exchange');
  const exchange = await Exchange.deploy();
  await exchange.waitForDeployment();
  const exchangeAddr = await exchange.getAddress();
  console.log('Exchange:          ', exchangeAddr);

  // 3. AgentRegistry
  const AgentRegistry = await hre.ethers.getContractFactory('AgentRegistry');
  const registry = await AgentRegistry.deploy();
  await registry.waitForDeployment();
  const registryAddr = await registry.getAddress();
  console.log('AgentRegistry:     ', registryAddr);

  // 4. Treasury
  const Treasury = await hre.ethers.getContractFactory('Treasury');
  const treasury = await Treasury.deploy();
  await treasury.waitForDeployment();
  const treasuryAddr = await treasury.getAddress();
  console.log('Treasury:          ', treasuryAddr);

  // 5. AgentCoordinator — pass MockPlatform as the IAgentRequester
  const AgentCoordinator = await hre.ethers.getContractFactory('AgentCoordinator');
  const coordinator = await AgentCoordinator.deploy(
    mockPlatformAddr,
    exchangeAddr,
    1n, // llmAgentId (irrelevant for mock)
    1n  // jsonApiAgentId (irrelevant for mock)
  );
  await coordinator.waitForDeployment();
  const coordinatorAddr = await coordinator.getAddress();
  console.log('AgentCoordinator:  ', coordinatorAddr);

  // Set agent configs + prompts
  console.log('\n─── Configuring agents ────────────────────────────────────');
  for (const id of AGENT_IDS) {
    let tx = await coordinator.setAgentConfig(id, 'https://mock.price/eth', 'price', 0);
    await tx.wait();
    tx = await coordinator.setSystemPrompt(id, PROMPTS[id]);
    await tx.wait();
    console.log(`  ${id}: config + prompt set`);
  }

  // Fund coordinator (deposit=0 so any balance satisfies the guard, but send some ETH anyway)
  const fundTx = await coordinator.fund({ value: hre.ethers.parseEther('10.0') });
  await fundTx.wait();
  console.log('\nCoordinator funded: 10.0 ETH');

  // Register agents in AgentRegistry + fund their treasuries
  console.log('\n─── Registering agents & funding treasuries ───────────────');
  for (let i = 0; i < AGENT_IDS.length; i++) {
    const id = AGENT_IDS[i];
    const signer = agentSigners[i];
    const meta = AGENT_META[id];

    let tx = await registry.register(signer.address, meta.name, meta.strategy);
    await tx.wait();

    tx = await treasury.depositFor(signer.address, { value: hre.ethers.parseEther('0.1') });
    await tx.wait();

    console.log(`  ${id}: ${signer.address} registered + 0.1 ETH in treasury`);
  }

  // Read ABIs
  const mockArtifact  = await hre.artifacts.readArtifact('MockPlatform');
  const exchArtifact  = await hre.artifacts.readArtifact('Exchange');
  const regArtifact   = await hre.artifacts.readArtifact('AgentRegistry');
  const trsArtifact   = await hre.artifacts.readArtifact('Treasury');
  const coordArtifact = await hre.artifacts.readArtifact('AgentCoordinator');

  const deployment = {
    chainId: 31337,
    network: 'localhost',
    deployedAt: new Date().toISOString(),
    deployer: deployer.address,
    contracts: {
      MockPlatform:     { address: mockPlatformAddr },
      Exchange:         { address: exchangeAddr },
      AgentRegistry:    { address: registryAddr },
      Treasury:         { address: treasuryAddr },
      AgentCoordinator: { address: coordinatorAddr },
    },
    abis: {
      MockPlatform:     mockArtifact.abi,
      Exchange:         exchArtifact.abi,
      AgentRegistry:    regArtifact.abi,
      Treasury:         trsArtifact.abi,
      AgentCoordinator: coordArtifact.abi,
    },
    agents: {
      market_maker:    { address: agentSigners[0].address, pk: HARDHAT_PKS[1] },
      momentum_trader: { address: agentSigners[1].address, pk: HARDHAT_PKS[2] },
      arbitrage_agent: { address: agentSigners[2].address, pk: HARDHAT_PKS[3] },
      risk_manager:    { address: agentSigners[3].address, pk: HARDHAT_PKS[4] },
      noise_trader:    { address: agentSigners[4].address, pk: HARDHAT_PKS[5] },
    },
  };

  const deploymentsDir = path.join(__dirname, '../deployments');
  if (!fs.existsSync(deploymentsDir)) fs.mkdirSync(deploymentsDir, { recursive: true });
  const outPath = path.join(deploymentsDir, 'somnia-local.json');
  fs.writeFileSync(outPath, JSON.stringify(deployment, null, 2));
  console.log('\nDeployment saved to:', outPath);

  console.log('\n═══ Paste into backend/.env ════════════════════════════════');
  console.log('SOMNIA_RPC_URL=http://127.0.0.1:8545');
  console.log('SOMNIA_CHAIN_ID=31337');
  console.log(`EXCHANGE_ADDRESS=${exchangeAddr}`);
  console.log(`AGENT_REGISTRY_ADDRESS=${registryAddr}`);
  console.log(`TREASURY_ADDRESS=${treasuryAddr}`);
  console.log(`AGENT_COORDINATOR_ADDRESS=${coordinatorAddr}`);
  console.log(`MARKET_MAKER_PK=${HARDHAT_PKS[1]}`);
  console.log(`MOMENTUM_TRADER_PK=${HARDHAT_PKS[2]}`);
  console.log(`ARBITRAGE_AGENT_PK=${HARDHAT_PKS[3]}`);
  console.log(`RISK_MANAGER_PK=${HARDHAT_PKS[4]}`);
  console.log(`NOISE_TRADER_PK=${HARDHAT_PKS[5]}`);
  console.log('════════════════════════════════════════════════════════════\n');

  console.log('Next steps:');
  console.log('  npx hardhat run scripts/test-local.js --network localhost   # smoke test');
  console.log('  node scripts/platform-daemon.js                             # continuous loop');
}

main().catch((e) => { console.error(e); process.exit(1); });
