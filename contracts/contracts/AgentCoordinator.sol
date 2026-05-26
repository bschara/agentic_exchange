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

interface IERC20Approvable {
    function approve(address spender, uint256 amount) external returns (bool);
}

interface IExchange {
    function placeOrder(bool isBuy, uint256 price, uint256 amount) external returns (uint256 orderId);
    function cancelOrder(uint256 orderId) external;
    function getLastTradePrice() external view returns (uint256);
    function hasTraded() external view returns (bool);
    function getBestBid() external view returns (uint256 price, bool exists);
    function getBestAsk() external view returns (uint256 price, bool exists);
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
contract AgentCoordinator {
    // Base order size; scales with win streak via _orderAmount(), capped at 5×
    uint256 public constant ORDER_AMOUNT_BASE = 0.001e18;
    uint256 public constant ORDER_AMOUNT_MAX  = 0.005e18;
    uint256 public constant PRICE_OFFSET_BPS  = 10; // 0.1%

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

    // Last BUY/SELL/HOLD per agent — read by peers in _buildContext next cycle
    mapping(string => string) public lastDecision;

    // Consecutive filled-order streak per agent — drives _orderAmount()
    mapping(string => uint256) public winStreak;

    // Pause flags — owner can halt an agent's self-retriggering loop to save STT
    mapping(string => bool) public agentPaused;

    // Ordered list of configured agent IDs — iterated for peer signals + coalition
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

    string[] private _allowedValues;

    // ── Events ───────────────────────────────────────────────────────────────────

    event AgentPaused(string agentId);
    event AgentResumed(string agentId);
    event DecisionTriggered(uint256 indexed requestId, string agentId);
    event PriceFetchFailed(uint256 indexed requestId, string agentId);

    // context: the full LLM prompt sent to Somnia validators, visible on-chain
    event LLMRequestFired(
        uint256 indexed llmRequestId,
        string agentId,
        uint256 fetchedPrice,
        string context
    );

    // streak: agent's win streak after this decision
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

    // Fired when 3 agents converge on the same direction — coordinated order at 3× base size
    event CoalitionFormed(string direction, uint256 agentCount, uint256 price, uint256 orderId);

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
        if (!_agentIdRegistered(agentId)) _agentIdList.push(agentId);
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

    function pauseAgent(string calldata agentId) external onlyOwner {
        agentPaused[agentId] = true;
        emit AgentPaused(agentId);
    }

    function resumeAgent(string calldata agentId) external onlyOwner {
        agentPaused[agentId] = false;
        emit AgentResumed(agentId);
    }

    function fund() external payable {}

    function approveToken(address _token, address spender, uint256 amount) external onlyOwner {
        IERC20Approvable(_token).approve(spender, amount);
    }

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

    // ── Step 1b (optional): Backend injects price directly, skipping JSON API ────
    function triggerWithPrice(string calldata agentId, uint256 rawPrice) external onlyOwner {
        require(bytes(agentConfigs[agentId].priceUrl).length > 0, "No config for agent");
        uint256 deposit = platform.getRequestDeposit();
        require(address(this).balance >= deposit, "Coordinator underfunded");
        _fireLLMRequest(agentId, rawPrice);
        emit DecisionTriggered(0, agentId);
    }

    // ── Step 2: Callback — Somnia JSON API agent returns the price ───────────────
    //
    // Builds on-chain context (price + peer signals + own streak) and fires LLM.
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
        _fireLLMRequest(req.agentId, fetchedPrice);
    }

    // ── Internal: fire LLM inference request with a known price ─────────────────
    function _fireLLMRequest(string memory agentId, uint256 fetchedPrice) internal {
        string memory context   = _buildContext(fetchedPrice, agentId);
        string memory sysPrompt = _getSystemPrompt(agentId);

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
    //
    // Stores decision for peers, checks coalition, updates streak, places order.
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
            winStreak[req.agentId] = 0;
            emit DecisionFailed(requestId, req.agentId, "No consensus or timeout");
            _retrigger(req.agentId);
            return;
        }

        // Cancel stale order from the previous cycle before placing a new one
        uint256 prev = lastOrderId[req.agentId];
        if (prev > 0) {
            try exchange.cancelOrder(prev) {} catch {}
            lastOrderId[req.agentId] = 0;
        }

        AgentConfig memory cfg = agentConfigs[req.agentId];
        uint256 basePrice = _toWei(req.fetchedPrice, cfg.decimals);

        // Market maker posts both sides simultaneously to actually make markets.
        // Bypasses LLM result — its strategy is fixed dual-sided quoting.
        if (_strEq(req.agentId, "market_maker")) {
            uint256 bidPrice = basePrice * (10000 - PRICE_OFFSET_BPS) / 10000;
            uint256 askPrice = basePrice * (10000 + PRICE_OFFSET_BPS) / 10000;
            try exchange.placeOrder(true,  bidPrice, ORDER_AMOUNT_BASE) returns (uint256 bidId) {
                emit DecisionExecuted(requestId, req.agentId, "BUY",  bidPrice, bidId, 0);
            } catch {}
            try exchange.placeOrder(false, askPrice, ORDER_AMOUNT_BASE) returns (uint256 askId) {
                lastOrderId[req.agentId] = askId;
                emit DecisionExecuted(requestId, req.agentId, "SELL", askPrice, askId, 0);
            } catch {}
            _retrigger(req.agentId);
            return;
        }

        string memory decision = abi.decode(responses[0].result, (string));
        bool isBuy  = _strEq(decision, "BUY");
        bool isSell = _strEq(decision, "SELL");

        // Publish this decision so peers read it in their next LLM context
        lastDecision[req.agentId] = decision;

        // Coalition check: when 3 directional agents converge, fire a coordinated order
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

        // Price relative to live fetched reference to prevent drift
        uint256 orderPrice = isBuy
            ? basePrice * (10000 + PRICE_OFFSET_BPS) / 10000
            : basePrice * (10000 - PRICE_OFFSET_BPS) / 10000;

        try exchange.placeOrder(isBuy, orderPrice, _orderAmount(req.agentId)) returns (uint256 orderId) {
            winStreak[req.agentId]++;
            lastOrderId[req.agentId] = orderId;
            emit DecisionExecuted(requestId, req.agentId, decision, orderPrice, orderId, winStreak[req.agentId]);
        } catch {
            winStreak[req.agentId] = 0;
            emit DecisionFailed(requestId, req.agentId, "placeOrder reverted");
        }

        _retrigger(req.agentId);
    }

    // ── Self-re-trigger — keeps the agent loop running without any off-chain call ─
    function _retrigger(string memory agentId) internal {
        if (agentPaused[agentId]) {
            emit LoopStopped(agentId, "paused", address(this).balance);
            return;
        }

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

    function _agentIdRegistered(string memory id) internal view returns (bool) {
        for (uint256 i = 0; i < _agentIdList.length; i++) {
            if (_strEq(_agentIdList[i], id)) return true;
        }
        return false;
    }

    // Returns "agentId=DECISION,..." for all peers with a recorded decision, excluding self.
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

    // Order amount scales +1× per 5 consecutive wins, capped at ORDER_AMOUNT_MAX.
    function _orderAmount(string memory agentId) internal view returns (uint256) {
        uint256 streak = winStreak[agentId];
        uint256 multiplier = 1 + streak / 5;
        uint256 amt = ORDER_AMOUNT_BASE * multiplier;
        return amt > ORDER_AMOUNT_MAX ? ORDER_AMOUNT_MAX : amt;
    }

    // Count how many agents in _agentIdList have lastDecision == direction.
    function _coalitionCount(string memory direction) internal view returns (uint256 count) {
        for (uint256 i = 0; i < _agentIdList.length; i++) {
            if (_strEq(lastDecision[_agentIdList[i]], direction)) count++;
        }
    }

    // Fire a 3× coordinated order when agents reach consensus.
    function _fireCoalitionOrder(bool isBuy, uint256 basePrice) internal {
        uint256 coalitionAmt = ORDER_AMOUNT_BASE * 3;
        uint256 price = isBuy
            ? basePrice * (10000 + PRICE_OFFSET_BPS) / 10000
            : basePrice * (10000 - PRICE_OFFSET_BPS) / 10000;
        try exchange.placeOrder(isBuy, price, coalitionAmt) returns (uint256 orderId) {
            emit CoalitionFormed(isBuy ? "BUY" : "SELL", 3, price, orderId);
        } catch {}
    }

    // Build a market context string entirely from on-chain data, including peer signals
    // and own win streak. fetchedPrice is in AgentConfig.decimals scale.
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

        uint256 streak = winStreak[agentId];
        string memory streakInfo = streak > 0
            ? string(abi.encodePacked(_uint2str(streak), "-win streak. "))
            : "";

        string memory part1 = string(abi.encodePacked(
            "ETH/USD: $", _uint2str(priceUsd),
            ". Last trade: $", _uint2str(lastFillUsd),
            ". Bid: $", bidOk ? _uint2str(bidUsd) : "none",
            ". Ask: $", askOk ? _uint2str(askUsd) : "none"
        ));
        string memory part2 = string(abi.encodePacked(
            ". Peers: ", _buildPeerSignals(agentId),
            ". ", streakInfo,
            "Decide: BUY, SELL, or HOLD."
        ));
        return string(abi.encodePacked(part1, part2));
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
