const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-network-helpers");

const PRICE_URL      = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd";
const PRICE_SELECTOR = "ethereum.usd";

describe("AgentRegistry", function () {
  async function deployFixture() {
    const [owner, user, stranger] = await ethers.getSigners();

    // Deploy a minimal coordinator stub so registry can call addAgentToList
    const platform   = await ethers.deployContract("MockPlatform");
    const tokenF     = await ethers.getContractFactory("AgentToken");
    const token      = await upgrades.deployProxy(tokenF, ["Test Token", "TST"], { kind: "transparent", initializer: "initialize" });
    await token.waitForDeployment();
    const quoteF     = await ethers.getContractFactory("QuoteToken");
    const quoteToken = await upgrades.deployProxy(quoteF, [], { kind: "transparent", initializer: "initialize" });
    await quoteToken.waitForDeployment();
    const exchangeF  = await ethers.getContractFactory("Exchange");
    const exchange   = await upgrades.deployProxy(exchangeF, [await token.getAddress(), await quoteToken.getAddress()], { kind: "transparent", initializer: "initialize" });
    await exchange.waitForDeployment();

    const CoordFactory = await ethers.getContractFactory("AgentCoordinator");
    const coordinator  = await upgrades.deployProxy(
      CoordFactory,
      [owner.address, 1n, 2n],
      { kind: "transparent", constructorArgs: [await platform.getAddress(), await exchange.getAddress()], initializer: "initialize" }
    );
    await coordinator.waitForDeployment();

    const RegFactory = await ethers.getContractFactory("AgentRegistry");
    const registry   = await upgrades.deployProxy(
      RegFactory,
      [owner.address, await coordinator.getAddress()],
      { kind: "transparent", initializer: "initialize" }
    );
    await registry.waitForDeployment();
    await coordinator.setRegistry(await registry.getAddress());

    return { registry, coordinator, owner, user, stranger };
  }

  describe("registerAgent()", function () {
    it("stores agent info and emits AgentRegistered", async function () {
      const { registry, owner } = await loadFixture(deployFixture);
      await expect(
        registry.connect(owner).registerAgent(
          "agent1", "Alpha", "⚖️", 3, "Act as a market maker.", PRICE_URL, PRICE_SELECTOR, 0
        )
      )
        .to.emit(registry, "AgentRegistered")
        .withArgs("agent1", owner.address, "Alpha", "⚖️", 3);

      const info = await registry.agents("agent1");
      expect(info.agentOwner).to.equal(owner.address);
      expect(info.name).to.equal("Alpha");
      expect(info.riskLevel).to.equal(3);
      expect(info.active).to.be.true;
    });

    it("reverts when registering the same agent ID twice", async function () {
      const { registry, owner } = await loadFixture(deployFixture);
      await registry.connect(owner).registerAgent(
        "agent1", "Alpha", "⚖️", 3, "prompt", PRICE_URL, PRICE_SELECTOR, 0
      );
      await expect(
        registry.connect(owner).registerAgent(
          "agent1", "Beta", "📈", 4, "prompt2", PRICE_URL, PRICE_SELECTOR, 0
        )
      ).to.be.revertedWith("Agent ID already taken");
    });

    it("reverts for riskLevel outside 1-5", async function () {
      const { registry, owner } = await loadFixture(deployFixture);
      await expect(
        registry.connect(owner).registerAgent(
          "bad", "Bad", "❌", 6, "prompt", PRICE_URL, PRICE_SELECTOR, 0
        )
      ).to.be.revertedWith("riskLevel must be 1-5");
    });

    it("reverts when priceUrl is empty", async function () {
      const { registry, owner } = await loadFixture(deployFixture);
      await expect(
        registry.connect(owner).registerAgent("bad", "Bad", "❌", 3, "prompt", "", "", 0)
      ).to.be.revertedWith("priceUrl required");
    });

    it("any user can register their own agent (msg.sender becomes owner)", async function () {
      const { registry, user } = await loadFixture(deployFixture);
      await registry.connect(user).registerAgent(
        "user_agent", "UserAgent", "🤖", 2, "my strategy", PRICE_URL, PRICE_SELECTOR, 0
      );
      const info = await registry.agents("user_agent");
      expect(info.agentOwner).to.equal(user.address);
    });
  });

  describe("pauseAgent / resumeAgent", function () {
    async function withAgent(fixture) {
      await fixture.registry.connect(fixture.owner).registerAgent(
        "agent1", "Alpha", "⚖️", 3, "prompt", PRICE_URL, PRICE_SELECTOR, 0
      );
      return fixture;
    }

    it("owner can pause and resume an agent", async function () {
      const { registry, owner } = await withAgent(await loadFixture(deployFixture));
      await expect(registry.connect(owner).pauseAgent("agent1"))
        .to.emit(registry, "AgentPaused").withArgs("agent1", owner.address);
      await expect(registry.connect(owner).resumeAgent("agent1"))
        .to.emit(registry, "AgentResumed").withArgs("agent1", owner.address);
    });

    it("agent owner can pause and resume their own agent", async function () {
      const { registry, user } = await loadFixture(deployFixture);
      await registry.connect(user).registerAgent(
        "user_agent", "UserAgent", "🤖", 2, "prompt", PRICE_URL, PRICE_SELECTOR, 0
      );
      await expect(registry.connect(user).pauseAgent("user_agent"))
        .to.emit(registry, "AgentPaused");
    });

    it("stranger cannot pause another user's agent", async function () {
      const { registry, owner, stranger } = await withAgent(await loadFixture(deployFixture));
      await expect(registry.connect(stranger).pauseAgent("agent1"))
        .to.be.revertedWith("Not authorized: must be contract owner or agent owner");
    });
  });

  describe("Config getters", function () {
    it("getSystemPrompt returns the registered prompt", async function () {
      const { registry, owner } = await loadFixture(deployFixture);
      await registry.connect(owner).registerAgent(
        "agent1", "Alpha", "⚖️", 3, "Be aggressive.", PRICE_URL, PRICE_SELECTOR, 0
      );
      expect(await registry.getSystemPrompt("agent1")).to.equal("Be aggressive.");
    });

    it("getPriceConfig returns the registered price config", async function () {
      const { registry, owner } = await loadFixture(deployFixture);
      await registry.connect(owner).registerAgent(
        "agent1", "Alpha", "⚖️", 3, "prompt", PRICE_URL, PRICE_SELECTOR, 2
      );
      const [url, selector, decimals] = await registry.getPriceConfig("agent1");
      expect(url).to.equal(PRICE_URL);
      expect(selector).to.equal(PRICE_SELECTOR);
      expect(decimals).to.equal(2);
    });

    it("getRiskLevel returns the registered risk level", async function () {
      const { registry, owner } = await loadFixture(deployFixture);
      await registry.connect(owner).registerAgent(
        "agent1", "Alpha", "⚖️", 4, "prompt", PRICE_URL, PRICE_SELECTOR, 0
      );
      expect(await registry.getRiskLevel("agent1")).to.equal(4);
    });
  });

  describe("Discovery", function () {
    it("getAllAgentIds returns all registered IDs in insertion order", async function () {
      const { registry, owner } = await loadFixture(deployFixture);
      await registry.connect(owner).registerAgent("a1", "A1", "⚖️", 3, "p", PRICE_URL, PRICE_SELECTOR, 0);
      await registry.connect(owner).registerAgent("a2", "A2", "📈", 3, "p", PRICE_URL, PRICE_SELECTOR, 0);
      const ids = await registry.getAllAgentIds();
      expect(ids).to.deep.equal(["a1", "a2"]);
    });

    it("isRegistered returns false before and true after registration", async function () {
      const { registry, owner } = await loadFixture(deployFixture);
      expect(await registry.isRegistered("agent1")).to.be.false;
      await registry.connect(owner).registerAgent(
        "agent1", "Alpha", "⚖️", 3, "prompt", PRICE_URL, PRICE_SELECTOR, 0
      );
      expect(await registry.isRegistered("agent1")).to.be.true;
    });
  });
});
