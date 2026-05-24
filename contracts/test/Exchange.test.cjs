const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-network-helpers");

const P = (x) => ethers.parseEther(String(x));

describe("Exchange", function () {
  async function deployFixture() {
    const [owner, buyer, seller, agent3] = await ethers.getSigners();
    const exchange = await ethers.deployContract("Exchange");
    return { exchange, owner, buyer, seller, agent3 };
  }

  describe("placeOrder(isBuy, price, amount)", function () {
    it("assigns incrementing orderIds starting at 1 and emits OrderPlaced", async function () {
      const { exchange, buyer, seller } = await loadFixture(deployFixture);
      await expect(exchange.connect(buyer).placeOrder(true, P(100), P(1)))
        .to.emit(exchange, "OrderPlaced")
        .withArgs(1n, buyer.address, true, P(100), P(1));
      await expect(exchange.connect(seller).placeOrder(false, P(200), P(1)))
        .to.emit(exchange, "OrderPlaced")
        .withArgs(2n, seller.address, false, P(200), P(1));
    });

    it("stores the order with correct fields", async function () {
      const { exchange, buyer } = await loadFixture(deployFixture);
      await exchange.connect(buyer).placeOrder(true, P(100), P(1));
      const order = await exchange.getOrder(1n);
      expect(order.id).to.equal(1n);
      expect(order.agent).to.equal(buyer.address);
      expect(order.isBuy).to.be.true;
      expect(order.price).to.equal(P(100));
      expect(order.amount).to.equal(P(1));
      expect(order.filled).to.equal(0n);
      expect(order.active).to.be.true;
    });

    it("adds an unmatched order to the active book", async function () {
      const { exchange, buyer, seller } = await loadFixture(deployFixture);
      await exchange.connect(buyer).placeOrder(true,  P(90),  P(1));
      await exchange.connect(seller).placeOrder(false, P(110), P(1));
      expect(await exchange.getActiveBuys()).to.deep.equal([1n]);
      expect(await exchange.getActiveSells()).to.deep.equal([2n]);
    });

    it("reverts when price is 0", async function () {
      const { exchange, buyer } = await loadFixture(deployFixture);
      await expect(exchange.connect(buyer).placeOrder(true, 0n, P(1)))
        .to.be.revertedWith("Price must be > 0");
    });

    it("reverts when amount is 0", async function () {
      const { exchange, buyer } = await loadFixture(deployFixture);
      await expect(exchange.connect(buyer).placeOrder(true, P(100), 0n))
        .to.be.revertedWith("Amount must be > 0");
    });
  });

  describe("Order matching", function () {
    it("exact price match fully fills both orders and emits TradeExecuted", async function () {
      const { exchange, buyer, seller } = await loadFixture(deployFixture);
      const price = P(100);
      const amount = P(1);

      await exchange.connect(seller).placeOrder(false, price, amount); // orderId=1
      await expect(exchange.connect(buyer).placeOrder(true, price, amount)) // orderId=2
        .to.emit(exchange, "TradeExecuted")
        .withArgs(1n, 2n, 1n, buyer.address, seller.address, price, amount);

      expect((await exchange.getOrder(1n)).active).to.be.false;
      expect((await exchange.getOrder(2n)).active).to.be.false;
      expect(await exchange.getActiveBuys()).to.deep.equal([]);
      expect(await exchange.getActiveSells()).to.deep.equal([]);
      expect(await exchange.getLastTradePrice()).to.equal(price);
      expect(await exchange.hasTraded()).to.be.true;
    });

    it("buy price above ask fills at the maker's (sell) price", async function () {
      const { exchange, buyer, seller } = await loadFixture(deployFixture);
      await exchange.connect(seller).placeOrder(false, P(90), P(1)); // sell at 90
      await exchange.connect(buyer).placeOrder(true, P(100), P(1));  // buy at 100 → fills at 90
      const trade = await exchange.getTrade(1n);
      expect(trade.price).to.equal(P(90));
    });

    it("no match when buy price is below ask price (spread exists)", async function () {
      const { exchange, buyer, seller } = await loadFixture(deployFixture);
      await exchange.connect(seller).placeOrder(false, P(110), P(1));
      await exchange.connect(buyer).placeOrder(true,  P(90),  P(1));
      expect((await exchange.getActiveBuys()).length).to.equal(1);
      expect((await exchange.getActiveSells()).length).to.equal(1);
      expect(await exchange.hasTraded()).to.be.false;
    });

    it("partial fill — smaller buy against a larger sell leaves sell partially filled and active", async function () {
      const { exchange, buyer, seller } = await loadFixture(deployFixture);
      const price = P(100);
      await exchange.connect(seller).placeOrder(false, price, P(3)); // sell 3, orderId=1
      await exchange.connect(buyer).placeOrder(true,  price, P(1));  // buy 1,  orderId=2

      const sellOrder = await exchange.getOrder(1n);
      expect(sellOrder.filled).to.equal(P(1));
      expect(sellOrder.active).to.be.true;
      expect((await exchange.getOrder(2n)).active).to.be.false;
      expect((await exchange.getActiveSells()).length).to.equal(1);
    });

    it("matches first eligible sell in insertion order (FIFO, not by best price)", async function () {
      const { exchange, buyer, seller, agent3 } = await loadFixture(deployFixture);
      // Insert lower-priced sell first so it's matched first
      await exchange.connect(agent3).placeOrder(false, P(95),  P(1)); // orderId=1 — first in book
      await exchange.connect(seller).placeOrder(false, P(105), P(1)); // orderId=2 — second
      await exchange.connect(buyer).placeOrder(true,  P(110), P(1));  // matches orderId=1
      const trade = await exchange.getTrade(1n);
      expect(trade.price).to.equal(P(95));
      expect(trade.sellOrderId).to.equal(1n);
    });

    it("one buy can fill against multiple sells in sequence", async function () {
      const { exchange, buyer, seller, agent3 } = await loadFixture(deployFixture);
      const price = P(100);
      await exchange.connect(seller).placeOrder(false, price, P(1)); // orderId=1
      await exchange.connect(agent3).placeOrder(false, price, P(1)); // orderId=2
      await exchange.connect(buyer).placeOrder(true,  price, P(2));  // orderId=3 → fills both

      expect((await exchange.getOrder(1n)).active).to.be.false;
      expect((await exchange.getOrder(2n)).active).to.be.false;
      expect((await exchange.getOrder(3n)).active).to.be.false;
      expect(await exchange.getActiveSells()).to.deep.equal([]);
    });
  });

  describe("cancelOrder(orderId)", function () {
    it("deactivates the order, removes it from the book, and emits OrderCancelled", async function () {
      const { exchange, seller } = await loadFixture(deployFixture);
      await exchange.connect(seller).placeOrder(false, P(100), P(1));
      await expect(exchange.connect(seller).cancelOrder(1n))
        .to.emit(exchange, "OrderCancelled")
        .withArgs(1n, seller.address);
      expect((await exchange.getOrder(1n)).active).to.be.false;
      expect(await exchange.getActiveSells()).to.deep.equal([]);
    });

    it("reverts when cancelling another agent's order", async function () {
      const { exchange, seller, buyer } = await loadFixture(deployFixture);
      await exchange.connect(seller).placeOrder(false, P(100), P(1));
      await expect(exchange.connect(buyer).cancelOrder(1n))
        .to.be.revertedWith("Not your order");
    });

    it("reverts when the order is already inactive", async function () {
      const { exchange, seller } = await loadFixture(deployFixture);
      await exchange.connect(seller).placeOrder(false, P(100), P(1));
      await exchange.connect(seller).cancelOrder(1n);
      await expect(exchange.connect(seller).cancelOrder(1n))
        .to.be.revertedWith("Order not active");
    });
  });

  describe("View functions", function () {
    it("getBestBid returns the highest active buy price", async function () {
      const { exchange, buyer, agent3 } = await loadFixture(deployFixture);
      await exchange.connect(buyer).placeOrder(true, P(90), P(1));
      await exchange.connect(agent3).placeOrder(true, P(95), P(1));
      const [price, exists] = await exchange.getBestBid();
      expect(exists).to.be.true;
      expect(price).to.equal(P(95));
    });

    it("getBestAsk returns the lowest active sell price", async function () {
      const { exchange, seller, agent3 } = await loadFixture(deployFixture);
      await exchange.connect(seller).placeOrder(false, P(110), P(1));
      await exchange.connect(agent3).placeOrder(false, P(105), P(1));
      const [price, exists] = await exchange.getBestAsk();
      expect(exists).to.be.true;
      expect(price).to.equal(P(105));
    });

    it("getBestBid returns exists=false when no active buys", async function () {
      const { exchange } = await loadFixture(deployFixture);
      const [, exists] = await exchange.getBestBid();
      expect(exists).to.be.false;
    });

    it("getBestAsk returns exists=false when no active sells", async function () {
      const { exchange } = await loadFixture(deployFixture);
      const [, exists] = await exchange.getBestAsk();
      expect(exists).to.be.false;
    });

    it("getOrdersByAgent returns only active orders for that agent", async function () {
      const { exchange, buyer } = await loadFixture(deployFixture);
      await exchange.connect(buyer).placeOrder(true, P(90), P(1)); // orderId=1
      await exchange.connect(buyer).placeOrder(true, P(95), P(1)); // orderId=2
      await exchange.connect(buyer).cancelOrder(1n);
      const active = await exchange.getOrdersByAgent(buyer.address);
      expect(active).to.deep.equal([2n]);
    });

    it("getActiveOrders returns combined buy and sell order ids", async function () {
      const { exchange, buyer, seller } = await loadFixture(deployFixture);
      await exchange.connect(buyer).placeOrder(true,  P(90),  P(1)); // orderId=1
      await exchange.connect(seller).placeOrder(false, P(110), P(1)); // orderId=2
      const active = await exchange.getActiveOrders();
      expect(active.length).to.equal(2);
      expect(active).to.include(1n);
      expect(active).to.include(2n);
    });

    it("getLastTradePrice returns 0 before any trade", async function () {
      const { exchange } = await loadFixture(deployFixture);
      expect(await exchange.getLastTradePrice()).to.equal(0n);
    });
  });
});
