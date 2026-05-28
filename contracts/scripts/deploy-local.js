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
  '0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a', // Account #4 risk_manager
  '0x8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba', // Account #5 noise_trader
];

const AGENT_IDS = ['market_maker', 'momentum_trader', 'arbitrage_agent', 'risk_manager', 'noise_trader'];

// Unified metadata for all system agents — same fields used by AgentRegistry.registerAgent()
const AGENT_META = {
  market_maker:    { name: 'MM-Prime',       icon: '⚖️', riskLevel: 3 },
  momentum_trader: { name: 'Momentum-Alpha', icon: '📈', riskLevel: 4 },
  arbitrage_agent: { name: 'Arb-Scanner',    icon: '🔍', riskLevel: 3 },
  risk_manager:    { name: 'Risk-Shield',    icon: '🛡️', riskLevel: 2 },
  noise_trader:    { name: 'Noise-Bot',      icon: '🎲', riskLevel: 1 },
};

const PRICE_URL = 'https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd';
const PRICE_SELECTOR = 'ethereum.usd';
const PRICE_DECIMALS = 0;

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

  // 1. MockPlatform
  const MockPlatform = await hre.ethers.getContractFactory('MockPlatform');
  const mockPlatform = await MockPlatform.deploy();
  await mockPlatform.waitForDeployment();
  const mockPlatformAddr = await mockPlatform.getAddress();
  console.log('MockPlatform:      ', mockPlatformAddr);

  // 2. AgentToken
  const AgentToken = await hre.ethers.getContractFactory('AgentToken');
  const token = await AgentToken.deploy('AgentToken', 'AGT');
  await token.waitForDeployment();
  const tokenAddr = await token.getAddress();
  console.log('AgentToken:        ', tokenAddr);

  // 3. Exchange
  const Exchange = await hre.ethers.getContractFactory('Exchange');
  const exchange = await Exchange.deploy(tokenAddr);
  await exchange.waitForDeployment();
  const exchangeAddr = await exchange.getAddress();
  console.log('Exchange:          ', exchangeAddr);

  // 4. Treasury
  const Treasury = await hre.ethers.getContractFactory('Treasury');
  const treasury = await Treasury.deploy();
  await treasury.waitForDeployment();
  const treasuryAddr = await treasury.getAddress();
  console.log('Treasury:          ', treasuryAddr);

  // 5. AgentCoordinator — deployed BEFORE registry (registry needs coordinator address)
  const AgentCoordinator = await hre.ethers.getContractFactory('AgentCoordinator');
  const coordinator = await AgentCoordinator.deploy(
    mockPlatformAddr,
    exchangeAddr,
    1n,
    1n
  );
  await coordinator.waitForDeployment();
  const coordinatorAddr = await coordinator.getAddress();
  console.log('AgentCoordinator:  ', coordinatorAddr);

  // 6. AgentRegistry — takes coordinator address in constructor
  const AgentRegistry = await hre.ethers.getContractFactory('AgentRegistry');
  const registry = await AgentRegistry.deploy(coordinatorAddr);
  await registry.waitForDeployment();
  const registryAddr = await registry.getAddress();
  console.log('AgentRegistry:     ', registryAddr);

  // 7. Wire registry into coordinator so registry can call onlyOwnerOrRegistry functions
  await (await coordinator.setRegistry(registryAddr)).wait();
  console.log('coordinator.setRegistry() done');

  // 8. Mint AGT to coordinator + approve Exchange
  await (await token.mint(coordinatorAddr, hre.ethers.parseEther('10000000'))).wait();
  console.log('Minted 10M AGT to AgentCoordinator');
  await (await coordinator.approveToken(tokenAddr, exchangeAddr, hre.ethers.MaxUint256)).wait();
  console.log('AgentCoordinator approved Exchange for AGT');

  // 9. Register ALL system agents via AgentRegistry.registerAgent()
  //    Deployer is msg.sender → agentOwner = deployer for all system agents.
  //    This replaces the old separate setAgentConfig() + setSystemPrompt() calls.
  console.log('\n─── Registering system agents via unified AgentRegistry ───');
  for (const id of AGENT_IDS) {
    const meta = AGENT_META[id];
    const tx = await registry.registerAgent(
      id,
      meta.name,
      meta.icon,
      meta.riskLevel,
      PROMPTS[id],
      PRICE_URL,
      PRICE_SELECTOR,
      PRICE_DECIMALS
    );
    await tx.wait();
    console.log(`  ${id}: registered (owner=deployer, icon=${meta.icon}, risk=${meta.riskLevel})`);
  }

  // 10. Fund coordinator with ETH for Somnia platform deposits
  await (await coordinator.fund({ value: hre.ethers.parseEther('10.0') })).wait();
  console.log('\nCoordinator funded: 10.0 ETH');

  // 11. Fund agent treasuries + mint AGT to noise_trader for direct Exchange calls
  console.log('\n─── Funding agent treasuries ───────────────────────────────');
  for (let i = 0; i < AGENT_IDS.length; i++) {
    const signer = agentSigners[i];
    await (await treasury.depositFor(signer.address, { value: hre.ethers.parseEther('0.1') })).wait();
    console.log(`  ${AGENT_IDS[i]}: 0.1 ETH in treasury`);
  }

  const noiseSigner = agentSigners[4];
  await (await token.mint(noiseSigner.address, hre.ethers.parseEther('10000'))).wait();
  await (await token.connect(noiseSigner).approve(exchangeAddr, hre.ethers.MaxUint256)).wait();
  console.log(`\nNoise trader: 10,000 AGT + Exchange approved (${noiseSigner.address})`);

  // 12. Write deployment JSON
  const mockArtifact  = await hre.artifacts.readArtifact('MockPlatform');
  const tokenArtifact = await hre.artifacts.readArtifact('AgentToken');
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
      AgentToken:       { address: tokenAddr },
      Exchange:         { address: exchangeAddr },
      Treasury:         { address: treasuryAddr },
      AgentCoordinator: { address: coordinatorAddr },
      AgentRegistry:    { address: registryAddr },
    },
    abis: {
      MockPlatform:     mockArtifact.abi,
      AgentToken:       tokenArtifact.abi,
      Exchange:         exchArtifact.abi,
      Treasury:         trsArtifact.abi,
      AgentCoordinator: coordArtifact.abi,
      AgentRegistry:    regArtifact.abi,
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
  console.log(`AGENT_TOKEN_ADDRESS=${tokenAddr}`);
  console.log(`EXCHANGE_ADDRESS=${exchangeAddr}`);
  console.log(`AGENT_REGISTRY_ADDRESS=${registryAddr}`);
  console.log(`TREASURY_ADDRESS=${treasuryAddr}`);
  console.log(`AGENT_COORDINATOR_ADDRESS=${coordinatorAddr}`);
  console.log(`MARKET_MAKER_PK=${HARDHAT_PKS[1]}`);
  console.log(`MOMENTUM_TRADER_PK=${HARDHAT_PKS[2]}`);
  console.log(`ARBITRAGE_AGENT_PK=${HARDHAT_PKS[3]}`);
  console.log(`RISK_MANAGER_PK=${HARDHAT_PKS[4]}`);
  console.log(`NOISE_TRADER_PK=${HARDHAT_PKS[5]}`);
  console.log('\n─── Paste into frontend/.env.local ─────────────────────────');
  console.log(`NEXT_PUBLIC_COORDINATOR_ADDRESS=${coordinatorAddr}`);
  console.log(`NEXT_PUBLIC_REGISTRY_ADDRESS=${registryAddr}`);
  console.log('════════════════════════════════════════════════════════════\n');
}

main().catch((e) => { console.error(e); process.exit(1); });
