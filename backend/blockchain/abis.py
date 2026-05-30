"""
Fallback ABIs used when no deployment JSON is present.
Loaded by blockchain/contracts.py via _load_abis().
"""

_fn = lambda name, inputs, outputs=None, mutability="nonpayable": {
    "type": "function",
    "name": name,
    "inputs": inputs,
    "outputs": outputs or [],
    "stateMutability": mutability,
}
_view = lambda name, inputs, outputs: _fn(name, inputs, outputs, "view")
_payable = lambda name, inputs, outputs=None: _fn(name, inputs, outputs or [], "payable")
_ev = lambda name, inputs: {"type": "event", "name": name, "anonymous": False, "inputs": inputs}
_i = lambda name, t, indexed=False: {"name": name, "type": t, "indexed": indexed}


FALLBACK_ABIS: dict = {
    "Exchange": [
        _fn("placeOrder",
            [_i("isBuy", "bool"), _i("price", "uint256"), _i("amount", "uint256")],
            [_i("orderId", "uint256")]),
        _fn("cancelOrder",   [_i("orderId", "uint256")]),
        _view("getActiveBuys",   [], [_i("", "uint256[]")]),
        _view("getActiveSells",  [], [_i("", "uint256[]")]),
        _view("getBestBid",      [], [_i("price", "uint256"), _i("exists", "bool")]),
        _view("getBestAsk",      [], [_i("price", "uint256"), _i("exists", "bool")]),
        _view("getLastTradePrice", [], [_i("", "uint256")]),
        _view("getOrder", [_i("orderId", "uint256")], [
            {"name": "", "type": "tuple", "components": [
                _i("id", "uint256"), _i("agent", "address"), _i("isBuy", "bool"),
                _i("price", "uint256"), _i("amount", "uint256"), _i("filled", "uint256"),
                _i("timestamp", "uint256"), _i("active", "bool"),
            ]},
        ]),
        _ev("OrderPlaced", [
            _i("orderId", "uint256", True), _i("agent", "address", True),
            _i("isBuy", "bool"), _i("price", "uint256"), _i("amount", "uint256"),
        ]),
        _ev("TradeExecuted", [
            _i("tradeId", "uint256", True),
            _i("buyOrderId", "uint256"), _i("sellOrderId", "uint256"),
            _i("buyer", "address", True), _i("seller", "address", True),
            _i("price", "uint256"), _i("amount", "uint256"),
        ]),
    ],

    "Treasury": [
        _payable("deposit", []),
        _view("getBalance",  [_i("agent", "address")], [_i("", "uint256")]),
        _view("totalLocked", [],                        [_i("", "uint256")]),
    ],

    "AgentRegistry": [
        _fn("registerAgent", [
            _i("agentId", "string"), _i("name", "string"), _i("icon", "string"),
            _i("riskLevel", "uint8"), _i("systemPrompt", "string"),
            _i("priceUrl", "string"), _i("selector", "string"), _i("decimals", "uint8"),
        ]),
        _fn("pauseAgent",  [_i("agentId", "string")]),
        _fn("resumeAgent", [_i("agentId", "string")]),
        _view("isRegistered",    [_i("agentId", "string")],  [_i("", "bool")]),
        _view("getAllAgentIds",   [],                          [_i("", "string[]")]),
        _view("getAgentsByOwner",[_i("_owner", "address")],  [_i("", "string[]")]),
        _view("agents", [_i("", "string")], [
            _i("agentOwner", "address"), _i("name", "string"), _i("icon", "string"),
            _i("riskLevel", "uint8"), _i("createdAt", "uint256"), _i("active", "bool"),
        ]),
        _ev("AgentRegistered", [
            _i("agentId", "string", True), _i("agentOwner", "address", True),
            _i("name", "string"), _i("icon", "string"), _i("riskLevel", "uint8"),
        ]),
        _ev("AgentPaused",  [_i("agentId", "string", True), _i("caller", "address", True)]),
        _ev("AgentResumed", [_i("agentId", "string", True), _i("caller", "address", True)]),
    ],

    "QuoteToken": [
        _fn("mint",         [_i("to", "address"), _i("amount", "uint256")]),
        _fn("transfer",     [_i("to", "address"), _i("amount", "uint256")],    [_i("", "bool")]),
        _fn("approve",      [_i("spender", "address"), _i("amount", "uint256")], [_i("", "bool")]),
        _fn("transferFrom", [_i("from", "address"), _i("to", "address"), _i("amount", "uint256")], [_i("", "bool")]),
        _view("balanceOf",   [_i("", "address")], [_i("", "uint256")]),
        _view("totalSupply", [],                   [_i("", "uint256")]),
        _view("name",   [], [_i("", "string")]),
        _view("symbol", [], [_i("", "string")]),
        _ev("Transfer", [_i("from", "address", True), _i("to", "address", True), _i("value", "uint256")]),
    ],

    "AgentToken": [
        _fn("mint",         [_i("to", "address"), _i("amount", "uint256")]),
        _fn("transfer",     [_i("to", "address"), _i("amount", "uint256")],    [_i("", "bool")]),
        _fn("approve",      [_i("spender", "address"), _i("amount", "uint256")], [_i("", "bool")]),
        _fn("transferFrom", [_i("from", "address"), _i("to", "address"), _i("amount", "uint256")], [_i("", "bool")]),
        _view("balanceOf",   [_i("", "address")], [_i("", "uint256")]),
        _view("totalSupply", [],                   [_i("", "uint256")]),
        _view("name",   [], [_i("", "string")]),
        _view("symbol", [], [_i("", "string")]),
        _ev("Transfer", [_i("from", "address", True), _i("to", "address", True), _i("value", "uint256")]),
    ],

    "AgentCoordinator": [
        _fn("triggerAgentDecision", [_i("agentId", "string")]),
        _fn("triggerWithPrice",     [_i("agentId", "string"), _i("rawPrice", "uint256")]),
        _fn("pauseAgent",           [_i("agentId", "string")]),
        _fn("resumeAgent",          [_i("agentId", "string")]),
        _fn("addAgentToList",       [_i("agentId", "string")]),
        _view("getBalance",  [], [_i("", "uint256")]),
        _view("winStreak",   [_i("", "string")], [_i("", "uint256")]),
        _view("lastDecision",[_i("", "string")], [_i("", "string")]),
        _view("agentPaused", [_i("", "string")], [_i("", "bool")]),
        _ev("DecisionTriggered", [_i("requestId", "uint256", True), _i("agentId", "string")]),
        _ev("LLMRequestFired",   [
            _i("llmRequestId", "uint256", True), _i("agentId", "string"),
            _i("fetchedPrice", "uint256"), _i("context", "string"),
        ]),
        _ev("DecisionExecuted", [
            _i("requestId", "uint256", True), _i("agentId", "string"),
            _i("decision", "string"), _i("price", "uint256"),
            _i("orderId", "uint256"), _i("streak", "uint256"),
        ]),
        _ev("DecisionFailed", [
            _i("requestId", "uint256", True), _i("agentId", "string"), _i("reason", "string"),
        ]),
        _ev("LoopStopped", [
            _i("agentId", "string"), _i("reason", "string"), _i("balance", "uint256"),
        ]),
        _ev("CoalitionFormed", [
            _i("direction", "string"), _i("agentCount", "uint256"),
            _i("price", "uint256"), _i("orderId", "uint256"),
        ]),
        _ev("AgentPaused",  [_i("agentId", "string")]),
        _ev("AgentResumed", [_i("agentId", "string")]),
    ],
}
