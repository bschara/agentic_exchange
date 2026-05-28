// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IAgentCoordinator {
    function addAgentToList(string calldata agentId) external;
    function pauseAgent(string calldata agentId) external;
    function resumeAgent(string calldata agentId) external;
}

// ── AgentRegistry ────────────────────────────────────────────────────────────
//
// Unified registry and source of truth for ALL agent data — system agents
// registered by the deployer, user-defined agents registered by anyone.
// msg.sender becomes agentOwner.
//
// Stores: ownership, display metadata, AND agent config (systemPrompt,
// priceUrl, selector, decimals). AgentCoordinator reads config via view
// getters on each decision cycle — it owns only runtime state.
//
contract AgentRegistry {
    struct AgentInfo {
        // ── Ownership & display ────────────────────────────────────────────
        address agentOwner;   // deployer for system agents; user wallet for custom agents
        string  name;
        string  icon;         // display emoji e.g. "⚖️"
        uint8   riskLevel;    // 1-5: scales order size in coordinator _orderAmount()
        uint256 createdAt;
        bool    active;
        // ── Agent config (read by coordinator on each decision cycle) ──────
        string  systemPrompt; // LLM strategy prompt — passed to Somnia inferString()
        string  priceUrl;     // CoinGecko or other JSON API endpoint
        string  selector;     // JSON path selector e.g. "ethereum.usd"
        uint8   decimals;     // price decimal places (0 = whole dollars)
    }

    address public owner;
    address public coordinator;
    string[] private _allAgentIds;

    mapping(string  => AgentInfo) public agents;
    mapping(address => string[])  public ownerAgents;

    // ── Events ────────────────────────────────────────────────────────────────

    event AgentRegistered(
        string  indexed agentId,
        address indexed agentOwner,
        string  name,
        string  icon,
        uint8   riskLevel
    );
    event AgentPaused(string indexed agentId, address indexed caller);
    event AgentResumed(string indexed agentId, address indexed caller);

    // ── Modifiers ─────────────────────────────────────────────────────────────

    modifier onlyContractOwner() {
        require(msg.sender == owner, "Not registry owner");
        _;
    }

    modifier onlyOwnerOrAgentOwner(string calldata agentId) {
        require(
            msg.sender == owner || msg.sender == agents[agentId].agentOwner,
            "Not authorized: must be contract owner or agent owner"
        );
        _;
    }

    // ── Constructor ───────────────────────────────────────────────────────────

    constructor(address _coordinator) {
        owner = msg.sender;
        coordinator = _coordinator;
    }

    // ── Registration ──────────────────────────────────────────────────────────

    // One registration function for ALL agents.
    // Deployer calls for system agents; users call for their own.
    // Stores ALL config here — coordinator reads it back via getters.
    function registerAgent(
        string calldata agentId,
        string calldata name,
        string calldata icon,
        uint8  riskLevel,
        string calldata systemPrompt,
        string calldata priceUrl,
        string calldata selector,
        uint8  decimals
    ) external {
        require(agents[agentId].agentOwner == address(0), "Agent ID already taken");
        require(riskLevel >= 1 && riskLevel <= 5, "riskLevel must be 1-5");
        require(bytes(priceUrl).length > 0, "priceUrl required");

        agents[agentId] = AgentInfo({
            agentOwner:   msg.sender,
            name:         name,
            icon:         icon,
            riskLevel:    riskLevel,
            createdAt:    block.timestamp,
            active:       true,
            systemPrompt: systemPrompt,
            priceUrl:     priceUrl,
            selector:     selector,
            decimals:     decimals
        });
        ownerAgents[msg.sender].push(agentId);
        _allAgentIds.push(agentId);

        // Tell coordinator to add this agentId to its peer-signal iteration list
        IAgentCoordinator(coordinator).addAgentToList(agentId);

        emit AgentRegistered(agentId, msg.sender, name, icon, riskLevel);
    }

    // ── Pause / Resume ────────────────────────────────────────────────────────

    function pauseAgent(string calldata agentId) external onlyOwnerOrAgentOwner(agentId) {
        require(agents[agentId].agentOwner != address(0), "Agent not registered");
        IAgentCoordinator(coordinator).pauseAgent(agentId);
        emit AgentPaused(agentId, msg.sender);
    }

    function resumeAgent(string calldata agentId) external onlyOwnerOrAgentOwner(agentId) {
        require(agents[agentId].agentOwner != address(0), "Agent not registered");
        IAgentCoordinator(coordinator).resumeAgent(agentId);
        emit AgentResumed(agentId, msg.sender);
    }

    // ── Admin ─────────────────────────────────────────────────────────────────

    function setActive(string calldata agentId, bool active) external onlyContractOwner {
        agents[agentId].active = active;
    }

    // ── Config getters (read by AgentCoordinator on each decision cycle) ──────

    function getSystemPrompt(string calldata agentId) external view returns (string memory) {
        return agents[agentId].systemPrompt;
    }

    function getPriceConfig(string calldata agentId) external view
        returns (string memory priceUrl, string memory selector, uint8 decimals)
    {
        AgentInfo storage a = agents[agentId];
        return (a.priceUrl, a.selector, a.decimals);
    }

    function getRiskLevel(string calldata agentId) external view returns (uint8) {
        return agents[agentId].riskLevel;
    }

    // ── Discovery ─────────────────────────────────────────────────────────────

    function getAllAgentIds() external view returns (string[] memory) {
        return _allAgentIds;
    }

    function getAgentsByOwner(address _owner) external view returns (string[] memory) {
        return ownerAgents[_owner];
    }

    function isRegistered(string calldata agentId) external view returns (bool) {
        return agents[agentId].agentOwner != address(0);
    }
}
