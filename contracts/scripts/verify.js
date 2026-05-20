import hre from 'hardhat';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function main() {
  const deploymentPath = path.join(__dirname, '../deployments/somnia-testnet.json');
  if (!fs.existsSync(deploymentPath)) {
    throw new Error('deployments/somnia-testnet.json not found — run deploy.js first');
  }

  const deployment = JSON.parse(fs.readFileSync(deploymentPath, 'utf8'));
  console.log('Verifying deployment on chain', deployment.chainId);
  console.log('Deployed at:', deployment.deployedAt);

  const exchange = await hre.ethers.getContractAt('Exchange', deployment.contracts.Exchange.address);
  const registry = await hre.ethers.getContractAt('AgentRegistry', deployment.contracts.AgentRegistry.address);
  const treasury = await hre.ethers.getContractAt('Treasury', deployment.contracts.Treasury.address);

  const activeOrders = await exchange.getActiveOrders();
  console.log('\nExchange active orders:', activeOrders.length);

  const allAgents = await registry.getAllAgents();
  console.log('AgentRegistry agents:', allAgents.length);
  for (const addr of allAgents) {
    const info = await registry.getAgent(addr);
    const bal = await treasury.getBalance(addr);
    console.log(`  ${info.name} (${addr.slice(0, 6)}...) — reputation: ${info.reputation}, treasury: ${hre.ethers.formatEther(bal)} STT`);
  }

  console.log('\n✓ All contracts responding correctly');
}

main().catch((e) => { console.error(e); process.exit(1); });
