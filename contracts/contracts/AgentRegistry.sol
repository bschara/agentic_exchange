// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract AgentRegistry {
    struct AgentInfo {
        address wallet;
        string name;
        string strategy;
        int256 reputation;
        uint256 tradesExecuted;
        uint256 registeredAt;
        bool active;
    }

    address public owner;
    address[] private _agentAddresses;
    mapping(address => AgentInfo) public agents;
    mapping(address => bool) public registered;

    event AgentRegistered(address indexed agent, string name, string strategy);
    event ReputationUpdated(address indexed agent, int256 delta, int256 newReputation);

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    function register(
        address agent,
        string calldata name,
        string calldata strategy
    ) external onlyOwner {
        require(!registered[agent], "Already registered");
        require(agent != address(0), "Zero address");

        agents[agent] = AgentInfo({
            wallet: agent,
            name: name,
            strategy: strategy,
            reputation: 100,
            tradesExecuted: 0,
            registeredAt: block.timestamp,
            active: true
        });
        registered[agent] = true;
        _agentAddresses.push(agent);

        emit AgentRegistered(agent, name, strategy);
    }

    function updateReputation(address agent, int256 delta) external onlyOwner {
        require(registered[agent], "Not registered");
        agents[agent].reputation += delta;
        emit ReputationUpdated(agent, delta, agents[agent].reputation);
    }

    function incrementTrades(address agent) external onlyOwner {
        require(registered[agent], "Not registered");
        agents[agent].tradesExecuted++;
    }

    function getAgent(address agent) external view returns (AgentInfo memory) {
        return agents[agent];
    }

    function getAllAgents() external view returns (address[] memory) {
        return _agentAddresses;
    }

    function isRegistered(address agent) external view returns (bool) {
        return registered[agent];
    }
}
