import hre from 'hardhat';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  console.log('Deploying contracts with:', deployer.address);
  const balance = await hre.ethers.provider.getBalance(deployer.address);
  console.log('Balance:', hre.ethers.formatEther(balance), 'STT');

  // Deploy Exchange
  const Exchange = await hre.ethers.getContractFactory('Exchange');
  const exchange = await Exchange.deploy();
  await exchange.waitForDeployment();
  const exchangeAddr = await exchange.getAddress();
  console.log('Exchange deployed to:', exchangeAddr);

  // Deploy AgentRegistry
  const AgentRegistry = await hre.ethers.getContractFactory('AgentRegistry');
  const registry = await AgentRegistry.deploy();
  await registry.waitForDeployment();
  const registryAddr = await registry.getAddress();
  console.log('AgentRegistry deployed to:', registryAddr);

  // Deploy Treasury
  const Treasury = await hre.ethers.getContractFactory('Treasury');
  const treasury = await Treasury.deploy();
  await treasury.waitForDeployment();
  const treasuryAddr = await treasury.getAddress();
  console.log('Treasury deployed to:', treasuryAddr);

  // Get ABIs from artifacts
  const exchangeArtifact = await hre.artifacts.readArtifact('Exchange');
  const registryArtifact = await hre.artifacts.readArtifact('AgentRegistry');
  const treasuryArtifact = await hre.artifacts.readArtifact('Treasury');

  const deployment = {
    chainId: 50312,
    deployedAt: new Date().toISOString(),
    deployer: deployer.address,
    contracts: {
      Exchange: { address: exchangeAddr },
      AgentRegistry: { address: registryAddr },
      Treasury: { address: treasuryAddr },
    },
    abis: {
      Exchange: exchangeArtifact.abi,
      AgentRegistry: registryArtifact.abi,
      Treasury: treasuryArtifact.abi,
    },
  };

  const deploymentsDir = path.join(__dirname, '../deployments');
  if (!fs.existsSync(deploymentsDir)) fs.mkdirSync(deploymentsDir, { recursive: true });

  const outPath = path.join(deploymentsDir, 'somnia-testnet.json');
  fs.writeFileSync(outPath, JSON.stringify(deployment, null, 2));
  console.log('\nDeployment saved to:', outPath);
  console.log('\nAdd to backend/.env:');
  console.log(`EXCHANGE_ADDRESS=${exchangeAddr}`);
  console.log(`AGENT_REGISTRY_ADDRESS=${registryAddr}`);
  console.log(`TREASURY_ADDRESS=${treasuryAddr}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
