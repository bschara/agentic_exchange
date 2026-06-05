// SPDX-License-Identifier: MIT
pragma solidity ^0.8.22;

import "@openzeppelin/contracts/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts/proxy/utils/UUPSUpgradeable.sol";

interface IERC20 {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function transfer(address to, uint256 amount) external returns (bool);
}

// Implemented by AgentCoordinator to receive per-agent fill/cancel accounting updates.
// tokenFill = sETH quantity actually exchanged; quoteFill = USDC quantity actually exchanged.
interface IAgentFillCallback {
    function onAgentFill(string calldata agentId, bool isBuy, uint256 tokenFill, uint256 quoteFill) external;
    function onAgentCancel(string calldata agentId, bool isBuy, uint256 unfilledTokens, uint256 remainingQuote) external;
}

contract Exchange is Initializable, UUPSUpgradeable {
    struct Order {
        uint256 id;
        address agent;
        bool isBuy;
        uint256 price;   // scaled by 1e18
        uint256 amount;  // original amount, scaled by 1e18
        uint256 filled;  // amount matched so far, scaled by 1e18
        uint256 timestamp;
        bool active;
    }

    struct Trade {
        uint256 id;
        uint256 buyOrderId;
        uint256 sellOrderId;
        address buyer;
        address seller;
        uint256 price;
        uint256 amount;
        uint256 timestamp;
    }

    IERC20 public token;
    IERC20 public quoteToken;
    address public exchangeOwner;

    uint256 private _nextOrderId;
    uint256 private _nextTradeId;

    // QUOTE locked per BUY order — released to seller on fill, refunded on cancel
    mapping(uint256 => uint256) private _lockedQuote;

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    function initialize(address _token, address _quoteToken) external initializer {
        token         = IERC20(_token);
        quoteToken    = IERC20(_quoteToken);
        exchangeOwner = msg.sender;
        _nextOrderId  = 1;
        _nextTradeId  = 1;
    }

    // Last matched trade price — read by Python backend for real price discovery
    uint256 public lastTradePrice;
    bool public hasTraded;

    mapping(uint256 => Order) public orders;
    mapping(uint256 => Trade) public trades;

    uint256[] private _activeBuyIds;
    uint256[] private _activeSellIds;

    // Per-agent order history — used to enumerate active orders by agent address
    mapping(address => uint256[]) private _agentOrderIds;

    // agentId string per order — non-empty only for orders placed via placeOrderForAgent.
    // Triggers fill/cancel callbacks back to the placing address (coordinator).
    mapping(uint256 => string) private _orderAgentId;

    event OrderPlaced(uint256 indexed orderId, address indexed agent, bool isBuy, uint256 price, uint256 amount);
    event OrderCancelled(uint256 indexed orderId, address indexed agent);
    event OrderFilled(uint256 indexed orderId, uint256 filledAmount, bool fullFill);
    event TradeExecuted(
        uint256 indexed tradeId,
        uint256 buyOrderId,
        uint256 sellOrderId,
        address indexed buyer,
        address indexed seller,
        uint256 price,
        uint256 amount
    );

    // ── Placing orders ──────────────────────────────────────────────────────────

    function placeOrder(bool isBuy, uint256 price, uint256 amount) external returns (uint256 orderId) {
        orderId = _placeOrder(isBuy, price, amount, "");
    }

    // Like placeOrder but records agentId so fill/cancel events are fed back to the
    // coordinator's onAgentFill / onAgentCancel for per-agent balance accounting.
    function placeOrderForAgent(
        bool isBuy,
        uint256 price,
        uint256 amount,
        string calldata agentId
    ) external returns (uint256 orderId) {
        orderId = _placeOrder(isBuy, price, amount, agentId);
    }

    function _placeOrder(
        bool isBuy,
        uint256 price,
        uint256 amount,
        string memory agentId
    ) internal returns (uint256 orderId) {
        require(price > 0, "Price must be > 0");
        require(amount > 0, "Amount must be > 0");

        orderId = _nextOrderId++;
        orders[orderId] = Order({
            id: orderId,
            agent: msg.sender,
            isBuy: isBuy,
            price: price,
            amount: amount,
            filled: 0,
            timestamp: block.timestamp,
            active: true
        });
        _agentOrderIds[msg.sender].push(orderId);

        if (bytes(agentId).length > 0) {
            _orderAgentId[orderId] = agentId;
        }

        if (isBuy) {
            uint256 quoteAmount = price * amount / 1e18;
            require(quoteAmount > 0, "Quote amount too small");
            require(quoteToken.transferFrom(msg.sender, address(this), quoteAmount), "QUOTE transfer failed");
            _lockedQuote[orderId] = quoteAmount;
        } else {
            require(token.transferFrom(msg.sender, address(this), amount), "Token transfer failed");
        }

        emit OrderPlaced(orderId, msg.sender, isBuy, price, amount);

        uint256 remaining = _matchOrder(orderId, isBuy, price, amount);

        if (remaining == 0) {
            orders[orderId].active = false;
        } else {
            if (isBuy) {
                _activeBuyIds.push(orderId);
            } else {
                _activeSellIds.push(orderId);
            }
        }
    }

    // ── Matching engine ─────────────────────────────────────────────────────────

    function _matchOrder(
        uint256 newId,
        bool isBuy,
        uint256 price,
        uint256 originalAmount
    ) internal returns (uint256 remaining) {
        remaining = originalAmount;

        uint256[] storage book = isBuy ? _activeSellIds : _activeBuyIds;
        uint256 i = 0;

        while (i < book.length && remaining > 0) {
            uint256 oppositeId = book[i];
            Order storage opp = orders[oppositeId];

            if (!opp.active) {
                _removeAt(book, i);
                continue;
            }

            // Buy: match sells where sell.price <= buy.price
            // Sell: match buys where buy.price >= sell.price
            bool priceMatch = isBuy ? (price >= opp.price) : (opp.price >= price);

            if (priceMatch) {
                uint256 oppRemaining = opp.amount - opp.filled;
                uint256 fill = remaining < oppRemaining ? remaining : oppRemaining;
                uint256 fillPrice = opp.price; // maker's price

                orders[newId].filled += fill;
                opp.filled += fill;
                remaining -= fill;

                // Record trade — delegated to helper to avoid stack-too-deep
                _recordTrade(isBuy, newId, oppositeId, fillPrice, fill);

                if (opp.filled >= opp.amount) {
                    opp.active = false;
                    emit OrderFilled(oppositeId, opp.filled, true);
                    _removeAt(book, i);
                    // don't increment i — slot now holds the swapped element
                } else {
                    i++;
                }
            } else {
                i++;
            }
        }

        if (orders[newId].filled > 0 && orders[newId].filled < originalAmount) {
            emit OrderFilled(newId, orders[newId].filled, false);
        } else if (orders[newId].filled >= originalAmount) {
            emit OrderFilled(newId, orders[newId].filled, true);
        }
    }

    // ── Cancellation ────────────────────────────────────────────────────────────

    function cancelOrder(uint256 orderId) external {
        Order storage order = orders[orderId];
        require(order.active, "Order not active");
        require(order.agent == msg.sender, "Not your order");

        // CEI: deactivate before any external calls
        order.active = false;
        if (order.isBuy) {
            _removeFromBook(_activeBuyIds, orderId);
        } else {
            _removeFromBook(_activeSellIds, orderId);
        }

        uint256 unfilledTokens = 0;
        uint256 remainingQuote = 0;

        if (order.isBuy) {
            remainingQuote = _lockedQuote[orderId];
            if (remainingQuote > 0) {
                _lockedQuote[orderId] = 0;
                require(quoteToken.transfer(order.agent, remainingQuote), "QUOTE refund failed");
            }
        } else {
            unfilledTokens = order.amount - order.filled;
            if (unfilledTokens > 0) require(token.transfer(order.agent, unfilledTokens), "sETH refund failed");
        }

        // Notify coordinator so it can restore the agent's virtual balance.
        string memory agentId = _orderAgentId[orderId];
        if (bytes(agentId).length > 0) {
            try IAgentFillCallback(order.agent).onAgentCancel(agentId, order.isBuy, unfilledTokens, remainingQuote) {} catch {}
        }

        emit OrderCancelled(orderId, msg.sender);
    }

    // ── Views ────────────────────────────────────────────────────────────────────

    function getBestBid() external view returns (uint256 price, bool exists) {
        for (uint256 i = 0; i < _activeBuyIds.length; i++) {
            Order storage o = orders[_activeBuyIds[i]];
            if (o.active && (!exists || o.price > price)) {
                price = o.price;
                exists = true;
            }
        }
    }

    function getBestAsk() external view returns (uint256 price, bool exists) {
        for (uint256 i = 0; i < _activeSellIds.length; i++) {
            Order storage o = orders[_activeSellIds[i]];
            if (o.active && (!exists || o.price < price)) {
                price = o.price;
                exists = true;
            }
        }
    }

    function getLastTradePrice() external view returns (uint256) {
        return lastTradePrice;
    }

    function getOrder(uint256 orderId) external view returns (Order memory) {
        return orders[orderId];
    }

    function getTrade(uint256 tradeId) external view returns (Trade memory) {
        return trades[tradeId];
    }

    function getActiveOrders() external view returns (uint256[] memory) {
        uint256 totalLen = _activeBuyIds.length + _activeSellIds.length;
        uint256[] memory result = new uint256[](totalLen);
        for (uint256 i = 0; i < _activeBuyIds.length; i++) result[i] = _activeBuyIds[i];
        for (uint256 i = 0; i < _activeSellIds.length; i++) result[_activeBuyIds.length + i] = _activeSellIds[i];
        return result;
    }

    function getActiveBuys() external view returns (uint256[] memory) {
        return _activeBuyIds;
    }

    function getActiveSells() external view returns (uint256[] memory) {
        return _activeSellIds;
    }

    function getOrdersByAgent(address agent) external view returns (uint256[] memory activeIds) {
        uint256[] storage all = _agentOrderIds[agent];
        uint256 count = 0;
        for (uint256 i = 0; i < all.length; i++) {
            if (orders[all[i]].active) count++;
        }
        activeIds = new uint256[](count);
        uint256 j = 0;
        for (uint256 i = 0; i < all.length; i++) {
            if (orders[all[i]].active) activeIds[j++] = all[i];
        }
    }

    // ── Helpers ──────────────────────────────────────────────────────────────────

    function _recordTrade(
        bool isBuy,
        uint256 newId,
        uint256 oppositeId,
        uint256 fillPrice,
        uint256 fill
    ) internal {
        uint256 tradeId = _nextTradeId++;
        uint256 buyId = isBuy ? newId : oppositeId;
        uint256 sellId = isBuy ? oppositeId : newId;
        address buyer = orders[buyId].agent;
        address seller = orders[sellId].agent;

        trades[tradeId] = Trade({
            id: tradeId,
            buyOrderId: buyId,
            sellOrderId: sellId,
            buyer: buyer,
            seller: seller,
            price: fillPrice,
            amount: fill,
            timestamp: block.timestamp
        });
        lastTradePrice = fillPrice;
        hasTraded = true;

        emit TradeExecuted(tradeId, buyId, sellId, buyer, seller, fillPrice, fill);

        // Compute exact USDC amount before any transfers so callbacks receive accurate figures.
        // Proportional drain; last fill takes all remaining locked to eliminate dust.
        uint256 totalLocked = _lockedQuote[buyId];
        uint256 quoteForFill = 0;
        if (totalLocked > 0) {
            quoteForFill = (orders[buyId].filled >= orders[buyId].amount)
                ? totalLocked
                : totalLocked * fill / orders[buyId].amount;
        }

        // Notify coordinator with exact tokenFill + quoteFill so virtual balances stay accurate.
        // try/catch ensures a failing callback never reverts the trade.
        string memory buyAgentId = _orderAgentId[buyId];
        if (bytes(buyAgentId).length > 0) {
            try IAgentFillCallback(buyer).onAgentFill(buyAgentId, true, fill, quoteForFill) {} catch {}
        }
        string memory sellAgentId = _orderAgentId[sellId];
        if (bytes(sellAgentId).length > 0) {
            try IAgentFillCallback(seller).onAgentFill(sellAgentId, false, fill, quoteForFill) {} catch {}
        }

        // sETH to buyer (from seller's escrow)
        require(token.transfer(buyer, fill), "sETH transfer failed");

        // QUOTE to seller
        if (quoteForFill > 0) {
            _lockedQuote[buyId] -= quoteForFill;
            require(quoteToken.transfer(seller, quoteForFill), "QUOTE transfer failed");
        }
    }

    // ── Emergency recovery (owner-only) ─────────────────────────────────────────

    function _authorizeUpgrade(address) internal view override {
        require(msg.sender == exchangeOwner, "Not owner");
    }

    function emergencyWithdrawToken(address tokenAddr, uint256 amount) external {
        require(msg.sender == exchangeOwner, "Not owner");
        require(IERC20(tokenAddr).transfer(exchangeOwner, amount), "Transfer failed");
    }

    function _removeAt(uint256[] storage arr, uint256 index) internal {
        arr[index] = arr[arr.length - 1];
        arr.pop();
    }

    function _removeFromBook(uint256[] storage arr, uint256 orderId) internal {
        for (uint256 i = 0; i < arr.length; i++) {
            if (arr[i] == orderId) {
                _removeAt(arr, i);
                break;
            }
        }
    }
}
