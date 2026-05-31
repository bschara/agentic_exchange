import hre from 'hardhat';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Somnia testnet platform address for IAgentRequester
const SOMNIA_PLATFORM_TESTNET = '0x037Bb9C718F3f7fe5eCBDB0b600D607b52706776';

// Agent IDs — confirm both at https://agents.somnia.network
const LLM_AGENT_ID      = process.env.SOMNIA_LLM_AGENT_ID      || '2';
const JSON_API_AGENT_ID = process.env.SOMNIA_JSON_API_AGENT_ID  || '1';

// CoinGecko ETH/USD price endpoint (returns integer USD price, e.g. 3245)
const COINGECKO_ETH_URL = 'https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd';
const COINGECKO_SELECTOR = 'ethereum.usd';
const PRICE_DECIMALS = 0; // whole USD → returned as plain uint, e.g. 3245

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  console.log('Deploying contracts with:', deployer.address);
  const balance = await hre.ethers.provider.getBalance(deployer.address);
  console.log('Balance:', hre.ethers.formatEther(balance), 'STT');

  // Deploy AgentToken (sETH — Somnia synthetic ETH) — upgradeable proxy
  const AgentToken = await hre.ethers.getContractFactory('AgentToken');
  const token = await hre.upgrades.deployProxy(
    AgentToken,
    ['Somnia ETH', 'sETH'],
    { kind: 'uups', initializer: 'initialize' }
  );
  await token.waitForDeployment();
  const tokenAddr = await token.getAddress();
  console.log('AgentToken (proxy) deployed to:', tokenAddr);

  // Deploy QuoteToken (USDC-equivalent — payment currency for BUY orders) — upgradeable proxy
  const QuoteToken = await hre.ethers.getContractFactory('QuoteToken');
  const quoteToken = await hre.upgrades.deployProxy(
    QuoteToken,
    [],
    { kind: 'uups', initializer: 'initialize' }
  );
  await quoteToken.waitForDeployment();
  const quoteTokenAddr = await quoteToken.getAddress();
  console.log('QuoteToken (proxy) deployed to:', quoteTokenAddr);

  // Deploy Exchange (sETH/USDC market — locks USDC on BUY, sETH on SELL) — upgradeable proxy
  const Exchange = await hre.ethers.getContractFactory('Exchange');
  const exchange = await hre.upgrades.deployProxy(
    Exchange,
    [tokenAddr, quoteTokenAddr],
    { kind: 'uups', initializer: 'initialize' }
  );
  await exchange.waitForDeployment();
  const exchangeAddr = await exchange.getAddress();
  console.log('Exchange (proxy) deployed to:', exchangeAddr);

  // Deploy Treasury — upgradeable proxy
  const Treasury = await hre.ethers.getContractFactory('Treasury');
  const treasury = await hre.upgrades.deployProxy(
    Treasury,
    [],
    { kind: 'uups', initializer: 'initialize' }
  );
  await treasury.waitForDeployment();
  const treasuryAddr = await treasury.getAddress();
  console.log('Treasury (proxy) deployed to:', treasuryAddr);

  // Deploy AgentCoordinator — upgradeable proxy
  //   constructor sets immutables (platform, exchange)
  //   initialize() sets owner + agent IDs (called via proxy on first deploy)
  const AgentCoordinator = await hre.ethers.getContractFactory('AgentCoordinator');
  const coordinator = await hre.upgrades.deployProxy(
    AgentCoordinator,
    [deployer.address, BigInt(LLM_AGENT_ID), BigInt(JSON_API_AGENT_ID)],
    {
      kind: 'uups',
      constructorArgs: [SOMNIA_PLATFORM_TESTNET, exchangeAddr],
      initializer: 'initialize',
    }
  );
  await coordinator.waitForDeployment();
  const coordinatorAddr = await coordinator.getAddress();
  console.log('AgentCoordinator (proxy) deployed to:', coordinatorAddr);

  // Deploy AgentRegistry — upgradeable proxy
  const AgentRegistry = await hre.ethers.getContractFactory('AgentRegistry');
  const registry = await hre.upgrades.deployProxy(
    AgentRegistry,
    [deployer.address, coordinatorAddr],
    { kind: 'uups', initializer: 'initialize' }
  );
  await registry.waitForDeployment();
  const registryAddr = await registry.getAddress();
  console.log('AgentRegistry (proxy) deployed to:', registryAddr);

  // Register all system agents via unified AgentRegistry.registerAgent()
  // Deployer is msg.sender → agentOwner = deployer for all system agents.
  const AGENT_META = {
    market_maker:    { name: 'MM-Prime',       icon: '⚖️', riskLevel: 3,
      prompt: 'You are MM-Prime, an autonomous market maker on the Somnia blockchain. ' +
        'You receive: ETH reference price, on-chain last trade price, best bid, best ask. ' +
        'Goal: profit from the bid-ask spread by always providing liquidity on both sides. ' +
        'BUY if best ask exists and ask price is at or above reference price (capture sell-side spread). ' +
        'SELL if best bid exists and bid price is at or below reference price (capture buy-side spread). ' +
        'If no clear signal, alternate: BUY if last trade is below reference, SELL if above. ' +
        'Respond with exactly one word: BUY or SELL.' },
    momentum_trader: { name: 'Momentum-Alpha', icon: '📈', riskLevel: 4,
      prompt: 'You are Momentum-Alpha, an autonomous momentum trader on the Somnia blockchain. ' +
        'You receive: ETH reference price, on-chain last trade price, best bid, best ask. ' +
        'Goal: ride price trends for directional profit. ' +
        'BUY if ETH reference price is higher than or equal to the on-chain last trade price (upward momentum). ' +
        'SELL if ETH reference price is lower than the on-chain last trade price (downward momentum). ' +
        'Respond with exactly one word: BUY or SELL.' },
    arbitrage_agent: { name: 'Arb-Scanner',    icon: '🔍', riskLevel: 3,
      prompt: 'You are Arb-Scanner, an autonomous arbitrage agent on the Somnia blockchain. ' +
        'You receive: ETH reference price (from CoinGecko), on-chain last trade price, best bid, best ask. ' +
        'Goal: exploit price gaps between the reference market and the on-chain exchange. ' +
        'BUY if the on-chain last trade price is below the ETH reference price (on-chain underpriced). ' +
        'SELL if the on-chain last trade price is above or equal to the ETH reference price (on-chain overpriced or at parity). ' +
        'Respond with exactly one word: BUY or SELL.' },
    risk_manager:    { name: 'Risk-Shield',    icon: '🛡️', riskLevel: 2,
      prompt: 'You are Risk-Shield, an autonomous risk management agent on the Somnia blockchain. ' +
        'You receive: ETH reference price, on-chain last trade price, best bid, best ask. ' +
        'Goal: maintain market stability by providing liquidity and hedging risk. ' +
        'BUY if there is no best bid, or if the on-chain last trade price is more than $5 below ETH reference (support the market). ' +
        'SELL if there is no best ask, or if the on-chain last trade price is more than $5 above ETH reference (resist the spike). ' +
        'If both conditions are neutral, BUY if last trade is below reference, SELL if above. ' +
        'Respond with exactly one word: BUY or SELL.' },
    noise_trader:    { name: 'Noise-Bot',      icon: '🎲', riskLevel: 1,
      prompt: 'You are Noise-Bot, a random noise trading agent on the Somnia blockchain. ' +
        'Your goal is to keep the market active with unpredictable orders. ' +
        'If the ETH reference price ends in an even digit, BUY. If odd, SELL. ' +
        'Respond with exactly one word: BUY or SELL.' },
  };

  console.log('\n─── Registering system agents via AgentRegistry ───');
  for (const [id, meta] of Object.entries(AGENT_META)) {
    const tx = await registry.registerAgent(
      id, meta.name, meta.icon, meta.riskLevel,
      meta.prompt, COINGECKO_ETH_URL, COINGECKO_SELECTOR, PRICE_DECIMALS
    );
    await tx.wait();
    console.log(`  ${id}: registered (icon=${meta.icon}, risk=${meta.riskLevel})`);
  }

  // Wire registry into coordinator so registry can call onlyOwnerOrRegistry functions
  await (await coordinator.setRegistry(registryAddr)).wait();
  console.log('coordinator.setRegistry() done');

  // Fund AgentCoordinator — needs 2 deposits per decision cycle (JSON API + LLM)
  // 0.2 STT covers ~many cycles across 4 agents
  const coordinatorFund = hre.ethers.parseEther('0.2');
  const fundTx = await coordinator.fund({ value: coordinatorFund });
  await fundTx.wait();
  console.log(`AgentCoordinator funded with ${hre.ethers.formatEther(coordinatorFund)} STT`);

  // Mint 10M sETH to coordinator (pool for all main agents)
  const COORDINATOR_MINT = hre.ethers.parseEther('10000000');
  await (await token.mint(coordinatorAddr, COORDINATOR_MINT)).wait();
  console.log('Minted 10M sETH to AgentCoordinator');

  // Coordinator approves Exchange for both sETH and USDC
  await (await coordinator.approveToken(tokenAddr, exchangeAddr, hre.ethers.MaxUint256)).wait();
  console.log('AgentCoordinator approved Exchange for sETH');

  // Mint 10K QUOTE to coordinator (for BUY orders)
  await (await quoteToken.mint(coordinatorAddr, hre.ethers.parseEther('10000'))).wait();
  console.log('Minted 10K QUOTE to AgentCoordinator');
  await (await coordinator.approveToken(quoteTokenAddr, exchangeAddr, hre.ethers.MaxUint256)).wait();
  console.log('AgentCoordinator approved Exchange for QUOTE');

  // Mint 10M QUOTE to noise_trader wallet if address provided via env
  const noiseTraderAddr = process.env.NOISE_TRADER_ADDRESS || '';
  if (noiseTraderAddr && hre.ethers.isAddress(noiseTraderAddr)) {
    await (await quoteToken.mint(noiseTraderAddr, hre.ethers.parseEther('10000'))).wait();
    console.log(`Minted 10K QUOTE to noise_trader (${noiseTraderAddr})`);
  }

  // Read ABIs from artifacts
  const tokenArtifact       = await hre.artifacts.readArtifact('AgentToken');
  const quoteArtifact       = await hre.artifacts.readArtifact('QuoteToken');
  const exchangeArtifact    = await hre.artifacts.readArtifact('Exchange');
  const registryArtifact    = await hre.artifacts.readArtifact('AgentRegistry');
  const treasuryArtifact    = await hre.artifacts.readArtifact('Treasury');
  const coordinatorArtifact = await hre.artifacts.readArtifact('AgentCoordinator');

  const deployment = {
    chainId: 50312,
    deployedAt: new Date().toISOString(),
    deployer: deployer.address,
    contracts: {
      AgentToken:       { address: tokenAddr },
      QuoteToken:       { address: quoteTokenAddr },
      Exchange:         { address: exchangeAddr },
      AgentRegistry:    { address: registryAddr },
      Treasury:         { address: treasuryAddr },
      AgentCoordinator: { address: coordinatorAddr },
    },
    abis: {
      AgentToken:       tokenArtifact.abi,
      QuoteToken:       quoteArtifact.abi,
      Exchange:         exchangeArtifact.abi,
      AgentRegistry:    registryArtifact.abi,
      Treasury:         treasuryArtifact.abi,
      AgentCoordinator: coordinatorArtifact.abi,
    },
    meta: {
      somniaPlatform: SOMNIA_PLATFORM_TESTNET,
      llmAgentId:     LLM_AGENT_ID,
      jsonApiAgentId: JSON_API_AGENT_ID,
      priceUrl:       COINGECKO_ETH_URL,
    },
  };

  const deploymentsDir = path.join(__dirname, '../deployments');
  if (!fs.existsSync(deploymentsDir)) fs.mkdirSync(deploymentsDir, { recursive: true });

  const outPath = path.join(deploymentsDir, 'somnia-testnet.json');
  fs.writeFileSync(outPath, JSON.stringify(deployment, null, 2));
  console.log('\nDeployment saved to:', outPath);

  console.log('\n─── Add to backend/.env ───────────────────────────────');
  console.log(`AGENT_TOKEN_ADDRESS=${tokenAddr}`);
  console.log(`QUOTE_TOKEN_ADDRESS=${quoteTokenAddr}`);
  console.log(`EXCHANGE_ADDRESS=${exchangeAddr}`);
  console.log(`AGENT_REGISTRY_ADDRESS=${registryAddr}`);
  console.log(`TREASURY_ADDRESS=${treasuryAddr}`);
  console.log(`AGENT_COORDINATOR_ADDRESS=${coordinatorAddr}`);
  console.log('───────────────────────────────────────────────────────');
  console.log('\nNote: Confirm agent IDs at https://agents.somnia.network');
  console.log(`  LLM Inference agent ID:  ${LLM_AGENT_ID}  (override: SOMNIA_LLM_AGENT_ID)`);
  console.log(`  JSON API agent ID:       ${JSON_API_AGENT_ID}  (override: SOMNIA_JSON_API_AGENT_ID)`);
}

main().catch((e) => { console.error(e); process.exit(1); });
