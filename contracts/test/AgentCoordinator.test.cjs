const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-network-helpers");
const { anyValue } = require("@nomicfoundation/hardhat-chai-matchers/withArgs");

// MockPlatform.getRequestDeposit() returns 0, so all balance guards pass without
// funding the coordinator.
//
// Request ID sequence (MockPlatform._nextId starts at 1):
//   triggerAgentDecision   → createRequest → reqId=1  (price fetch)
//   simulatePriceCallback  → createRequest → reqId=2  (LLM inference)
//   simulateLLMCallback    → _retrigger    → reqId=3  (next price fetch)

const AGENT_ID = "agent1";

describe("AgentCoordinator", function () {
  async function deployFixture() {
    const [owner, stranger] = await ethers.getSigners();

    const platform    = await ethers.deployContract("MockPlatform");
    const token       = await ethers.deployContract("AgentToken", ["Test Token", "TST"]);
    const exchange    = await ethers.deployContract("Exchange", [await token.getAddress()]);
    const coordinator = await ethers.deployContract("AgentCoordinator", [
      await platform.getAddress(),
      await exchange.getAddress(),
      1n, // llmAgentId
      2n, // jsonApiAgentId
    ]);

    // Mint AGT to coordinator and approve Exchange so SELL orders don't revert
    await token.mint(await coordinator.getAddress(), ethers.parseEther("1000000"));
    await coordinator.approveToken(
      await token.getAddress(),
      await exchange.getAddress(),
      ethers.MaxUint256
    );

    await coordinator.setAgentConfig(AGENT_ID, "https://api.example.com/eth", "$.price", 0);
    await coordinator.setSystemPrompt(AGENT_ID, "Reply BUY, SELL, or HOLD.");

    return { coordinator, platform, exchange, token, owner, stranger };
  }

  // Stage 1: fires price fetch (reqId=1) then delivers price data (llmReqId=2).
  async function triggerAndFetchPrice(coordinator, platform, price = 3000n) {
    await coordinator.triggerAgentDecision(AGENT_ID);
    await platform.simulatePriceCallback(1n, price);
  }

  describe("Configuration setters (onlyOwner)", function () {
    it("setAgentConfig stores the config and reverts for non-owner", async function () {
      const { coordinator, stranger } = await loadFixture(deployFixture);
      const cfg = await coordinator.agentConfigs(AGENT_ID);
      expect(cfg.priceUrl).to.equal("https://api.example.com/eth");
      expect(cfg.selector).to.equal("$.price");
      expect(cfg.decimals).to.equal(0);

      await expect(coordinator.connect(stranger).setAgentConfig(AGENT_ID, "u", "s", 2))
        .to.be.revertedWith("Not owner");
    });

    it("setSystemPrompt stores the prompt and reverts for non-owner", async function () {
      const { coordinator, stranger } = await loadFixture(deployFixture);
      expect(await coordinator.systemPrompts(AGENT_ID)).to.equal("Reply BUY, SELL, or HOLD.");
      await expect(coordinator.connect(stranger).setSystemPrompt(AGENT_ID, "x"))
        .to.be.revertedWith("Not owner");
    });

    it("setLlmAgentId updates the ID and reverts for non-owner", async function () {
      const { coordinator, stranger } = await loadFixture(deployFixture);
      await coordinator.setLlmAgentId(99n);
      expect(await coordinator.llmAgentId()).to.equal(99n);
      await expect(coordinator.connect(stranger).setLlmAgentId(1n))
        .to.be.revertedWith("Not owner");
    });

    it("setJsonApiAgentId updates the ID and reverts for non-owner", async function () {
      const { coordinator, stranger } = await loadFixture(deployFixture);
      await coordinator.setJsonApiAgentId(88n);
      expect(await coordinator.jsonApiAgentId()).to.equal(88n);
      await expect(coordinator.connect(stranger).setJsonApiAgentId(2n))
        .to.be.revertedWith("Not owner");
    });
  });

  describe("fund() / withdraw()", function () {
    it("accepts ETH via fund() and getBalance reflects it", async function () {
      const { coordinator } = await loadFixture(deployFixture);
      await coordinator.fund({ value: ethers.parseEther("1") });
      expect(await coordinator.getBalance()).to.equal(ethers.parseEther("1"));
    });

    it("owner can withdraw the full balance", async function () {
      const { coordinator, owner } = await loadFixture(deployFixture);
      await coordinator.fund({ value: ethers.parseEther("1") });
      await expect(coordinator.connect(owner).withdraw())
        .to.changeEtherBalance(owner, ethers.parseEther("1"));
      expect(await coordinator.getBalance()).to.equal(0n);
    });

    it("non-owner cannot withdraw", async function () {
      const { coordinator, stranger } = await loadFixture(deployFixture);
      await coordinator.fund({ value: ethers.parseEther("1") });
      await expect(coordinator.connect(stranger).withdraw())
        .to.be.revertedWith("Not owner");
    });
  });

  describe("triggerAgentDecision(agentId)", function () {
    it("emits DecisionTriggered and records a pending price request", async function () {
      const { coordinator } = await loadFixture(deployFixture);
      await expect(coordinator.triggerAgentDecision(AGENT_ID))
        .to.emit(coordinator, "DecisionTriggered")
        .withArgs(1n, AGENT_ID);

      const pending = await coordinator.pendingPriceRequests(1n);
      expect(pending.agentId).to.equal(AGENT_ID);
      expect(pending.exists).to.be.true;
    });

    it("reverts when no config is set for the agent", async function () {
      const { coordinator } = await loadFixture(deployFixture);
      await expect(coordinator.triggerAgentDecision("unknown_agent"))
        .to.be.revertedWith("No config for agent");
    });
  });

  describe("handlePriceData (stage-1 callback)", function () {
    it("emits LLMRequestFired, stores the LLM request, and consumes the price request", async function () {
      const { coordinator, platform } = await loadFixture(deployFixture);
      await coordinator.triggerAgentDecision(AGENT_ID); // reqId=1

      await expect(platform.simulatePriceCallback(1n, 3000n))
        .to.emit(coordinator, "LLMRequestFired")
        .withArgs(2n, AGENT_ID, 3000n, anyValue);

      const llmPending = await coordinator.pendingLLMRequests(2n);
      expect(llmPending.agentId).to.equal(AGENT_ID);
      expect(llmPending.fetchedPrice).to.equal(3000n);
      expect(llmPending.exists).to.be.true;

      expect((await coordinator.pendingPriceRequests(1n)).exists).to.be.false;
    });
  });

  describe("handleDecision (stage-2 callback)", function () {
    it("BUY: places a buy order at price + offset, emits DecisionExecuted, and re-triggers", async function () {
      const { coordinator, platform } = await loadFixture(deployFixture);
      await triggerAndFetchPrice(coordinator, platform);

      // basePrice = 3000 * 1e18 (decimals=0); BUY offset = +0.1% → * 10010 / 10000
      const basePrice = ethers.parseEther("3000");
      const buyPrice  = basePrice * 10010n / 10000n;

      await expect(platform.simulateLLMCallback(2n, "BUY"))
        .to.emit(coordinator, "DecisionExecuted")
        .withArgs(2n, AGENT_ID, "BUY", buyPrice, 1n, anyValue)
        .and.to.emit(coordinator, "DecisionTriggered") // _retrigger fires immediately
        .withArgs(3n, AGENT_ID);

      expect((await coordinator.pendingLLMRequests(2n)).exists).to.be.false;
    });

    it("SELL: places a sell order at price - offset and emits DecisionExecuted", async function () {
      const { coordinator, platform } = await loadFixture(deployFixture);
      await triggerAndFetchPrice(coordinator, platform);

      const basePrice = ethers.parseEther("3000");
      const sellPrice = basePrice * 9990n / 10000n;

      await expect(platform.simulateLLMCallback(2n, "SELL"))
        .to.emit(coordinator, "DecisionExecuted")
        .withArgs(2n, AGENT_ID, "SELL", sellPrice, 1n, anyValue);
    });

    it("HOLD: emits DecisionExecuted with price=0 and orderId=0, places no order", async function () {
      const { coordinator, platform, exchange } = await loadFixture(deployFixture);
      await triggerAndFetchPrice(coordinator, platform);

      await expect(platform.simulateLLMCallback(2n, "HOLD"))
        .to.emit(coordinator, "DecisionExecuted")
        .withArgs(2n, AGENT_ID, "HOLD", 0n, 0n, 0n);

      expect(await exchange.getActiveOrders()).to.deep.equal([]);
    });

    it("stale order from the previous cycle is cancelled before placing a new one", async function () {
      const { coordinator, platform, exchange } = await loadFixture(deployFixture);

      // Cycle 1: BUY places orderId=1 on exchange, stored as lastOrderId
      await triggerAndFetchPrice(coordinator, platform);  // reqs 1 & 2
      await platform.simulateLLMCallback(2n, "BUY");      // req 3 from _retrigger

      expect(await coordinator.lastOrderId(AGENT_ID)).to.equal(1n);

      // Cycle 2: _retrigger created reqId=3; simulate its price callback → llmReqId=4
      await platform.simulatePriceCallback(3n, 3000n);

      // Stale orderId=1 should be cancelled; new orderId=2 placed
      await expect(platform.simulateLLMCallback(4n, "BUY"))
        .to.emit(exchange, "OrderCancelled")
        .withArgs(1n, await coordinator.getAddress());

      expect(await coordinator.lastOrderId(AGENT_ID)).to.equal(2n);
    });
  });

  describe("market_maker special case", function () {
    it("posts both BUY and SELL orders around the fetched price, ignoring LLM content", async function () {
      const { coordinator, platform, exchange } = await loadFixture(deployFixture);
      const MM = "market_maker";
      await coordinator.setAgentConfig(MM, "https://api.example.com/eth", "$.price", 0);

      await coordinator.triggerAgentDecision(MM); // reqId=1
      await platform.simulatePriceCallback(1n, 3000n); // llmReqId=2

      const basePrice = ethers.parseEther("3000");
      const bidPrice  = basePrice * 9990n / 10000n;
      const askPrice  = basePrice * 10010n / 10000n;

      await expect(platform.simulateLLMCallback(2n, "HOLD")) // content irrelevant for market_maker
        .to.emit(coordinator, "DecisionExecuted")
        .withArgs(2n, MM, "BUY",  bidPrice, 1n, 0n)
        .and.to.emit(coordinator, "DecisionExecuted")
        .withArgs(2n, MM, "SELL", askPrice, 2n, 0n);

      expect((await exchange.getActiveBuys()).length).to.equal(1);
      expect((await exchange.getActiveSells()).length).to.equal(1);
    });
  });

  describe("lastDecision and winStreak", function () {
    it("stores lastDecision[agentId] after a BUY decision", async function () {
      const { coordinator, platform } = await loadFixture(deployFixture);
      await triggerAndFetchPrice(coordinator, platform); // reqs 1 & 2
      await platform.simulateLLMCallback(2n, "BUY");
      expect(await coordinator.lastDecision(AGENT_ID)).to.equal("BUY");
    });

    it("stores lastDecision[agentId] after a SELL decision", async function () {
      const { coordinator, platform } = await loadFixture(deployFixture);
      await triggerAndFetchPrice(coordinator, platform);
      await platform.simulateLLMCallback(2n, "SELL");
      expect(await coordinator.lastDecision(AGENT_ID)).to.equal("SELL");
    });

    it("stores lastDecision[agentId] = HOLD after a HOLD decision", async function () {
      const { coordinator, platform } = await loadFixture(deployFixture);
      await triggerAndFetchPrice(coordinator, platform);
      await platform.simulateLLMCallback(2n, "HOLD");
      expect(await coordinator.lastDecision(AGENT_ID)).to.equal("HOLD");
    });

    it("winStreak increments after a successful BUY and resets on HOLD", async function () {
      const { coordinator, platform } = await loadFixture(deployFixture);

      // Cycle 1: BUY fills → streak = 1
      await triggerAndFetchPrice(coordinator, platform); // reqs 1 & 2
      await platform.simulateLLMCallback(2n, "BUY");    // req 3 from _retrigger
      expect(await coordinator.winStreak(AGENT_ID)).to.equal(1n);

      // Cycle 2: HOLD → streak resets to 0
      await platform.simulatePriceCallback(3n, 3000n);  // llmReqId=4
      await platform.simulateLLMCallback(4n, "HOLD");
      expect(await coordinator.winStreak(AGENT_ID)).to.equal(0n);
    });

    it("winStreak accumulates across multiple consecutive BUY fills", async function () {
      const { coordinator, platform } = await loadFixture(deployFixture);

      // Cycle 1: BUY → streak=1
      await triggerAndFetchPrice(coordinator, platform); // reqs 1 & 2
      await platform.simulateLLMCallback(2n, "BUY");    // req 3

      // Cycle 2: BUY → streak=2
      await platform.simulatePriceCallback(3n, 3000n);  // llmReqId=4
      await platform.simulateLLMCallback(4n, "BUY");    // req 5

      expect(await coordinator.winStreak(AGENT_ID)).to.equal(2n);
    });
  });

  describe("CoalitionFormed", function () {
    // Deploys with 3 directional agents so _coalitionCount can reach 3.
    async function deployThreeAgentFixture() {
      const [owner] = await ethers.getSigners();
      const platform    = await ethers.deployContract("MockPlatform");
      const token       = await ethers.deployContract("AgentToken", ["Test Token", "TST"]);
      const exchange    = await ethers.deployContract("Exchange", [await token.getAddress()]);
      const coordinator = await ethers.deployContract("AgentCoordinator", [
        await platform.getAddress(),
        await exchange.getAddress(),
        1n, 2n,
      ]);
      await token.mint(await coordinator.getAddress(), ethers.parseEther("1000000"));
      await coordinator.approveToken(
        await token.getAddress(),
        await exchange.getAddress(),
        ethers.MaxUint256
      );
      // Register 3 directional agents (no market_maker — it's non-directional)
      await coordinator.setAgentConfig("agent1", "https://api.example.com/eth", "$.price", 0);
      await coordinator.setAgentConfig("agent2", "https://api.example.com/eth", "$.price", 0);
      await coordinator.setAgentConfig("agent3", "https://api.example.com/eth", "$.price", 0);
      return { coordinator, platform, exchange, token, owner };
    }

    it("emits CoalitionFormed when 3 agents all decide BUY", async function () {
      const { coordinator, platform } = await loadFixture(deployThreeAgentFixture);

      // Trigger all 3 price fetches — reqIds 1, 2, 3
      await coordinator.triggerAgentDecision("agent1");
      await coordinator.triggerAgentDecision("agent2");
      await coordinator.triggerAgentDecision("agent3");

      // Deliver prices — fires LLM requests with reqIds 4, 5, 6
      await platform.simulatePriceCallback(1n, 3000n);
      await platform.simulatePriceCallback(2n, 3000n);
      await platform.simulatePriceCallback(3n, 3000n);

      const basePrice = ethers.parseEther("3000");
      const buyPrice  = basePrice * 10010n / 10000n;

      // agent1 BUY: coalitionCount=1 — no coalition yet
      await platform.simulateLLMCallback(4n, "BUY");
      // agent2 BUY: coalitionCount=2 — no coalition yet
      await platform.simulateLLMCallback(5n, "BUY");
      // agent3 BUY: coalitionCount=3 → CoalitionFormed fires before agent3's own order
      await expect(platform.simulateLLMCallback(6n, "BUY"))
        .to.emit(coordinator, "CoalitionFormed")
        .withArgs("BUY", 3n, buyPrice, anyValue);
    });

    it("does not emit CoalitionFormed when only 2 agents agree", async function () {
      const { coordinator, platform } = await loadFixture(deployThreeAgentFixture);

      await coordinator.triggerAgentDecision("agent1");
      await coordinator.triggerAgentDecision("agent2");
      await coordinator.triggerAgentDecision("agent3");

      await platform.simulatePriceCallback(1n, 3000n);
      await platform.simulatePriceCallback(2n, 3000n);
      await platform.simulatePriceCallback(3n, 3000n);

      // agent1 BUY, agent2 BUY, agent3 SELL — no consensus
      await platform.simulateLLMCallback(4n, "BUY");
      await platform.simulateLLMCallback(5n, "BUY");
      await expect(platform.simulateLLMCallback(6n, "SELL"))
        .to.not.emit(coordinator, "CoalitionFormed");
    });
  });

  describe("triggerWithPrice (backend-injected price)", function () {
    it("owner can call triggerWithPrice and it emits DecisionTriggered with requestId=0", async function () {
      const { coordinator } = await loadFixture(deployFixture);
      await expect(coordinator.triggerWithPrice(AGENT_ID, 3245n))
        .to.emit(coordinator, "DecisionTriggered")
        .withArgs(0n, AGENT_ID)
        .and.to.emit(coordinator, "LLMRequestFired")
        .withArgs(1n, AGENT_ID, 3245n, anyValue);
    });

    it("non-owner reverts", async function () {
      const { coordinator, stranger } = await loadFixture(deployFixture);
      await expect(coordinator.connect(stranger).triggerWithPrice(AGENT_ID, 3000n))
        .to.be.revertedWith("Not owner");
    });

    it("reverts when no config is set for the agent", async function () {
      const { coordinator } = await loadFixture(deployFixture);
      await expect(coordinator.triggerWithPrice("unknown_agent", 3000n))
        .to.be.revertedWith("No config for agent");
    });

    it("subsequent handleDecision callback places an order using the injected price", async function () {
      const { coordinator, platform, exchange } = await loadFixture(deployFixture);

      // triggerWithPrice fires LLM request directly (reqId=1, no JSON API step)
      await coordinator.triggerWithPrice(AGENT_ID, 3000n);

      const basePrice = ethers.parseEther("3000");
      const buyPrice  = basePrice * 10010n / 10000n; // +0.1% for BUY

      await expect(platform.simulateLLMCallback(1n, "BUY"))
        .to.emit(coordinator, "DecisionExecuted")
        .withArgs(1n, AGENT_ID, "BUY", buyPrice, 1n, anyValue);

      expect((await exchange.getActiveBuys()).length).to.equal(1);
    });
  });
});
