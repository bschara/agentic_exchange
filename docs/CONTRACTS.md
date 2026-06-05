# Contracts — Agentic Exchange

Six Solidity contracts on Somnia testnet (chain 50312) — **all deployed as upgradeable UUPS proxies**. One deployer wallet manages everything; no individual agent wallets are needed.

`AgentCoordinator` is the central execution engine. All five system agents share its token pool, with per-agent virtual balances tracked on-chain (`agentTokenBalance[agentId]` / `agentQuoteBalance[agentId]`). STT platform fees are tracked per user wallet (`userSttBalance[ownerAddress]`). `Exchange` fires fill/cancel callbacks to the coordinator so virtual balances stay accurate.

---

## Directory Map

```
contracts/
├── contracts/
│   ├── AgentToken.sol          # ★ Upgradeable (UUPS)
│   │                           # Mintable ERC20 (sETH, Somnia ETH) — minted to coordinator pool
│   │                           # constructor() → _disableInitializers()
│   │                           # initialize(name, symbol) — sets owner = msg.sender
│   ├── QuoteToken.sol          # ★ Upgradeable (UUPS)
│   │                           # USDC-equivalent ERC20 with public faucet() for testnet top-up
│   │                           # constructor() → _disableInitializers()
│   │                           # initialize() — sets name/symbol/owner
│   ├── Exchange.sol            # ★ Upgradeable (UUPS)
│   │                           # Real on-chain LOB with two-token settlement
│   │                           # placeOrderForAgent(isBuy, price, amount, agentId) — new
│   │                           #   stores _orderAgentId[orderId] = agentId
│   │                           #   fires onAgentFill / onAgentCancel callbacks on coordinator
│   │                           # placeOrder() — unchanged for external callers
│   │                           # IAgentFillCallback interface (onAgentFill / onAgentCancel)
│   │                           # initialize(token, quoteToken)
│   ├── AgentCoordinator.sol    # ★ Upgradeable (UUPS)
│   │                           # constructor(platform, exchange) — immutables + _disableInitializers()
│   │                           # initialize(owner, llmAgentId, jsonApiAgentId)
│   │                           #
│   │                           # Token pool accounting:
│   │                           #   agentTokenBalance[agentId] / agentQuoteBalance[agentId]
│   │                           #   allocateToAgent(agentId, owner, tokenAmt, quoteAmt)
│   │                           #   getAgentAllocation(agentId) view
│   │                           #   onAgentFill / onAgentCancel (called by Exchange only)
│   │                           #
│   │                           # STT fee accounting:
│   │                           #   userSttBalance[ownerAddress]
│   │                           #   agentOwner[agentId]
│   │                           #   fund() payable — sets userSttBalance[msg.sender]
│   │                           #   depositStt(forOwner) payable
│   │                           #   getUserSttBalance(owner) view
│   │                           #
│   │                           # Decision pipeline:
│   │                           #   triggerAgentDecision / handlePriceData / handleDecision
│   │                           #   _executeRuleDecision (noise_trader, empty systemPrompt)
│   │                           #   _retrigger → self-loop
│   │                           #   winStreak, lastDecision, coalition, cancel-before-place
│   ├── AgentRegistry.sol       # ★ Upgradeable (UUPS)
│   │                           # Unified registry for system + user agents (string-ID keyed)
│   │                           # constructor() → _disableInitializers()
│   │                           # initialize(owner, coordinator)
│   │                           # registerAgent(agentId, name, icon, riskLevel, systemPrompt,
│   │                           #               priceUrl, selector, decimals) — open, anyone
│   │                           # agentOwner = msg.sender; emits AgentRegistered
│   │                           # pauseAgent / resumeAgent — onlyOwner OR agentOwner
│   │                           # getSystemPrompt / getPriceConfig / getRiskLevel — view, read by coordinator
│   ├── Treasury.sol            # ★ Upgradeable (UUPS)
│   │                           # Per-address ETH balances (deposit/withdraw/allocate)
│   └── MockPlatform.sol        # Local dev: simulates Somnia IAgentRequester callbacks
├── scripts/
│   ├── deploy-local.js         # Local Hardhat: deploys + allocates all 5 agents, writes somnia-local.json
│   │                           # Only DEPLOYER_PK needed — no agent PKs
│   │                           # Mints 50K sETH + 50K USDC to coordinator (5 × 10K each)
│   │                           # Calls allocateToAgent for each system agent
│   │                           # noise_trader registered with systemPrompt = "" (rule-based signal)
│   ├── deploy.js               # Testnet: same as deploy-local but for Somnia chain 50312
│   ├── upgrade.js              # Upgrades any/all proxy implementations (address unchanged)
│   │                           # Flags: UPGRADE_COORDINATOR UPGRADE_REGISTRY UPGRADE_EXCHANGE
│   │                           #        UPGRADE_TREASURY UPGRADE_AGENT_TOKEN UPGRADE_QUOTE_TOKEN
│   ├── platform-daemon.js      # Local: watches MockPlatform events, fires price + LLM callbacks
│   ├── test-local.js           # Local: one-shot smoke test for the full decision cycle
│   └── verify.js               # Testnet: sanity-check live contracts
└── deployments/
    ├── somnia-local.json       # Auto-generated: proxy addresses + ABIs (no PKs)
    └── somnia-testnet.json     # Auto-generated: proxy addresses + ABIs (gitignored)
```

---

## Prerequisites

- Node.js 18+
- **One funded deployer wallet** (~1 STT for deployment gas on testnet)
- Somnia testnet faucet: **https://testnet.somnia.network/**

---

## Deployment Walkthrough

### 1. Install dependencies

```bash
cd contracts && npm install
```

### 2. Generate a deployer wallet (if needed)

```bash
node -e "
const {ethers} = require('ethers');
const w = ethers.Wallet.createRandom();
console.log('DEPLOYER_PRIVATE_KEY=' + w.privateKey);
console.log('Address: ' + w.address);
"
```

### 3. Fund the deployer via faucet

Visit **https://testnet.somnia.network/** and request STT for the deployer address (~1 STT needed).

### 4. Configure `.env`

```bash
cp .env.example .env
```

```env
DEPLOYER_PRIVATE_KEY=0x...
SOMNIA_RPC_URL=https://dream-rpc.somnia.network
```

### 5. Deploy contracts

```bash
npx hardhat run scripts/deploy.js --network somnia
```

Output:

```
Deployer: 0xAbCd...
AgentToken (proxy):       0x0000...
QuoteToken (proxy):       0x1111...
Exchange (proxy):         0x2222...
Treasury (proxy):         0x3333...
AgentCoordinator (proxy): 0x4444...
AgentRegistry (proxy):    0x5555...
coordinator.setRegistry() done
Minted 50K sETH to AgentCoordinator
Minted 50K USDC to AgentCoordinator
─── Registering system agents and allocating virtual capital ───
  market_maker:    registered + 10K/10K allocated (prompt set)
  momentum_trader: registered + 10K/10K allocated (prompt set)
  arbitrage_agent: registered + 10K/10K allocated (prompt set)
  risk_manager:    registered + 10K/10K allocated (prompt set)
  noise_trader:    registered + 10K/10K allocated (rule-based)
Coordinator funded: 0.5 STT

═══ Paste into backend/.env ════════════════════════════════
DEPLOYER_PRIVATE_KEY=0x...
AGENT_TOKEN_ADDRESS=0x0000...
QUOTE_TOKEN_ADDRESS=0x1111...
EXCHANGE_ADDRESS=0x2222...
TREASURY_ADDRESS=0x3333...
AGENT_COORDINATOR_ADDRESS=0x4444...
AGENT_REGISTRY_ADDRESS=0x5555...
```

### 6. Upgrade (after code changes)

```bash
npx hardhat run scripts/upgrade.js --network somnia
# All proxies upgraded by default — address unchanged, state preserved
# Disable any: UPGRADE_EXCHANGE=false npx hardhat run scripts/upgrade.js --network somnia
```

---

## Local Development

```bash
# Terminal 1
cd contracts && npx hardhat node

# Terminal 2
cd contracts && npx hardhat run scripts/deploy-local.js --network localhost
# Writes somnia-local.json — backend auto-loads addresses from it

# Terminal 3
./start.sh   # starts platform-daemon + backend + frontend
```

---

## Contract Reference

### Exchange.sol — `placeOrderForAgent`

New function alongside the unchanged `placeOrder`:

```solidity
function placeOrderForAgent(
    bool isBuy, uint256 price, uint256 amount, string calldata agentId
) external returns (uint256 orderId)
```

- Stores `_orderAgentId[orderId] = agentId`
- After each fill: calls `IAgentFillCallback(msg.sender).onAgentFill(agentId, isBuy, tokenFill, quoteFill)`
- `quoteFill` = `lockedQuote * fill / totalAmount` (exact, not `fillPrice * fill`)
- After cancel: calls `IAgentFillCallback(msg.sender).onAgentCancel(agentId, isBuy, unfilledTokens, remainingQuote)`
- All callbacks wrapped in `try/catch` — a failing callback never reverts the trade

### AgentCoordinator.sol — `allocateToAgent`

```solidity
function allocateToAgent(
    string calldata agentId,
    address agentOwnerAddr,
    uint256 tokenAmount,   // sETH (18 decimals)
    uint256 quoteAmount    // USDC (18 decimals)
) external onlyOwner
```

Sets virtual token balances, caches owner address. Call once per agent at registration.

### AgentCoordinator.sol — STT functions

```solidity
function fund() external payable
// userSttBalance[msg.sender] += msg.value
// Called by users from frontend; msg.sender = their wallet = owner of all their agents

function depositStt(address forOwner) external payable
// userSttBalance[forOwner] += msg.value
// Deployer uses this to top up specific user pools

function getUserSttBalance(address agentOwnerAddr) external view returns (uint256)
```

### AgentCoordinator.sol — Noise Trader Rule

Empty `systemPrompt` in registry = rule-based. Detected in `handlePriceData`:

```solidity
if (bytes(IAgentRegistry(registry).getSystemPrompt(req.agentId)).length == 0) {
    _executeRuleDecision(req.agentId, fetchedPrice);
    return;
}
```

`_executeRuleDecision`: compares active buy vs sell order counts via `getActiveBuys().length` / `getActiveSells().length`. BUY when asks outnumber bids, SELL when bids outnumber asks, `block.prevrandao` when balanced. Skips placement (retriggers only) before the first trade establishes a reference price.

---

## Events Reference

### AgentCoordinator

```
SttDeposited(address indexed owner, uint256 amount)
AgentCapitalAllocated(string indexed agentId, uint256 tokenAmount, uint256 quoteAmount)
DecisionTriggered(uint256 indexed requestId, string agentId)
LLMRequestFired(uint256 indexed llmRequestId, string agentId, uint256 fetchedPrice, string context)
DecisionExecuted(uint256 indexed requestId, string agentId, string decision, uint256 price, uint256 orderId, uint256 streak)
DecisionFailed(uint256 indexed requestId, string agentId, string reason)
PriceFetchFailed(uint256 indexed requestId, string agentId)
LoopStopped(string agentId, string reason, uint256 sttBalance)
CoalitionFormed(string direction, uint256 agentCount, uint256 price, uint256 orderId)
AgentPaused(string agentId)
AgentResumed(string agentId)
```

### Exchange

```
OrderPlaced(uint256 indexed orderId, address indexed agent, bool isBuy, uint256 price, uint256 amount)
OrderFilled(uint256 indexed orderId, uint256 filledAmount, bool fullFill)
OrderCancelled(uint256 indexed orderId, address indexed agent)
TradeExecuted(uint256 indexed tradeId, uint256 buyOrderId, uint256 sellOrderId,
              address indexed buyer, address indexed seller, uint256 price, uint256 amount)
```

### AgentRegistry

```
AgentRegistered(string indexed agentId, address indexed agentOwner,
                string name, string icon, uint8 riskLevel)
```

---

## Test Suite

```bash
cd contracts && npx hardhat test
```

| File | Coverage |
|------|----------|
| `Exchange.test.cjs` | Order placement, matching engine, fills, cancellation, `placeOrderForAgent` callbacks |
| `AgentCoordinator.test.cjs` | Full pipeline, coalition detection, win streaks, peer signals, per-user STT deduction, `LoopStopped` |
| `AgentRegistry.test.cjs` | Registration, ownership, pause/resume |
| `Treasury.test.cjs` | Deposit, withdraw, allocate, getBalance |

Each file uses `loadFixture` for isolated state. `AgentCoordinator.test.cjs` uses `MockPlatform.simulatePriceCallback` / `simulateLLMCallback` to drive the full cycle.
