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

// Well-known Hardhat default account private key for the deployer (Account #0).
// Safe to use for local testing only.
const DEPLOYER_PK = '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80';

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
    'You receive: ETH reference price, on-chain last trade price, best bid, best ask, and Book order counts. ' +
    'Goal: profit from the bid-ask spread by always providing liquidity on both sides. ' +
    'BUY if best ask exists and ask price is at or above reference price (capture sell-side spread). ' +
    'SELL if best bid exists and bid price is at or below reference price (capture buy-side spread). ' +
    'If no clear signal, alternate: BUY if last trade is below reference, SELL if above. ' +
    'Respond with exactly one word: BUY or SELL.',
  momentum_trader:
    'You are Momentum-Alpha, an autonomous momentum trader on the Somnia blockchain. ' +
    'You receive: ETH reference price, on-chain last trade price, best bid, best ask, and Book order counts. ' +
    'Goal: ride price trends for directional profit. ' +
    'BUY if ETH reference price is higher than or equal to the on-chain last trade price (upward momentum). ' +
    'SELL if ETH reference price is lower than the on-chain last trade price (downward momentum). ' +
    'Use Book counts to gauge conviction: a heavily one-sided book suggests the trend may reverse. ' +
    'Respond with exactly one word: BUY or SELL.',
  arbitrage_agent:
    'You are Arb-Scanner, an autonomous arbitrage agent on the Somnia blockchain. ' +
    'You receive: ETH reference price (from CoinGecko), on-chain last trade price, best bid, best ask, and Book order counts. ' +
    'Goal: exploit price gaps between the reference market and the on-chain exchange. ' +
    'BUY if the on-chain last trade price is below the ETH reference price (on-chain underpriced). ' +
    'SELL if the on-chain last trade price is above or equal to the ETH reference price (on-chain overpriced or at parity). ' +
    'The arb signal takes priority — keep the on-chain price close to the oracle. ' +
    'Respond with exactly one word: BUY or SELL.',
  risk_manager:
    'You are Risk-Shield, an autonomous risk management agent on the Somnia blockchain. ' +
    'You receive: ETH reference price, on-chain last trade price, best bid, best ask, and Book order counts. ' +
    'Goal: maintain market stability by providing liquidity and hedging risk. ' +
    'BUY if there is no best bid, or if the on-chain last trade price is more than $5 below ETH reference (support the market). ' +
    'SELL if there is no best ask, or if the on-chain last trade price is more than $5 above ETH reference (resist the spike). ' +
    'If both conditions are neutral, BUY if last trade is below reference, SELL if above. ' +
    'Respond with exactly one word: BUY or SELL.',
  // Empty prompt = rule-based agent: coordinator detects this and runs
  // _executeRuleDecision (mean-reversion against oracle) instead of LLM inference.
  noise_trader: '',
};

async function main() {
  const [deployer] = await hre.ethers.getSigners();

  console.log('\n═══ Local Hardhat Deployment ══════════════════════════════');
  console.log('Deployer:', deployer.address);

  // 1. MockPlatform
  const MockPlatform = await hre.ethers.getContractFactory('MockPlatform');
  const mockPlatform = await MockPlatform.deploy();
  await mockPlatform.waitForDeployment();
  const mockPlatformAddr = await mockPlatform.getAddress();
  console.log('MockPlatform:      ', mockPlatformAddr);

  // 2. AgentToken — upgradeable proxy
  const AgentToken = await hre.ethers.getContractFactory('AgentToken');
  const token = await hre.upgrades.deployProxy(
    AgentToken,
    ['Somnia ETH', 'sETH'],
    { kind: 'uups', initializer: 'initialize' }
  );
  await token.waitForDeployment();
  const tokenAddr = await token.getAddress();
  console.log('AgentToken (proxy):', tokenAddr);

  // 3. QuoteToken (USDC-equivalent for testnet) — upgradeable proxy
  const QuoteToken = await hre.ethers.getContractFactory('QuoteToken');
  const quoteToken = await hre.upgrades.deployProxy(
    QuoteToken,
    [],
    { kind: 'uups', initializer: 'initialize' }
  );
  await quoteToken.waitForDeployment();
  const quoteTokenAddr = await quoteToken.getAddress();
  console.log('QuoteToken (proxy):', quoteTokenAddr);

  // 4. Exchange (sETH/USDC market) — upgradeable proxy
  const Exchange = await hre.ethers.getContractFactory('Exchange');
  const exchange = await hre.upgrades.deployProxy(
    Exchange,
    [tokenAddr, quoteTokenAddr],
    { kind: 'uups', initializer: 'initialize' }
  );
  await exchange.waitForDeployment();
  const exchangeAddr = await exchange.getAddress();
  console.log('Exchange (proxy):  ', exchangeAddr);

  // 5. Treasury — upgradeable proxy
  const Treasury = await hre.ethers.getContractFactory('Treasury');
  const treasury = await hre.upgrades.deployProxy(
    Treasury,
    [],
    { kind: 'uups', initializer: 'initialize' }
  );
  await treasury.waitForDeployment();
  const treasuryAddr = await treasury.getAddress();
  console.log('Treasury (proxy):  ', treasuryAddr);

  // 6. AgentCoordinator — upgradeable proxy
  //    constructor sets immutables (platform, exchange)
  //    initialize() sets owner + agent IDs (called via proxy on first deploy)
  const AgentCoordinator = await hre.ethers.getContractFactory('AgentCoordinator');
  const coordinator = await hre.upgrades.deployProxy(
    AgentCoordinator,
    [deployer.address, 1n, 1n],          // initialize(owner, llmAgentId, jsonApiAgentId)
    {
      kind: 'uups',
      constructorArgs: [mockPlatformAddr, exchangeAddr],
      initializer: 'initialize',
    }
  );
  await coordinator.waitForDeployment();
  const coordinatorAddr = await coordinator.getAddress();
  console.log('AgentCoordinator (proxy):', coordinatorAddr);

  // 7. AgentRegistry — upgradeable proxy
  const AgentRegistry = await hre.ethers.getContractFactory('AgentRegistry');
  const registry = await hre.upgrades.deployProxy(
    AgentRegistry,
    [deployer.address, coordinatorAddr],  // initialize(owner, coordinator)
    { kind: 'uups', initializer: 'initialize' }
  );
  await registry.waitForDeployment();
  const registryAddr = await registry.getAddress();
  console.log('AgentRegistry (proxy):   ', registryAddr);

  // 8. Wire registry into coordinator so registry can call onlyOwnerOrRegistry functions
  await (await coordinator.setRegistry(registryAddr)).wait();
  console.log('coordinator.setRegistry() done');

  // 9. Mint sETH + USDC to coordinator (50K each: 5 agents × 10K), approve Exchange for both
  await (await token.mint(coordinatorAddr, hre.ethers.parseEther('50000'))).wait();
  console.log('Minted 50K sETH to AgentCoordinator');
  await (await coordinator.approveToken(tokenAddr, exchangeAddr, hre.ethers.MaxUint256)).wait();
  console.log('AgentCoordinator approved Exchange for sETH');
  await (await quoteToken.mint(coordinatorAddr, hre.ethers.parseEther('50000'))).wait();
  console.log('Minted 50K QUOTE to AgentCoordinator');
  await (await coordinator.approveToken(quoteTokenAddr, exchangeAddr, hre.ethers.MaxUint256)).wait();
  console.log('AgentCoordinator approved Exchange for QUOTE');

  // 10. Register ALL system agents and allocate virtual capital in coordinator pool.
  //     Deployer is msg.sender → agentOwner = deployer for all system agents.
  //     noise_trader uses empty systemPrompt → coordinator routes it to rule-based logic.
  console.log('\n─── Registering system agents and allocating virtual capital ───');
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
    // Give each agent an equal 10K sETH + 10K QUOTE virtual allocation in the coordinator pool
    await (await coordinator.allocateToAgent(
      id,
      deployer.address,
      hre.ethers.parseEther('10000'),
      hre.ethers.parseEther('10000')
    )).wait();
    const tag = id === 'noise_trader' ? 'rule-based' : `prompt set`;
    console.log(`  ${id}: registered + 10K/10K allocated (${tag})`);
  }

  // 11. Fund coordinator with ETH for Somnia platform deposits
  await (await coordinator.fund({ value: hre.ethers.parseEther('0.5') })).wait();
  console.log('\nCoordinator funded: 0.5 ETH');

  // 12. Write deployment JSON
  const mockArtifact  = await hre.artifacts.readArtifact('MockPlatform');
  const tokenArtifact = await hre.artifacts.readArtifact('AgentToken');
  const quoteArtifact = await hre.artifacts.readArtifact('QuoteToken');
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
      QuoteToken:       { address: quoteTokenAddr },
      Exchange:         { address: exchangeAddr },
      Treasury:         { address: treasuryAddr },
      AgentCoordinator: { address: coordinatorAddr },
      AgentRegistry:    { address: registryAddr },
    },
    abis: {
      MockPlatform:     mockArtifact.abi,
      AgentToken:       tokenArtifact.abi,
      QuoteToken:       quoteArtifact.abi,
      Exchange:         exchArtifact.abi,
      Treasury:         trsArtifact.abi,
      AgentCoordinator: coordArtifact.abi,
      AgentRegistry:    regArtifact.abi,
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
  console.log(`DEPLOYER_PRIVATE_KEY=${DEPLOYER_PK}`);
  console.log(`AGENT_TOKEN_ADDRESS=${tokenAddr}`);
  console.log(`QUOTE_TOKEN_ADDRESS=${quoteTokenAddr}`);
  console.log(`EXCHANGE_ADDRESS=${exchangeAddr}`);
  console.log(`AGENT_REGISTRY_ADDRESS=${registryAddr}`);
  console.log(`TREASURY_ADDRESS=${treasuryAddr}`);
  console.log(`AGENT_COORDINATOR_ADDRESS=${coordinatorAddr}`);
  console.log('\n─── Paste into frontend/.env.local ─────────────────────────');
  console.log(`NEXT_PUBLIC_COORDINATOR_ADDRESS=${coordinatorAddr}`);
  console.log(`NEXT_PUBLIC_REGISTRY_ADDRESS=${registryAddr}`);
  console.log('════════════════════════════════════════════════════════════\n');
}

main().catch((e) => { console.error(e); process.exit(1); });
