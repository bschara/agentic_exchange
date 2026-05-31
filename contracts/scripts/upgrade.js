// Upgrade any or all upgradeable contracts to a new implementation.
//
// Usage:
//   npx hardhat run scripts/upgrade.js --network somnia
//   npx hardhat run scripts/upgrade.js --network localhost
//
// Reads proxy addresses from the deployment JSON.
// Set the corresponding env var to "false" to skip a contract (all default to true):
//   UPGRADE_COORDINATOR, UPGRADE_REGISTRY, UPGRADE_EXCHANGE,
//   UPGRADE_TREASURY, UPGRADE_AGENT_TOKEN, UPGRADE_QUOTE_TOKEN

import hre from 'hardhat';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const SOMNIA_PLATFORM_TESTNET = '0x037Bb9C718F3f7fe5eCBDB0b600D607b52706776';

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  const isLocal = hre.network.name === 'localhost';
  const deployFile = isLocal ? 'somnia-local.json' : 'somnia-testnet.json';
  const deployPath = path.join(__dirname, '../deployments', deployFile);

  if (!fs.existsSync(deployPath)) {
    throw new Error(`Deployment file not found: ${deployPath}. Run deploy script first.`);
  }

  const deployment = JSON.parse(fs.readFileSync(deployPath, 'utf8'));
  const coordinatorProxyAddr = deployment.contracts.AgentCoordinator?.address;
  const registryProxyAddr    = deployment.contracts.AgentRegistry?.address;
  const exchangeProxyAddr    = deployment.contracts.Exchange?.address;
  const treasuryProxyAddr    = deployment.contracts.Treasury?.address;
  const agentTokenProxyAddr  = deployment.contracts.AgentToken?.address;
  const quoteTokenProxyAddr  = deployment.contracts.QuoteToken?.address;
  const platformAddr         = isLocal
    ? deployment.contracts.MockPlatform?.address
    : SOMNIA_PLATFORM_TESTNET;

  const upgradeCoordinator = process.env.UPGRADE_COORDINATOR  !== 'false';
  const upgradeRegistry    = process.env.UPGRADE_REGISTRY     !== 'false';
  const upgradeExchange    = process.env.UPGRADE_EXCHANGE      !== 'false';
  const upgradeTreasury    = process.env.UPGRADE_TREASURY      !== 'false';
  const upgradeAgentToken  = process.env.UPGRADE_AGENT_TOKEN   !== 'false';
  const upgradeQuoteToken  = process.env.UPGRADE_QUOTE_TOKEN   !== 'false';

  console.log('\n═══ Upgrading Contracts ═══════════════════════════════════');
  console.log('Deployer:          ', deployer.address);
  console.log('Network:           ', hre.network.name);
  console.log('Coordinator proxy: ', coordinatorProxyAddr);
  console.log('Registry proxy:    ', registryProxyAddr);
  console.log('Exchange proxy:    ', exchangeProxyAddr);
  console.log('Treasury proxy:    ', treasuryProxyAddr);
  console.log('AgentToken proxy:  ', agentTokenProxyAddr);
  console.log('QuoteToken proxy:  ', quoteTokenProxyAddr);

  // ── Upgrade AgentCoordinator ──────────────────────────────────────────────

  if (upgradeCoordinator) {
    if (!coordinatorProxyAddr) throw new Error('AgentCoordinator proxy address not found in deployment JSON');
    if (!platformAddr || !exchangeAddr) throw new Error('Platform or Exchange address missing');

    console.log('\n─── Upgrading AgentCoordinator ──────────────────────────────');
    const AgentCoordinator = await hre.ethers.getContractFactory('AgentCoordinator');
    const upgraded = await hre.upgrades.upgradeProxy(
      coordinatorProxyAddr,
      AgentCoordinator,
      { kind: 'uups', constructorArgs: [platformAddr, exchangeAddr] }
    );
    await upgraded.waitForDeployment();
    console.log('AgentCoordinator upgraded. Proxy address unchanged:', coordinatorProxyAddr);

    // Update impl address in deployment JSON
    const newImpl = await hre.upgrades.erc1967.getImplementationAddress(coordinatorProxyAddr);
    console.log('New implementation:', newImpl);
    deployment.contracts.AgentCoordinator.implementation = newImpl;
    deployment.contracts.AgentCoordinator.upgradedAt = new Date().toISOString();
  }

  // ── Upgrade AgentRegistry ─────────────────────────────────────────────────

  if (upgradeRegistry) {
    if (!registryProxyAddr) throw new Error('AgentRegistry proxy address not found in deployment JSON');

    console.log('\n─── Upgrading AgentRegistry ──────────────────────────────');
    const AgentRegistry = await hre.ethers.getContractFactory('AgentRegistry');
    const upgraded = await hre.upgrades.upgradeProxy(registryProxyAddr, AgentRegistry, {
      kind: 'uups',
    });
    await upgraded.waitForDeployment();
    console.log('AgentRegistry upgraded. Proxy address unchanged:', registryProxyAddr);

    const newImpl = await hre.upgrades.erc1967.getImplementationAddress(registryProxyAddr);
    console.log('New implementation:', newImpl);
    deployment.contracts.AgentRegistry.implementation = newImpl;
    deployment.contracts.AgentRegistry.upgradedAt = new Date().toISOString();
  }

  // ── Upgrade Exchange ──────────────────────────────────────────────────────

  if (upgradeExchange) {
    if (!exchangeProxyAddr) throw new Error('Exchange proxy address not found in deployment JSON');

    console.log('\n─── Upgrading Exchange ───────────────────────────────────────');
    const Exchange = await hre.ethers.getContractFactory('Exchange');
    const upgraded = await hre.upgrades.upgradeProxy(exchangeProxyAddr, Exchange, {
      kind: 'uups',
    });
    await upgraded.waitForDeployment();
    console.log('Exchange upgraded. Proxy address unchanged:', exchangeProxyAddr);

    const newImpl = await hre.upgrades.erc1967.getImplementationAddress(exchangeProxyAddr);
    console.log('New implementation:', newImpl);
    deployment.contracts.Exchange.implementation = newImpl;
    deployment.contracts.Exchange.upgradedAt = new Date().toISOString();
  }

  // ── Upgrade Treasury ──────────────────────────────────────────────────────

  if (upgradeTreasury) {
    if (!treasuryProxyAddr) throw new Error('Treasury proxy address not found in deployment JSON');

    console.log('\n─── Upgrading Treasury ───────────────────────────────────────');
    const Treasury = await hre.ethers.getContractFactory('Treasury');
    const upgraded = await hre.upgrades.upgradeProxy(treasuryProxyAddr, Treasury, {
      kind: 'uups',
    });
    await upgraded.waitForDeployment();
    console.log('Treasury upgraded. Proxy address unchanged:', treasuryProxyAddr);

    const newImpl = await hre.upgrades.erc1967.getImplementationAddress(treasuryProxyAddr);
    console.log('New implementation:', newImpl);
    deployment.contracts.Treasury.implementation = newImpl;
    deployment.contracts.Treasury.upgradedAt = new Date().toISOString();
  }

  // ── Upgrade AgentToken ────────────────────────────────────────────────────

  if (upgradeAgentToken) {
    if (!agentTokenProxyAddr) throw new Error('AgentToken proxy address not found in deployment JSON');

    console.log('\n─── Upgrading AgentToken ─────────────────────────────────────');
    const AgentToken = await hre.ethers.getContractFactory('AgentToken');
    const upgraded = await hre.upgrades.upgradeProxy(agentTokenProxyAddr, AgentToken, {
      kind: 'uups',
    });
    await upgraded.waitForDeployment();
    console.log('AgentToken upgraded. Proxy address unchanged:', agentTokenProxyAddr);

    const newImpl = await hre.upgrades.erc1967.getImplementationAddress(agentTokenProxyAddr);
    console.log('New implementation:', newImpl);
    deployment.contracts.AgentToken.implementation = newImpl;
    deployment.contracts.AgentToken.upgradedAt = new Date().toISOString();
  }

  // ── Upgrade QuoteToken ────────────────────────────────────────────────────

  if (upgradeQuoteToken) {
    if (!quoteTokenProxyAddr) throw new Error('QuoteToken proxy address not found in deployment JSON');

    console.log('\n─── Upgrading QuoteToken ─────────────────────────────────────');
    const QuoteToken = await hre.ethers.getContractFactory('QuoteToken');
    const upgraded = await hre.upgrades.upgradeProxy(quoteTokenProxyAddr, QuoteToken, {
      kind: 'uups',
    });
    await upgraded.waitForDeployment();
    console.log('QuoteToken upgraded. Proxy address unchanged:', quoteTokenProxyAddr);

    const newImpl = await hre.upgrades.erc1967.getImplementationAddress(quoteTokenProxyAddr);
    console.log('New implementation:', newImpl);
    deployment.contracts.QuoteToken.implementation = newImpl;
    deployment.contracts.QuoteToken.upgradedAt = new Date().toISOString();
  }

  // ── Persist updated deployment JSON ──────────────────────────────────────

  fs.writeFileSync(deployPath, JSON.stringify(deployment, null, 2));
  console.log('\nDeployment JSON updated:', deployPath);
  console.log('\n✓ Upgrade complete. Proxy addresses are unchanged — no env updates needed.\n');
}

main().catch((e) => { console.error(e); process.exit(1); });
