// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// Local stand-in for the Somnia IAgentRequester platform.
// Replaces the live platform at 0x037B... so contracts can be tested on a local Hardhat node.
//
// Usage:
//   1. Deploy this contract first; pass its address to AgentCoordinator constructor.
//   2. Start platform-daemon.js — it watches RequestCreated events and auto-fires callbacks.
//      OR call simulatePriceCallback / simulateLLMCallback manually in test scripts.
//
// getRequestDeposit() returns 0 — all balance guards in AgentCoordinator pass immediately.

contract MockPlatform {
    // Mirror IAgentRequester types exactly — ABI encoding must match coordinator expectations.
    enum ResponseStatus { None, Pending, Success, Failed, TimedOut }

    struct Response {
        ResponseStatus status;
        bytes result;
        uint256 executionCost;
    }

    struct Request {
        uint256 agentId;
        address callbackAddress;
        bytes4  callbackSelector;
        bytes   payload;
    }

    struct StoredRequest {
        address callbackAddress;
        bytes4  callbackSelector;
    }

    uint256 private _nextId = 1;

    mapping(uint256 => StoredRequest) public requests;

    // callbackSelector included so platform-daemon.js can route price vs LLM requests
    event RequestCreated(
        uint256 indexed requestId,
        uint256         agentId,
        address indexed callbackAddress,
        bytes4          callbackSelector
    );

    function getRequestDeposit() external pure returns (uint256) {
        return 0;
    }

    function createRequest(
        uint256  agentId,
        address  callbackAddress,
        bytes4   callbackSelector,
        bytes calldata /* payload */
    ) external payable returns (uint256 requestId) {
        requestId = _nextId++;
        requests[requestId] = StoredRequest(callbackAddress, callbackSelector);
        emit RequestCreated(requestId, agentId, callbackAddress, callbackSelector);
    }

    // Called by platform-daemon.js (or test scripts) to simulate a JSON API price fetch response.
    // fetchedPrice is the raw USD value (decimals=0 → whole dollars, e.g. 3245 for $3245).
    function simulatePriceCallback(uint256 requestId, uint256 fetchedPrice) external {
        StoredRequest memory req = requests[requestId];
        require(req.callbackAddress != address(0), "Unknown request");

        Response[] memory responses = new Response[](1);
        responses[0] = Response({
            status:        ResponseStatus.Success,
            result:        abi.encode(fetchedPrice),
            executionCost: 0
        });

        Request memory emptyDetails;

        (bool ok, bytes memory err) = req.callbackAddress.call(
            abi.encodeWithSelector(
                req.callbackSelector,
                requestId,
                responses,
                ResponseStatus.Success,
                emptyDetails
            )
        );
        require(ok, _revertMsg(err));
    }

    // Called by platform-daemon.js to simulate LLM validator consensus.
    // decision must be "BUY", "SELL", or anything else (treated as HOLD by coordinator).
    function simulateLLMCallback(uint256 requestId, string calldata decision) external {
        StoredRequest memory req = requests[requestId];
        require(req.callbackAddress != address(0), "Unknown request");

        Response[] memory responses = new Response[](1);
        responses[0] = Response({
            status:        ResponseStatus.Success,
            result:        abi.encode(decision),
            executionCost: 0
        });

        Request memory emptyDetails;

        (bool ok, bytes memory err) = req.callbackAddress.call(
            abi.encodeWithSelector(
                req.callbackSelector,
                requestId,
                responses,
                ResponseStatus.Success,
                emptyDetails
            )
        );
        require(ok, _revertMsg(err));
    }

    function _revertMsg(bytes memory err) internal pure returns (string memory) {
        if (err.length < 68) return "Callback reverted (no message)";
        assembly { err := add(err, 0x04) }
        return abi.decode(err, (string));
    }
}
