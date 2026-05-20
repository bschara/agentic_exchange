import hre from 'hardhat';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { config as dotenvConfig } from 'dotenv';
dotenvConfig();

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const AGENTS = [
  { envKey: 'MARKET_MAKER_PK', name: 'MM-Prime', strategy: 'market_maker' },
  { envKey: 'MOMENTUM_TRADER_PK', name: 'Momentum-Alpha', strategy: 'momentum_trader' },
  { envKey: 'ARBITRAGE_AGENT_PK', name: 'Arb-Scanner', strategy: 'arbitrage_agent' },
  { envKey: 'RISK_MANAGER_PK', name: 'Risk-Shield', strategy: 'risk_manager' },
];

async function main() {
  const deploymentPath = path.join(__dirname, '../deployments/somnia-testnet.json');
  if (!fs.existsSync(deploymentPath)) {
    throw new Error('Run deploy.js first — deployments/somnia-testnet.json not found');
  }

  const deployment = JSON.parse(fs.readFileSync(deploymentPath, 'utf8'));
  const [deployer] = await hre.ethers.getSigners();
  console.log('Seeding with deployer:', deployer.address);

  const registry = await hre.ethers.getContractAt('AgentRegistry', deployment.contracts.AgentRegistry.address);
  const treasury = await hre.ethers.getContractAt('Treasury', deployment.contracts.Treasury.address);

  const fundAmount = hre.ethers.parseEther('0.1');

  for (const agent of AGENTS) {
    const pk = process.env[agent.envKey];
    if (!pk || pk.startsWith('0x_')) {
      console.warn(`Skipping ${agent.name} — ${agent.envKey} not set`);
      continue;
    }

    const wallet = new hre.ethers.Wallet(pk, hre.ethers.provider);
    const agentAddr = wallet.address;
    console.log(`\nRegistering ${agent.name} (${agentAddr})...`);

    const isReg = await registry.isRegistered(agentAddr);
    if (!isReg) {
      const tx = await registry.register(agentAddr, agent.name, agent.strategy);
      await tx.wait();
      console.log('  ✓ Registered');
    } else {
      console.log('  Already registered');
    }

    const tx2 = await treasury.depositFor(agentAddr, { value: fundAmount });
    await tx2.wait();
    console.log(`  ✓ Funded with ${hre.ethers.formatEther(fundAmount)} STT`);
  }

  console.log('\n✓ Seed complete');
  const allAgents = await registry.getAllAgents();
  console.log('Registered agents:', allAgents);
}

main().catch((e) => { console.error(e); process.exit(1); });
