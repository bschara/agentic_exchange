// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

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

interface IExchange {
    function placeOrder(bool isBuy, uint256 price, uint256 amount) external returns (uint256 orderId);
    function getLastTradePrice() external view returns (uint256);
    function hasTraded() external view returns (bool);
    function getBestBid() external view returns (uint256 price, bool exists);
    function getBestAsk() external view returns (uint256 price, bool exists);
}

// ── AgentCoordinator ────────────────────────────────────────────────────────────
//
// Two-step autonomous agent pipeline:
//   1. triggerAgentDecision() → Somnia JSON API agent fetches real ETH price
//   2. handlePriceData() callback → builds on-chain context → fires LLM Inference
//   3. handleDecision() callback → validator consensus → Exchange.placeOrder()
//
// Python is only the trigger. All data sourcing and decision-making is on-chain.
//
contract AgentCoordinator {
    uint256 public constant ORDER_AMOUNT = 0.1e18;
    uint256 public constant PRICE_OFFSET_BPS = 10; // 0.1%

    IAgentRequester public immutable platform;
    IExchange       public immutable exchange;
    address         public owner;

    uint256 public llmAgentId;
    uint256 public jsonApiAgentId;

    // Per-agent API config (URL, JSON selector, decimal places)
    struct AgentConfig {
        string priceUrl;
        string selector;
        uint8  decimals;
    }
    mapping(string => AgentConfig) public agentConfigs;

    // Per-agent strategy system prompts stored on-chain
    mapping(string => string) public systemPrompts;

    // Stage-1 pending: JSON API fetch in flight
    struct PriceRequest {
        string agentId;
        bool   exists;
    }
    mapping(uint256 => PriceRequest) public pendingPriceRequests;

    // Stage-2 pending: LLM inference in flight
    struct LLMRequest {
        string  agentId;
        uint256 fetchedPrice; // raw value from JSON API (in AgentConfig.decimals scale)
        bool    exists;
    }
    mapping(uint256 => LLMRequest) public pendingLLMRequests;

    string[] private _allowedValues;

    // ── Events ───────────────────────────────────────────────────────────────────

    event DecisionTriggered(uint256 indexed requestId, string agentId);
    event PriceFetchFailed(uint256 indexed requestId, string agentId);
    event LLMRequestFired(uint256 indexed llmRequestId, string agentId, uint256 fetchedPrice);
    event DecisionExecuted(
        uint256 indexed requestId,
        string agentId,
        string decision,
        uint256 price,
        uint256 orderId
    );
    event DecisionFailed(uint256 indexed requestId, string agentId, string reason);
    event LoopStopped(string agentId, string reason, uint256 balance);

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    constructor(
        address _platform,
        address _exchange,
        uint256 _llmAgentId,
        uint256 _jsonApiAgentId
    ) {
        platform       = IAgentRequester(_platform);
        exchange       = IExchange(_exchange);
        owner          = msg.sender;
        llmAgentId     = _llmAgentId;
        jsonApiAgentId = _jsonApiAgentId;

        _allowedValues.push("BUY");
        _allowedValues.push("SELL");
        _allowedValues.push("HOLD");
    }

    receive() external payable {}

    // ── Configuration ─────────────────────────────────────────────────────────────

    function setAgentConfig(
        string calldata agentId,
        string calldata url,
        string calldata selector,
        uint8 decimals
    ) external onlyOwner {
        agentConfigs[agentId] = AgentConfig(url, selector, decimals);
    }

    function setSystemPrompt(string calldata agentId, string calldata prompt) external onlyOwner {
        systemPrompts[agentId] = prompt;
    }

    function setLlmAgentId(uint256 agentId) external onlyOwner {
        llmAgentId = agentId;
    }

    function setJsonApiAgentId(uint256 agentId) external onlyOwner {
        jsonApiAgentId = agentId;
    }

    function fund() external payable {}

    function withdraw() external onlyOwner {
        (bool ok, ) = payable(owner).call{value: address(this).balance}("");
        require(ok, "Withdraw failed");
    }

    // ── Step 1: Trigger — Python calls this once per agent loop ──────────────────
    //
    // Fires a Somnia JSON API request to fetch the current ETH/USD price.
    // No market data is passed from Python — the agent self-sources its own data.
    //
    function triggerAgentDecision(string calldata agentId) external {
        AgentConfig memory cfg = agentConfigs[agentId];
        require(bytes(cfg.priceUrl).length > 0, "No config for agent");

        uint256 deposit = platform.getRequestDeposit();
        require(address(this).balance >= deposit * 2, "Coordinator underfunded: need 2 deposits");

        bytes memory payload = abi.encodeWithSelector(
            IJSONAPIAgent.fetchUint.selector,
            cfg.priceUrl,
            cfg.selector,
            cfg.decimals
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

    // ── Step 2: Callback — Somnia JSON API agent returns the price ───────────────
    //
    // Reads Exchange.sol on-chain state to enrich the context, then fires the
    // Somnia LLM Inference agent. All data is sourced on-chain at this point.
    //
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

        string memory context  = _buildContext(fetchedPrice, req.agentId);
        string memory sysPrompt = _getSystemPrompt(req.agentId);

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

        pendingLLMRequests[llmReqId] = LLMRequest(req.agentId, fetchedPrice, true);
        emit LLMRequestFired(llmReqId, req.agentId, fetchedPrice);
    }

    // ── Step 3: Callback — Somnia LLM validators reach consensus ─────────────────
    //
    // Receives BUY / SELL / HOLD from the validator network and executes the order
    // directly on Exchange.sol. No Python involved in this step.
    //
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
            emit DecisionFailed(requestId, req.agentId, "No consensus or timeout");
            return;
        }

        string memory decision = abi.decode(responses[0].result, (string));

        bool isBuy  = _strEq(decision, "BUY");
        bool isSell = _strEq(decision, "SELL");

        if (!isBuy && !isSell) {
            emit DecisionExecuted(requestId, req.agentId, "HOLD", 0, 0);
            _retrigger(req.agentId);
            return;
        }

        // Use last on-chain fill price as base; fall back to fetched price scaled to 1e18
        AgentConfig memory cfg = agentConfigs[req.agentId];
        uint256 basePrice = exchange.hasTraded()
            ? exchange.getLastTradePrice()
            : _toWei(req.fetchedPrice, cfg.decimals);

        uint256 orderPrice = isBuy
            ? basePrice * (10000 + PRICE_OFFSET_BPS) / 10000
            : basePrice * (10000 - PRICE_OFFSET_BPS) / 10000;

        try exchange.placeOrder(isBuy, orderPrice, ORDER_AMOUNT) returns (uint256 orderId) {
            emit DecisionExecuted(requestId, req.agentId, decision, orderPrice, orderId);
        } catch {
            emit DecisionFailed(requestId, req.agentId, "placeOrder reverted");
        }

        _retrigger(req.agentId);
    }

    // ── Self-re-trigger — keeps the agent loop running without any off-chain call ─
    function _retrigger(string memory agentId) internal {
        AgentConfig memory cfg = agentConfigs[agentId];
        uint256 needed = platform.getRequestDeposit() * 2;

        if (bytes(cfg.priceUrl).length == 0) {
            emit LoopStopped(agentId, "No agent config", address(this).balance);
            return;
        }
        if (address(this).balance < needed) {
            emit LoopStopped(agentId, "Insufficient balance", address(this).balance);
            return;
        }

        bytes memory payload = abi.encodeWithSelector(
            IJSONAPIAgent.fetchUint.selector,
            cfg.priceUrl,
            cfg.selector,
            cfg.decimals
        );
        uint256 newReqId = platform.createRequest{value: platform.getRequestDeposit()}(
            jsonApiAgentId,
            address(this),
            this.handlePriceData.selector,
            payload
        );
        pendingPriceRequests[newReqId] = PriceRequest(agentId, true);
        emit DecisionTriggered(newReqId, agentId);
    }

    // ── Helpers ──────────────────────────────────────────────────────────────────

    // Build a market context string entirely from on-chain data.
    // fetchedPrice is in AgentConfig.decimals scale (0 = whole USD, 2 = cents, 18 = wei).
    function _buildContext(uint256 fetchedPrice, string memory agentId) internal view returns (string memory) {
        AgentConfig memory cfg = agentConfigs[agentId];
        uint256 priceUsd = cfg.decimals == 0  ? fetchedPrice
                         : cfg.decimals == 2  ? fetchedPrice / 100
                         : fetchedPrice / 1e18;

        uint256 lastFillUsd = exchange.hasTraded() ? exchange.getLastTradePrice() / 1e18 : 0;

        (uint256 bidRaw, bool bidOk) = exchange.getBestBid();
        (uint256 askRaw, bool askOk) = exchange.getBestAsk();
        uint256 bidUsd = bidOk ? bidRaw / 1e18 : 0;
        uint256 askUsd = askOk ? askRaw / 1e18 : 0;

        return string(abi.encodePacked(
            "ETH/USD: $", _uint2str(priceUsd),
            ". On-chain last trade: $", _uint2str(lastFillUsd),
            ". Best bid: $", bidOk ? _uint2str(bidUsd) : "none",
            ". Best ask: $", askOk ? _uint2str(askUsd) : "none",
            ". Decide: BUY, SELL, or HOLD."
        ));
    }

    function _getSystemPrompt(string memory agentId) internal view returns (string memory) {
        string memory p = systemPrompts[agentId];
        if (bytes(p).length > 0) return p;
        return "You are an autonomous trading agent. Respond with exactly one word: BUY, SELL, or HOLD.";
    }

    // Scale a fetched price (in AgentConfig.decimals) to 1e18 for Exchange.sol
    function _toWei(uint256 price, uint8 decimals) internal pure returns (uint256) {
        if (decimals == 0)  return price * 1e18;
        if (decimals == 2)  return price * 1e16;
        if (decimals == 18) return price;
        // generic: multiply by 10^(18-decimals)
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

    function getBalance() external view returns (uint256) {
        return address(this).balance;
    }
}
