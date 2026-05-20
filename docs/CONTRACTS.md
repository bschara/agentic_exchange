# Contracts — Agentic Exchange

Three Solidity contracts on Somnia testnet (chain 50312) recording every agent order and trade permanently onchain. No real token movement — purely an onchain audit trail for the demo.

---

## Directory Map

```
contracts/
├── hardhat.config.js        # Solidity 0.8.20, Somnia network (6 gwei, chain 50312)
├── package.json             # type: "module" (ESM), hardhat + ethers v6 deps
├── .env                     # Private keys — NOT committed (see .gitignore)
├── contracts/
│   ├── Exchange.sol         # placeOrder / cancelOrder / executeTrade + events
│   ├── AgentRegistry.sol    # Agent registration, reputation, trade count
│   └── Treasury.sol         # Per-agent ETH balances (deposit / withdraw / allocate)
├── scripts/
│   ├── deploy.js            # Deploys all 3 contracts → writes deployments/somnia-testnet.json
│   ├── seed.js              # Registers 4 agents in registry, funds each in treasury
│   └── verify.js            # Sanity check: reads agent list + balances from live contracts
├── deployments/
│   └── somnia-testnet.json  # Auto-generated: addresses + ABIs. Tracked in git (no secrets).
├── artifacts/               # Hardhat build output (gitignored)
└── cache/                   # Hardhat compile cache (gitignored)
```

---

## Prerequisites

- Node.js 18+
- A funded deployer wallet (needs ~1 STT for deployment gas)
- Four funded agent wallets (need ~0.5 STT each)
- Somnia testnet faucet: **https://testnet.somnia.network/**

---

## Deployment Walkthrough

### 1. Install dependencies

```bash
cd contracts
npm install
```

### 2. Generate wallets (if you don't have them)

Run from `contracts/` (ethers is installed):

```bash
node -e "
const {ethers} = require('ethers');
const labels = ['DEPLOYER','MARKET_MAKER','MOMENTUM_TRADER','ARBITRAGE_AGENT','RISK_MANAGER'];
for (let i = 0; i < 5; i++) {
  const w = ethers.Wallet.createRandom();
  console.log(labels[i] + '_PK=' + w.privateKey);
  console.log(labels[i] + '_ADDR=' + w.address);
  console.log('');
}
"
```

### 3. Fund wallets

Visit **https://testnet.somnia.network/** and request STT for each of the 5 wallet addresses. The deployer needs ~1 STT; each agent wallet needs ~0.5 STT.

### 4. Configure `.env`

```bash
cp .env.example .env
# Fill in all private keys
```

```env
DEPLOYER_PRIVATE_KEY=0x...
SOMNIA_RPC_URL=https://dream-rpc.somnia.network
MARKET_MAKER_PK=0x...
MOMENTUM_TRADER_PK=0x...
ARBITRAGE_AGENT_PK=0x...
RISK_MANAGER_PK=0x...
```

### 5. Deploy contracts

```bash
npx hardhat run scripts/deploy.js --network somnia
```

Output:

```
Deploying from: 0xAbCd...
Exchange deployed:       0x1111...
AgentRegistry deployed:  0x2222...
Treasury deployed:       0x3333...

✓ Wrote deployments/somnia-testnet.json

Copy these into backend/.env:
  EXCHANGE_ADDRESS=0x1111...
  AGENT_REGISTRY_ADDRESS=0x2222...
  TREASURY_ADDRESS=0x3333...
```

### 6. Register agents and fund treasuries

```bash
npx hardhat run scripts/seed.js --network somnia
```

Registers all 4 agents in `AgentRegistry` and deposits 0.1 STT per agent into `Treasury`.

### 7. Verify deployment

```bash
npx hardhat run scripts/verify.js --network somnia
```

Prints all registered agents, their addresses, reputation, and treasury balance.

### 8. Configure backend

Copy the printed env vars into `backend/.env`, then restart the backend with `./start.sh`.

---

## Contract Reference

### `Exchange.sol`

Records buy/sell orders and matched trades. No actual token transfers.

**Structs:**

```solidity
struct Order {
    uint256 id;
    address agent;
    bool isBuy;        // true = buy order
    uint256 price;     // scaled 1e18
    uint256 amount;    // scaled 1e18
    uint256 timestamp;
    bool active;
}

struct Trade {
    uint256 id;
    uint256 buyOrderId;
    uint256 sellOrderId;
    address buyer;
    address seller;
    uint256 price;     // executed at sell order price
    uint256 amount;    // min(buyAmount, sellAmount)
    uint256 timestamp;
}
```

**Functions:**
| Function | Access | Description |
|----------|--------|-------------|
| `placeOrder(bool isBuy, uint256 price, uint256 amount)` | anyone | Creates order, returns `orderId` |
| `cancelOrder(uint256 orderId)` | order creator | Marks order inactive |
| `executeTrade(uint256 buyOrderId, uint256 sellOrderId)` | anyone | Matches two orders; requires `buyPrice >= sellPrice`; deactivates both |
| `getOrder(uint256 orderId)` | view | Returns `Order` struct |
| `getTrade(uint256 tradeId)` | view | Returns `Trade` struct |
| `getActiveOrders()` | view | Returns array of active order IDs |

**Events:**

```solidity
event OrderPlaced(uint256 indexed orderId, address indexed agent, bool isBuy, uint256 price, uint256 amount);
event OrderCancelled(uint256 indexed orderId, address indexed agent);
event TradeExecuted(uint256 indexed tradeId, uint256 buyOrderId, uint256 sellOrderId, address buyer, address seller, uint256 price, uint256 amount);
```

---

### `AgentRegistry.sol`

Maintains an on-chain registry of autonomous agents with metadata and reputation.

**Struct:**

```solidity
struct AgentInfo {
    address wallet;
    string name;
    string strategy;
    int256 reputation;       // starts at 100, adjusted by owner
    uint256 tradesExecuted;
    uint256 registeredAt;    // block.timestamp of registration
    bool active;
}
```

**Functions:**
| Function | Access | Description |
|----------|--------|-------------|
| `register(address agent, string name, string strategy)` | `onlyOwner` | Registers agent, sets initial reputation to 100 |
| `updateReputation(address agent, int256 delta)` | `onlyOwner` | Adds delta to reputation (can be negative) |
| `incrementTrades(address agent)` | `onlyOwner` | Increments `tradesExecuted` counter |
| `getAgent(address agent)` | view | Returns full `AgentInfo` struct |
| `getAllAgents()` | view | Returns array of all registered agent addresses |
| `isRegistered(address agent)` | view | Returns bool |

**Events:**

```solidity
event AgentRegistered(address indexed agent, string name, string strategy);
event ReputationUpdated(address indexed agent, int256 delta, int256 newReputation);
```

---

### `Treasury.sol`

Tracks per-agent STT balances. Owner can allocate between agents for simulated P&L settlement.

**Storage:**

```solidity
mapping(address => uint256) public balances;
address public owner;
```

**Functions:**
| Function | Access | Description |
|----------|--------|-------------|
| `deposit()` | anyone (payable) | Adds sent STT to caller's balance |
| `depositFor(address agent)` | anyone (payable) | Adds sent STT to named agent's balance |
| `withdraw(uint256 amount)` | caller | Transfers `amount` from caller's balance back to their wallet |
| `allocate(address from, address to, uint256 amount)` | `onlyOwner` | Moves balance between agents (simulated trading P&L) |
| `getBalance(address agent)` | view | Returns agent's current balance |
| `totalLocked()` | view | Returns total ETH held by contract |

**Events:**

```solidity
event Deposited(address indexed agent, uint256 amount);
event Withdrawn(address indexed agent, uint256 amount);
event Allocated(address indexed from, address indexed to, uint256 amount);
```

---

## Scripts Reference

### `scripts/deploy.js`

1. Gets deployer signer from hardhat
2. Deploys `Exchange`, `AgentRegistry`, `Treasury` sequentially
3. Reads compiled ABIs from `artifacts/`
4. Writes `deployments/somnia-testnet.json` with addresses + ABIs
5. Prints the exact env vars to copy into `backend/.env`

**Output file format** (`deployments/somnia-testnet.json`):

```json
{
  "network": "somnia-testnet",
  "chainId": 50312,
  "deployedAt": "2025-...",
  "deployer": "0x...",
  "contracts": {
    "Exchange": { "address": "0x...", "abi": [...] },
    "AgentRegistry": { "address": "0x...", "abi": [...] },
    "Treasury": { "address": "0x...", "abi": [...] }
  }
}
```

This file is tracked in git (no secrets — only addresses and ABIs). The backend reads it to initialize contract instances.

### `scripts/seed.js`

Requires: `deployments/somnia-testnet.json` + all 4 agent PKs in `.env`

For each agent:

1. Reads PK from env, skips gracefully if placeholder
2. Calls `AgentRegistry.register(address, name, strategy)` if not already registered
3. Calls `Treasury.depositFor(address)` with 0.1 STT

### `scripts/verify.js`

Requires: `deployments/somnia-testnet.json`

1. Calls `Exchange.getActiveOrders()` — prints count
2. Calls `AgentRegistry.getAllAgents()` — prints each agent's name, address, reputation
3. Calls `Treasury.getBalance()` for each — prints STT balance

---

## `deployments/somnia-testnet.json`

This file is intentionally **tracked in git** and **not gitignored**. It contains:

- Deployed contract addresses
- Full contract ABIs

It does **not** contain private keys (those stay in `.env`). The backend (`blockchain/contracts.py`) reads this file to load ABIs and instantiate contract instances. Without it, the backend falls back to minimal inline ABIs and logs a warning.

---

## Hardhat Notes

### ESM requirement

`package.json` has `"type": "module"`. This means all scripts must use ESM syntax:

```js
// correct
import hre from "hardhat";
import { ethers } from "hardhat";

// wrong — will throw
const hre = require("hardhat");
```

### Gas price

**Do not use dynamic gas estimation.** Somnia testnet's `eth_gasPrice` RPC returns unreliable values that cause transaction failures. Gas price is hardcoded in `hardhat.config.js`:

```js
gasPrice: 6000000000; // 6 gwei
```

The backend (`blockchain/client.py`) also hardcodes the same value.

### Placeholder PK guard

`hardhat.config.js` includes a `getAccounts()` function that returns `[]` when `DEPLOYER_PRIVATE_KEY` starts with `0x_`. This prevents hardhat from throwing a validation error when the `.env` file has placeholder values.

---

## Troubleshooting

| Symptom                                      | Cause                                          | Fix                                                                                                  |
| -------------------------------------------- | ---------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `deploy.js` fails with "insufficient funds"  | Deployer wallet needs more STT                 | Fund via faucet, allow a few seconds for balance to propagate                                        |
| `deploy.js` fails with "invalid private key" | Placeholder PK in `.env`                       | Fill real `DEPLOYER_PRIVATE_KEY`                                                                     |
| `seed.js` throws "Cannot read deployments"   | `deploy.js` hasn't been run                    | Run `deploy.js` first                                                                                |
| `seed.js` skips all agents                   | Agent PKs are still placeholder `0x_...`       | Fill all 4 agent PKs in `.env`                                                                       |
| `verify.js` shows 0 agents                   | `seed.js` was skipped or failed                | Run `seed.js`                                                                                        |
| Backend logs "contract not found"            | `backend/.env` still has placeholder addresses | Copy the addresses printed by `deploy.js`                                                            |
| Tx reverted on testnet                       | Gas too low or nonce conflict                  | Gas is hardcoded (shouldn't be the issue); nonce conflicts are handled by per-wallet Lock in backend |
