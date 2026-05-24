import '@nomicfoundation/hardhat-ethers';
import '@nomicfoundation/hardhat-chai-matchers';
import '@nomicfoundation/hardhat-network-helpers';
import { config as dotenvConfig } from 'dotenv';
dotenvConfig();

function getAccounts() {
  const pk = process.env.DEPLOYER_PRIVATE_KEY;
  if (!pk || pk.startsWith('0x_')) return [];
  return [pk];
}

/** @type import('hardhat/config').HardhatUserConfig */
export default {
  solidity: {
    version: '0.8.20',
    settings: {
      optimizer: { enabled: true, runs: 200 },
    },
  },
  networks: {
    localhost: {
      url: 'http://127.0.0.1:8545',
      chainId: 31337,
    },
    somnia: {
      url: process.env.SOMNIA_RPC_URL || 'https://dream-rpc.somnia.network',
      chainId: 50312,
      accounts: getAccounts(),
      gasPrice: 6000000000,
      timeout: 60000,
    },
  },
  paths: {
    sources: './contracts',
    tests: './test',
    cache: './cache',
    artifacts: './artifacts',
  },
};
