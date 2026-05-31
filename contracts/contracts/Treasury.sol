// SPDX-License-Identifier: MIT
pragma solidity ^0.8.22;

import "@openzeppelin/contracts/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts/proxy/utils/UUPSUpgradeable.sol";

contract Treasury is Initializable, UUPSUpgradeable {
    address public owner;
    mapping(address => uint256) public balances;

    event Deposited(address indexed agent, uint256 amount);
    event Withdrawn(address indexed agent, uint256 amount);
    event Allocated(address indexed from, address indexed to, uint256 amount);

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    function initialize() external initializer {
        owner = msg.sender;
    }

    function deposit() external payable {
        require(msg.value > 0, "Must send ETH");
        balances[msg.sender] += msg.value;
        emit Deposited(msg.sender, msg.value);
    }

    function depositFor(address agent) external payable {
        require(msg.value > 0, "Must send ETH");
        balances[agent] += msg.value;
        emit Deposited(agent, msg.value);
    }

    function withdraw(uint256 amount) external {
        require(balances[msg.sender] >= amount, "Insufficient balance");
        balances[msg.sender] -= amount;
        (bool success, ) = payable(msg.sender).call{value: amount}("");
        require(success, "Transfer failed");
        emit Withdrawn(msg.sender, amount);
    }

    function allocate(
        address from,
        address to,
        uint256 amount
    ) external onlyOwner {
        require(balances[from] >= amount, "Insufficient balance");
        balances[from] -= amount;
        balances[to] += amount;
        emit Allocated(from, to, amount);
    }

    function _authorizeUpgrade(address) internal override onlyOwner {}

    function getBalance(address agent) external view returns (uint256) {
        return balances[agent];
    }

    function totalLocked() external view returns (uint256) {
        return address(this).balance;
    }
}
