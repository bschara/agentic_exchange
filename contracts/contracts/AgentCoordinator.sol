// SPDX-License-Identifier: MIT
pragma solidity ^0.8.22;

import "@openzeppelin/contracts/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts/proxy/utils/UUPSUpgradeable.sol";

// ── Somnia Agent Platform interfaces ────────────────────────────────────────────

interface IAgentRequester {
    enum ResponseStatus { None, Pending, Success, Failed, TimedOut }

    struct Response {
        ResponseStatus status;
        bytes result;
        uint256 executionCost;
    }

    struct Request {
        uint256 agentId;
        address callbackAddress;
        bytes4 callbackSelector;
        bytes payload;
    }

    function createRequest(
        uint256 agentId,
        address callbackAddress,
        bytes4 callbackSelector,
        bytes calldata payload
    ) external payable returns (uint256 requestId);

    function getRequestDeposit() external view returns (uint256);
}

interface IJSONAPIAgent {
    function fetchUint(
        string calldata url,
        string calldata selector,
        uint8 decimals
    ) external;
}

interface ILLMAgent {
    function inferString(
        string calldata prompt,
        string calldata system,
        bool chainOfThought,
        string[] calldata allowedValues
    ) external;
}

interface IERC20Approvable {
    function approve(address spender, uint256 amount) external returns (bool);
}

interface IExchange {
    function placeOrder(bool isBuy, uint256 price, uint256 amount) external returns (uint256 orderId);
    function placeOrderForAgent(bool isBuy, uint256 price, uint256 amount, string calldata agentId) external returns (uint256 orderId);
    function cancelOrder(uint256 orderId) external;
    function getLastTradePrice() external view returns (uint256);
    function hasTraded() external view returns (bool);
    function getBestBid() external view returns (uint256 price, bool exists);
    function getBestAsk() external view returns (uint256 price, bool exists);
    function getActiveBuys() external view returns (uint256[] memory);
    function getActiveSells() external view returns (uint256[] memory);
}

// AgentRegistry view interface — coordinator reads config from registry at runtime
interface IAgentRegistry {
    function isRegistered(string calldata agentId) external view returns (bool);
    function getSystemPrompt(string calldata agentId) external view returns (string memory);
    function getPriceConfig(string calldata agentId) external view
        returns (string memory priceUrl, string memory selector, uint8 decimals);
    function getRiskLevel(string calldata agentId) external view returns (uint8);
}

// ── AgentCoordinator ────────────────────────────────────────────────────────────
//
// Three-step autonomous agent pipeline with peer awareness and adaptive sizing:
//   1. triggerAgentDecision() → Somnia JSON API agent fetches real ETH price
//   2. handlePriceData() callback → builds on-chain context (price + peers + streak)
//                                 → fires LLM Inference
//   3. handleDecision() callback → validator consensus → Exchange.placeOrder()
//                                → stores decision for peers → coalition check
//                                → updates win streak → _retrigger()
//
// Python is only the trigger. All data sourcing, peer communication, and
// decision-making is on-chain.
//
// Agent config (systemPrompt, priceUrl, selector, decimals, riskLevel) lives in
// AgentRegistry. Coordinator reads it via view calls and owns only runtime state:
// winStreak, lastDecision, agentPaused, lastOrderId, pendingRequests, _agentIdList.
//
contract AgentCoordinator is Initializable, UUPSUpgradeable {
    // Base order size; scales with win streak via _orderAmount(), capped at 5×
    uint256 public constant ORDER_AMOUNT_BASE = 0.001e18;
    uint256 public constant ORDER_AMOUNT_MAX  = 0.005e18;
    uint256 public constant PRICE_OFFSET_BPS  = 10; // 0.1%

    /// @custom:oz-upgrades-unsafe-allow state-variable-immutable
    IAgentRequester public immutable platform;
    /// @custom:oz-upgrades-unsafe-allow state-variable-immutable
    IExchange       public immutable exchange;
    address         public owner;

    uint256 public llmAgentId;
    uint256 public jsonApiAgentId;

    // Trusted registry — reads config from it; registry calls addAgentToList, pauseAgent, resumeAgent
    address public registry;

    // ── Runtime state (owned by coordinator) ─────────────────────────────────

    // Last BUY/SELL/HOLD per agent — read by peers in _buildContext next cycle
    mapping(string => string) public lastDecision;

    // Consecutive filled-order streak per agent — drives _orderAmount()
    mapping(string => uint256) public winStreak;

    // Pause flags — halts the self-retriggering loop to save STT
    mapping(string => bool) public agentPaused;

    // Ordered list of agent IDs — iterated for peer signals + coalition
    string[] private _agentIdList;

    // Stage-1 pending: JSON API fetch in flight
    struct PriceRequest {
        string agentId;
        bool   exists;
    }
    mapping(uint256 => PriceRequest) public pendingPriceRequests;

    // Stage-2 pending: LLM inference in flight
    struct LLMRequest {
        string  agentId;
        uint256 fetchedPrice;
        bool    exists;
    }
    mapping(uint256 => LLMRequest) public pendingLLMRequests;

    // Tracks the last order placed per agent so stale orders can be cancelled before requoting
    mapping(string => uint256) public lastOrderId;
    // Tracks the last BID order for market_maker (lastOrderId only tracks the ASK side)
    mapping(string => uint256) public lastBidOrderId;

    // Per-agent virtual balances within the shared coordinator pool (18 decimals)
    // Set at registration; deltas applied off-chain from Exchange TradeExecuted events
    mapping(string => uint256) public agentTokenBalance;
    mapping(string => uint256) public agentQuoteBalance;

    // Per-user STT balance — all agents owned by the same address share one pool
    mapping(address => uint256) public userSttBalance;
    // Cached owner per agentId — set in allocateToAgent, read on every platform call
    mapping(string => address) public agentOwner;

    string[] private _allowedValues;

    // ── Events ───────────────────────────────────────────────────────────────────

    event AgentPaused(string agentId);
    event AgentResumed(string agentId);
    event AgentCapitalAllocated(string indexed agentId, uint256 tokenAmount, uint256 quoteAmount);
    event SttDeposited(address indexed owner, uint256 amount);
    event DecisionTriggered(uint256 indexed requestId, string agentId);
    event PriceFetchFailed(uint256 indexed requestId, string agentId);

    event LLMRequestFired(
        uint256 indexed llmRequestId,
        string agentId,
        uint256 fetchedPrice,
        string context
    );

    event DecisionExecuted(
        uint256 indexed requestId,
        string agentId,
        string decision,
        uint256 price,
        uint256 orderId,
        uint256 streak
    );

    event DecisionFailed(uint256 indexed requestId, string agentId, string reason);
    event LoopStopped(string agentId, string reason, uint256 balance);
    event CoalitionFormed(string direction, uint256 agentCount, uint256 price, uint256 orderId);

    // ── Modifiers ─────────────────────────────────────────────────────────────

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    modifier onlyOwnerOrRegistry() {
        require(msg.sender == owner || msg.sender == registry, "Not authorized");
        _;
    }

    // ── Constructor (immutables only) ─────────────────────────────────────────
    // Only sets immutable platform + exchange; prevents direct initialization
    // of the implementation contract (must go through the proxy).

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor(address _platform, address _exchange) {
        platform = IAgentRequester(_platform);
        exchange = IExchange(_exchange);
        _disableInitializers();
    }

    // ── Initializer (called once via proxy on first deploy) ───────────────────

    function initialize(
        address _owner,
        uint256 _llmAgentId,
        uint256 _jsonApiAgentId
    ) external initializer {
        owner          = _owner;
        llmAgentId     = _llmAgentId;
        jsonApiAgentId = _jsonApiAgentId;

        _allowedValues.push("BUY");
        _allowedValues.push("SELL");
        _allowedValues.push("HOLD");
    }

    receive() external payable {}

    // ── Registry wiring ───────────────────────────────────────────────────────

    function setRegistry(address _registry) external onlyOwner {
        registry = _registry;
    }

    // Called by AgentRegistry.registerAgent() to keep peer-signal list current.
    function addAgentToList(string calldata agentId) external onlyOwnerOrRegistry {
        if (!_agentIdRegistered(agentId)) _agentIdList.push(agentId);
    }

    // ── Operational controls (callable by registry on behalf of agent owners) ─

    function pauseAgent(string calldata agentId) external onlyOwnerOrRegistry {
        agentPaused[agentId] = true;
        emit AgentPaused(agentId);
    }

    function resumeAgent(string calldata agentId) external onlyOwnerOrRegistry {
        agentPaused[agentId] = false;
        emit AgentResumed(agentId);
    }

    function setLlmAgentId(uint256 agentId) external onlyOwner {
        llmAgentId = agentId;
    }

    function setJsonApiAgentId(uint256 agentId) external onlyOwner {
        jsonApiAgentId = agentId;
    }

    // Deposit STT for the caller's own agent pool (called by users via the frontend).
    function fund() external payable {
        userSttBalance[msg.sender] += msg.value;
        emit SttDeposited(msg.sender, msg.value);
    }

    // Deposit STT on behalf of another address (used by deployer for system agents / top-ups).
    function depositStt(address forOwner) external payable {
        userSttBalance[forOwner] += msg.value;
        emit SttDeposited(forOwner, msg.value);
    }

    function getUserSttBalance(address agentOwnerAddr) external view returns (uint256) {
        return userSttBalance[agentOwnerAddr];
    }

    // Set the initial virtual capital allocation for an agent within the shared pool.
    // Also caches the owner for per-user STT deduction on each platform call.
    // Called by the backend once when an agent is registered.
    function allocateToAgent(
        string calldata agentId,
        address agentOwnerAddr,
        uint256 tokenAmount,
        uint256 quoteAmount
    ) external onlyOwner {
        require(IAgentRegistry(registry).isRegistered(agentId), "Agent not registered");
        agentTokenBalance[agentId] = tokenAmount;
        agentQuoteBalance[agentId] = quoteAmount;
        agentOwner[agentId] = agentOwnerAddr;
        emit AgentCapitalAllocated(agentId, tokenAmount, quoteAmount);
    }

    // Returns both virtual balances for an agent in one call.
    function getAgentAllocation(string calldata agentId)
        external view returns (uint256 tokenBalance, uint256 quoteBalance)
    {
        return (agentTokenBalance[agentId], agentQuoteBalance[agentId]);
    }

    // ── Fill/cancel callbacks from Exchange ───────────────────────────────────
    // Called by Exchange after each partial or full fill for orders placed via
    // placeOrderForAgent. Updates the agent's virtual balance within the shared pool.

    function onAgentFill(
        string calldata agentId,
        bool isBuy,
        uint256 tokenFill,
        uint256 quoteFill
    ) external {
        require(msg.sender == address(exchange), "Only exchange");
        if (isBuy) {
            // Buyer received sETH; quote was already deducted at order placement
            agentTokenBalance[agentId] += tokenFill;
        } else {
            // Seller received exact USDC amount computed by Exchange; token was already deducted
            agentQuoteBalance[agentId] += quoteFill;
        }
    }

    function onAgentCancel(
        string calldata agentId,
        bool isBuy,
        uint256 unfilledTokens,
        uint256 remainingQuote
    ) external {
        require(msg.sender == address(exchange), "Only exchange");
        if (isBuy) {
            // Unfilled quote is being refunded to coordinator; restore agent's virtual quote
            agentQuoteBalance[agentId] += remainingQuote;
        } else {
            // Unfilled sETH is being refunded to coordinator; restore agent's virtual token balance
            agentTokenBalance[agentId] += unfilledTokens;
        }
    }

    function approveToken(address _token, address spender, uint256 amount) external onlyOwner {
        IERC20Approvable(_token).approve(spender, amount);
    }

    function withdraw() external onlyOwner {
        (bool ok, ) = payable(owner).call{value: address(this).balance}("");
        require(ok, "Withdraw failed");
    }

    // ── Step 1: Trigger — Python calls this once per agent loop ──────────────────
    //
    // Reads price config from registry, fires Somnia JSON API price fetch.
    //
    function triggerAgentDecision(string calldata agentId) external onlyOwner {
        require(!agentPaused[agentId], "Agent is paused");
        require(IAgentRegistry(registry).isRegistered(agentId), "Agent not registered");

        uint256 deposit = platform.getRequestDeposit();
        address agentOwnerAddr = agentOwner[agentId];
        // Reserve 2 deposits up front: 1 for JSON API, 1 for the LLM call that follows.
        // Rule-based agents (empty prompt) only use 1, but the check is conservative.
        require(userSttBalance[agentOwnerAddr] >= deposit * 2, "Insufficient STT balance");
        userSttBalance[agentOwnerAddr] -= deposit;

        (string memory priceUrl, string memory selector, uint8 decimals) =
            IAgentRegistry(registry).getPriceConfig(agentId);

        bytes memory payload = abi.encodeWithSelector(
            IJSONAPIAgent.fetchUint.selector,
            priceUrl,
            selector,
            decimals
        );

        uint256 reqId = platform.createRequest{value: deposit}(
            jsonApiAgentId,
            address(this),
            this.handlePriceData.selector,
            payload
        );

        pendingPriceRequests[reqId] = PriceRequest(agentId, true);
        emit DecisionTriggered(reqId, agentId);
    }

    // ── Step 1b (optional): Backend injects price directly, skipping JSON API ────
    function triggerWithPrice(string calldata agentId, uint256 rawPrice) external onlyOwner {
        require(!agentPaused[agentId], "Agent is paused");
        require(IAgentRegistry(registry).isRegistered(agentId), "Agent not registered");
        uint256 deposit = platform.getRequestDeposit();
        address agentOwnerAddr = agentOwner[agentId];
        require(userSttBalance[agentOwnerAddr] >= deposit, "Insufficient STT balance");
        userSttBalance[agentOwnerAddr] -= deposit;
        _fireLLMRequest(agentId, rawPrice);
        emit DecisionTriggered(0, agentId);
    }

    // ── Step 2: Callback — Somnia JSON API agent returns the price ───────────────
    function handlePriceData(
        uint256 requestId,
        IAgentRequester.Response[] memory responses,
        IAgentRequester.ResponseStatus status,
        IAgentRequester.Request memory /* details */
    ) external {
        require(msg.sender == address(platform), "Only platform");

        PriceRequest memory req = pendingPriceRequests[requestId];
        if (!req.exists) return;
        delete pendingPriceRequests[requestId];

        if (status != IAgentRequester.ResponseStatus.Success || responses.length == 0) {
            emit PriceFetchFailed(requestId, req.agentId);
            return;
        }

        uint256 fetchedPrice = abi.decode(responses[0].result, (uint256));

        // Empty systemPrompt = rule-based agent (e.g. noise_trader); skip LLM entirely.
        if (bytes(IAgentRegistry(registry).getSystemPrompt(req.agentId)).length == 0) {
            _executeRuleDecision(req.agentId, fetchedPrice);
            return;
        }
        _fireLLMRequest(req.agentId, fetchedPrice);
    }

    // ── Internal: fire LLM inference request with a known price ─────────────────
    function _fireLLMRequest(string memory agentId, uint256 fetchedPrice) internal {
        // Deduct the LLM deposit from the agent's owner STT balance.
        uint256 deposit = platform.getRequestDeposit();
        userSttBalance[agentOwner[agentId]] -= deposit;

        string memory context   = _buildContext(fetchedPrice, agentId);
        string memory sysPrompt = IAgentRegistry(registry).getSystemPrompt(agentId);

        bytes memory llmPayload = abi.encodeWithSelector(
            ILLMAgent.inferString.selector,
            context,
            sysPrompt,
            false,
            _allowedValues
        );

        uint256 llmReqId = platform.createRequest{value: platform.getRequestDeposit()}(
            llmAgentId,
            address(this),
            this.handleDecision.selector,
            llmPayload
        );

        pendingLLMRequests[llmReqId] = LLMRequest(agentId, fetchedPrice, true);
        emit LLMRequestFired(llmReqId, agentId, fetchedPrice, context);
    }

    // ── Step 3: Callback — Somnia LLM validators reach consensus ─────────────────
    function handleDecision(
        uint256 requestId,
        IAgentRequester.Response[] memory responses,
        IAgentRequester.ResponseStatus status,
        IAgentRequester.Request memory /* details */
    ) external {
        require(msg.sender == address(platform), "Only platform");

        LLMRequest memory req = pendingLLMRequests[requestId];
        if (!req.exists) return;
        delete pendingLLMRequests[requestId];

        if (status != IAgentRequester.ResponseStatus.Success || responses.length == 0) {
            winStreak[req.agentId] = 0;
            emit DecisionFailed(requestId, req.agentId, "No consensus or timeout");
            _retrigger(req.agentId);
            return;
        }

        // Cancel stale orders from the previous cycle before placing new ones
        uint256 prev = lastOrderId[req.agentId];
        if (prev > 0) {
            try exchange.cancelOrder(prev) {} catch {}
            lastOrderId[req.agentId] = 0;
        }
        uint256 prevBid = lastBidOrderId[req.agentId];
        if (prevBid > 0) {
            try exchange.cancelOrder(prevBid) {} catch {}
            lastBidOrderId[req.agentId] = 0;
        }

        (, , uint8 decimals) = IAgentRegistry(registry).getPriceConfig(req.agentId);
        // Use on-chain sETH price when available; seed from ETH/USD oracle on first run
        uint256 basePrice = exchange.hasTraded()
            ? exchange.getLastTradePrice()
            : _toWei(req.fetchedPrice, decimals);

        // Market maker posts both sides simultaneously to actually make markets.
        if (_strEq(req.agentId, "market_maker")) {
            uint256 bidPrice = basePrice * (10000 - PRICE_OFFSET_BPS) / 10000;
            uint256 askPrice = basePrice * (10000 + PRICE_OFFSET_BPS) / 10000;
            uint256 bidQuote = bidPrice * ORDER_AMOUNT_BASE / 1e18;
            // Deduct virtual quote for the BUY side before placing
            if (agentQuoteBalance[req.agentId] >= bidQuote) {
                agentQuoteBalance[req.agentId] -= bidQuote;
                try exchange.placeOrderForAgent(true, bidPrice, ORDER_AMOUNT_BASE, req.agentId) returns (uint256 bidId) {
                    lastBidOrderId[req.agentId] = bidId;
                    emit DecisionExecuted(requestId, req.agentId, "BUY", bidPrice, bidId, 0);
                } catch {
                    agentQuoteBalance[req.agentId] += bidQuote; // restore on failure
                }
            }
            // Deduct virtual token for the SELL side before placing
            if (agentTokenBalance[req.agentId] >= ORDER_AMOUNT_BASE) {
                agentTokenBalance[req.agentId] -= ORDER_AMOUNT_BASE;
                try exchange.placeOrderForAgent(false, askPrice, ORDER_AMOUNT_BASE, req.agentId) returns (uint256 askId) {
                    lastOrderId[req.agentId] = askId;
                    emit DecisionExecuted(requestId, req.agentId, "SELL", askPrice, askId, 0);
                } catch {
                    agentTokenBalance[req.agentId] += ORDER_AMOUNT_BASE; // restore on failure
                }
            }
            _retrigger(req.agentId);
            return;
        }

        string memory decision = abi.decode(responses[0].result, (string));
        bool isBuy  = _strEq(decision, "BUY");
        bool isSell = _strEq(decision, "SELL");

        lastDecision[req.agentId] = decision;

        if (isBuy || isSell) {
            uint256 agreeCount = _coalitionCount(decision);
            if (agreeCount == 3) {
                _fireCoalitionOrder(isBuy, basePrice);
            }
        }

        if (!isBuy && !isSell) {
            winStreak[req.agentId] = 0;
            emit DecisionExecuted(requestId, req.agentId, "HOLD", 0, 0, 0);
            _retrigger(req.agentId);
            return;
        }

        uint256 orderPrice = isBuy
            ? basePrice * (10000 + PRICE_OFFSET_BPS) / 10000
            : basePrice * (10000 - PRICE_OFFSET_BPS) / 10000;

        uint256 orderAmt = _orderAmount(req.agentId);
        bool canPlace;
        if (isBuy) {
            uint256 quoteNeeded = orderPrice * orderAmt / 1e18;
            canPlace = agentQuoteBalance[req.agentId] >= quoteNeeded;
            if (canPlace) agentQuoteBalance[req.agentId] -= quoteNeeded;
        } else {
            canPlace = agentTokenBalance[req.agentId] >= orderAmt;
            if (canPlace) agentTokenBalance[req.agentId] -= orderAmt;
        }

        if (!canPlace) {
            lastDecision[req.agentId] = "HOLD"; // don't broadcast blocked decision to peers
            winStreak[req.agentId] = 0;
            emit DecisionFailed(requestId, req.agentId, "Insufficient virtual balance");
            _retrigger(req.agentId);
            return;
        }

        try exchange.placeOrderForAgent(isBuy, orderPrice, orderAmt, req.agentId) returns (uint256 orderId) {
            winStreak[req.agentId]++;
            lastOrderId[req.agentId] = orderId;
            emit DecisionExecuted(requestId, req.agentId, decision, orderPrice, orderId, winStreak[req.agentId]);
        } catch {
            // Restore virtual balance if exchange rejected the order
            if (isBuy) {
                agentQuoteBalance[req.agentId] += orderPrice * orderAmt / 1e18;
            } else {
                agentTokenBalance[req.agentId] += orderAmt;
            }
            winStreak[req.agentId] = 0;
            emit DecisionFailed(requestId, req.agentId, "placeOrder reverted");
        }

        _retrigger(req.agentId);
    }

    // ── Rule-based decision (no LLM) — order-book balance ───────────────────────
    //
    // Counterbalances the market: buy when asks > bids (others selling),
    // sell when bids > asks (others buying), random when balanced.
    // This ensures the noise bot always provides liquidity to the thin side.
    //
    function _executeRuleDecision(string memory agentId, uint256 fetchedPrice) internal {
        bool isBuy;
        uint256 buyDepth  = exchange.getActiveBuys().length;
        uint256 sellDepth = exchange.getActiveSells().length;
        if (sellDepth > buyDepth) {
            isBuy = true;   // more asks than bids — provide buy side
        } else if (buyDepth > sellDepth) {
            isBuy = false;  // more bids than asks — provide sell side
        } else {
            isBuy = block.prevrandao % 2 == 0;  // balanced — random
        }

        // Use last trade price when available; fall back to oracle on cold start
        (, , uint8 decimals) = IAgentRegistry(registry).getPriceConfig(agentId);
        uint256 basePrice = exchange.hasTraded()
            ? exchange.getLastTradePrice()
            : _toWei(fetchedPrice, decimals);
        uint256 orderPrice = isBuy
            ? basePrice * (10000 + PRICE_OFFSET_BPS) / 10000
            : basePrice * (10000 - PRICE_OFFSET_BPS) / 10000;

        // Scale order size with imbalance so noise bot absorbs directional pressure faster
        uint256 imbalance = sellDepth > buyDepth ? sellDepth - buyDepth : buyDepth - sellDepth;
        uint256 orderAmt  = _orderAmount(agentId);
        if (imbalance > 1) orderAmt = orderAmt * imbalance;
        if (orderAmt > ORDER_AMOUNT_MAX * 5) orderAmt = ORDER_AMOUNT_MAX * 5;

        // Cancel stale order from previous cycle
        uint256 prev = lastOrderId[agentId];
        if (prev > 0) { try exchange.cancelOrder(prev) {} catch {} lastOrderId[agentId] = 0; }
        uint256 prevBid = lastBidOrderId[agentId];
        if (prevBid > 0) { try exchange.cancelOrder(prevBid) {} catch {} lastBidOrderId[agentId] = 0; }

        if (isBuy) {
            uint256 q = orderPrice * orderAmt / 1e18;
            if (agentQuoteBalance[agentId] >= q) {
                agentQuoteBalance[agentId] -= q;
                try exchange.placeOrderForAgent(true, orderPrice, orderAmt, agentId) returns (uint256 oid) {
                    lastOrderId[agentId] = oid;
                    lastDecision[agentId] = "BUY";
                    emit DecisionExecuted(0, agentId, "BUY", orderPrice, oid, winStreak[agentId]);
                } catch { agentQuoteBalance[agentId] += q; }
            }
        } else {
            if (agentTokenBalance[agentId] >= orderAmt) {
                agentTokenBalance[agentId] -= orderAmt;
                try exchange.placeOrderForAgent(false, orderPrice, orderAmt, agentId) returns (uint256 oid) {
                    lastOrderId[agentId] = oid;
                    lastDecision[agentId] = "SELL";
                    emit DecisionExecuted(0, agentId, "SELL", orderPrice, oid, winStreak[agentId]);
                } catch { agentTokenBalance[agentId] += orderAmt; }
            }
        }

        _retrigger(agentId);
    }

    // ── Self-re-trigger ───────────────────────────────────────────────────────────
    function _retrigger(string memory agentId) internal {
        if (agentPaused[agentId]) {
            emit LoopStopped(agentId, "paused", userSttBalance[agentOwner[agentId]]);
            return;
        }

        if (!IAgentRegistry(registry).isRegistered(agentId)) {
            emit LoopStopped(agentId, "No agent config", userSttBalance[agentOwner[agentId]]);
            return;
        }

        address agentOwnerAddr = agentOwner[agentId];
        uint256 deposit = platform.getRequestDeposit();
        // Reserve 2 deposits: 1 for this JSON API call, 1 for the LLM call that follows.
        if (userSttBalance[agentOwnerAddr] < deposit * 2) {
            emit LoopStopped(agentId, "Insufficient STT", userSttBalance[agentOwnerAddr]);
            return;
        }
        userSttBalance[agentOwnerAddr] -= deposit;

        (string memory priceUrl, string memory selector, uint8 decimals) =
            IAgentRegistry(registry).getPriceConfig(agentId);

        bytes memory payload = abi.encodeWithSelector(
            IJSONAPIAgent.fetchUint.selector,
            priceUrl,
            selector,
            decimals
        );
        uint256 newReqId = platform.createRequest{value: deposit}(
            jsonApiAgentId,
            address(this),
            this.handlePriceData.selector,
            payload
        );
        pendingPriceRequests[newReqId] = PriceRequest(agentId, true);
        emit DecisionTriggered(newReqId, agentId);
    }

    // ── Helpers ──────────────────────────────────────────────────────────────────

    function _agentIdRegistered(string memory id) internal view returns (bool) {
        for (uint256 i = 0; i < _agentIdList.length; i++) {
            if (_strEq(_agentIdList[i], id)) return true;
        }
        return false;
    }

    function _buildPeerSignals(string memory excludeId) internal view returns (string memory) {
        bytes memory result;
        bool first = true;
        for (uint256 i = 0; i < _agentIdList.length; i++) {
            string memory id = _agentIdList[i];
            if (_strEq(id, excludeId)) continue;
            string memory dec = lastDecision[id];
            if (bytes(dec).length == 0) continue;
            if (!first) result = abi.encodePacked(result, ",");
            result = abi.encodePacked(result, id, "=", dec);
            first = false;
        }
        return first ? "none" : string(result);
    }

    function _orderAmount(string memory agentId) internal view returns (uint256) {
        uint256 streak = winStreak[agentId];
        uint256 multiplier = 1 + streak / 5;
        uint8   risk   = IAgentRegistry(registry).getRiskLevel(agentId);
        // risk==0 or unregistered → 1× baseline; risk 1-5 → 0.4×…2×
        uint256 riskFactor = risk == 0 ? 30 : uint256(risk) * 12;
        uint256 amt = ORDER_AMOUNT_BASE * multiplier * riskFactor / 30;
        return amt > ORDER_AMOUNT_MAX ? ORDER_AMOUNT_MAX : amt;
    }

    function _coalitionCount(string memory direction) internal view returns (uint256 count) {
        for (uint256 i = 0; i < _agentIdList.length; i++) {
            if (_strEq(lastDecision[_agentIdList[i]], direction)) count++;
        }
    }

    function _fireCoalitionOrder(bool isBuy, uint256 basePrice) internal {
        uint256 coalitionAmt = ORDER_AMOUNT_BASE * 3;
        uint256 price = isBuy
            ? basePrice * (10000 + PRICE_OFFSET_BPS) / 10000
            : basePrice * (10000 - PRICE_OFFSET_BPS) / 10000;
        // Coalition orders are placed on behalf of the coordinator itself (no per-agent id)
        try exchange.placeOrder(isBuy, price, coalitionAmt) returns (uint256 orderId) {
            emit CoalitionFormed(isBuy ? "BUY" : "SELL", 3, price, orderId);
        } catch {}
    }

    function _buildContext(uint256 fetchedPrice, string memory agentId) internal view returns (string memory) {
        (, , uint8 decimals) = IAgentRegistry(registry).getPriceConfig(agentId);
        uint256 priceUsd = decimals == 0  ? fetchedPrice
                         : decimals == 2  ? fetchedPrice / 100
                         : fetchedPrice / 1e18;

        uint256 lastFillUsd = exchange.hasTraded() ? exchange.getLastTradePrice() / 1e18 : 0;

        (uint256 bidRaw, bool bidOk) = exchange.getBestBid();
        (uint256 askRaw, bool askOk) = exchange.getBestAsk();
        uint256 bidUsd = bidOk ? bidRaw / 1e18 : 0;
        uint256 askUsd = askOk ? askRaw / 1e18 : 0;

        uint256 streak = winStreak[agentId];
        string memory streakInfo = streak > 0
            ? string(abi.encodePacked(_uint2str(streak), "-win streak. "))
            : "";

        uint256 buyDepth  = exchange.getActiveBuys().length;
        uint256 sellDepth = exchange.getActiveSells().length;

        string memory part1 = string(abi.encodePacked(
            "ETH oracle: $", _uint2str(priceUsd),
            ". sETH last trade: $", _uint2str(lastFillUsd),
            ". Bid: $", bidOk ? _uint2str(bidUsd) : "none",
            ". Ask: $", askOk ? _uint2str(askUsd) : "none",
            ". Book: ", _uint2str(buyDepth), " buys, ", _uint2str(sellDepth), " asks"
        ));
        string memory part2 = string(abi.encodePacked(
            ". Peers: ", _buildPeerSignals(agentId),
            ". ", streakInfo,
            "Decide: BUY, SELL, or HOLD."
        ));
        return string(abi.encodePacked(part1, part2));
    }

    function _toWei(uint256 price, uint8 decimals) internal pure returns (uint256) {
        if (decimals == 0)  return price * 1e18;
        if (decimals == 2)  return price * 1e16;
        if (decimals == 18) return price;
        uint256 factor = 1;
        for (uint8 i = decimals; i < 18; i++) factor *= 10;
        return price * factor;
    }

    function _strEq(string memory a, string memory b) internal pure returns (bool) {
        return keccak256(bytes(a)) == keccak256(bytes(b));
    }

    function _uint2str(uint256 v) internal pure returns (string memory) {
        if (v == 0) return "0";
        uint256 tmp = v;
        uint256 len;
        while (tmp != 0) { len++; tmp /= 10; }
        bytes memory buf = new bytes(len);
        while (v != 0) { buf[--len] = bytes1(uint8(48 + v % 10)); v /= 10; }
        return string(buf);
    }

    function _authorizeUpgrade(address) internal override onlyOwner {}

    function getBalance() external view returns (uint256) {
        return address(this).balance;
    }
}
