// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract Exchange {
    struct Order {
        uint256 id;
        address agent;
        bool isBuy;
        uint256 price;
        uint256 amount;
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

    uint256 private _nextOrderId = 1;
    uint256 private _nextTradeId = 1;

    mapping(uint256 => Order) public orders;
    mapping(uint256 => Trade) public trades;
    uint256[] private _activeOrderIds;

    event OrderPlaced(
        uint256 indexed orderId,
        address indexed agent,
        bool isBuy,
        uint256 price,
        uint256 amount
    );
    event OrderCancelled(uint256 indexed orderId, address indexed agent);
    event TradeExecuted(
        uint256 indexed tradeId,
        uint256 buyOrderId,
        uint256 sellOrderId,
        address buyer,
        address seller,
        uint256 price,
        uint256 amount
    );

    function placeOrder(
        bool isBuy,
        uint256 price,
        uint256 amount
    ) external returns (uint256 orderId) {
        require(price > 0, "Price must be > 0");
        require(amount > 0, "Amount must be > 0");

        orderId = _nextOrderId++;
        orders[orderId] = Order({
            id: orderId,
            agent: msg.sender,
            isBuy: isBuy,
            price: price,
            amount: amount,
            timestamp: block.timestamp,
            active: true
        });
        _activeOrderIds.push(orderId);

        emit OrderPlaced(orderId, msg.sender, isBuy, price, amount);
    }

    function cancelOrder(uint256 orderId) external {
        Order storage order = orders[orderId];
        require(order.active, "Order not active");
        require(order.agent == msg.sender, "Not your order");

        order.active = false;
        _removeFromActive(orderId);

        emit OrderCancelled(orderId, msg.sender);
    }

    function executeTrade(
        uint256 buyOrderId,
        uint256 sellOrderId
    ) external returns (uint256 tradeId) {
        Order storage buyOrder = orders[buyOrderId];
        Order storage sellOrder = orders[sellOrderId];

        require(buyOrder.active, "Buy order not active");
        require(sellOrder.active, "Sell order not active");
        require(buyOrder.isBuy, "Not a buy order");
        require(!sellOrder.isBuy, "Not a sell order");
        require(buyOrder.price >= sellOrder.price, "Price mismatch");

        uint256 executedAmount = buyOrder.amount < sellOrder.amount
            ? buyOrder.amount
            : sellOrder.amount;
        uint256 executedPrice = sellOrder.price;

        buyOrder.active = false;
        sellOrder.active = false;
        _removeFromActive(buyOrderId);
        _removeFromActive(sellOrderId);

        tradeId = _nextTradeId++;
        trades[tradeId] = Trade({
            id: tradeId,
            buyOrderId: buyOrderId,
            sellOrderId: sellOrderId,
            buyer: buyOrder.agent,
            seller: sellOrder.agent,
            price: executedPrice,
            amount: executedAmount,
            timestamp: block.timestamp
        });

        emit TradeExecuted(
            tradeId,
            buyOrderId,
            sellOrderId,
            buyOrder.agent,
            sellOrder.agent,
            executedPrice,
            executedAmount
        );
    }

    function getOrder(uint256 orderId) external view returns (Order memory) {
        return orders[orderId];
    }

    function getTrade(uint256 tradeId) external view returns (Trade memory) {
        return trades[tradeId];
    }

    function getActiveOrders() external view returns (uint256[] memory) {
        return _activeOrderIds;
    }

    function _removeFromActive(uint256 orderId) internal {
        uint256 len = _activeOrderIds.length;
        for (uint256 i = 0; i < len; i++) {
            if (_activeOrderIds[i] == orderId) {
                _activeOrderIds[i] = _activeOrderIds[len - 1];
                _activeOrderIds.pop();
                break;
            }
        }
    }
}
