const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-network-helpers");

describe("AgentRegistry", function () {
  async function deployFixture() {
    const [owner, agent1, agent2, stranger] = await ethers.getSigners();
    const registry = await ethers.deployContract("AgentRegistry");
    return { registry, owner, agent1, agent2, stranger };
  }

  describe("register(agent, name, strategy)", function () {
    it("stores agent info with default reputation 100 and emits AgentRegistered", async function () {
      const { registry, owner, agent1 } = await loadFixture(deployFixture);
      await expect(registry.connect(owner).register(agent1.address, "Alpha", "momentum"))
        .to.emit(registry, "AgentRegistered")
        .withArgs(agent1.address, "Alpha", "momentum");

      const info = await registry.getAgent(agent1.address);
      expect(info.wallet).to.equal(agent1.address);
      expect(info.name).to.equal("Alpha");
      expect(info.strategy).to.equal("momentum");
      expect(info.reputation).to.equal(100n);
      expect(info.tradesExecuted).to.equal(0n);
      expect(info.active).to.be.true;
    });

    it("reverts when registering the same agent twice", async function () {
      const { registry, owner, agent1 } = await loadFixture(deployFixture);
      await registry.connect(owner).register(agent1.address, "Alpha", "momentum");
      await expect(registry.connect(owner).register(agent1.address, "Alpha2", "mean-rev"))
        .to.be.revertedWith("Already registered");
    });

    it("reverts for zero address", async function () {
      const { registry, owner } = await loadFixture(deployFixture);
      await expect(registry.connect(owner).register(ethers.ZeroAddress, "Zero", "none"))
        .to.be.revertedWith("Zero address");
    });

    it("reverts for non-owner", async function () {
      const { registry, stranger, agent1 } = await loadFixture(deployFixture);
      await expect(registry.connect(stranger).register(agent1.address, "Alpha", "momentum"))
        .to.be.revertedWith("Not owner");
    });
  });

  describe("updateReputation(agent, delta)", function () {
    it("applies a positive delta and emits ReputationUpdated", async function () {
      const { registry, owner, agent1 } = await loadFixture(deployFixture);
      await registry.connect(owner).register(agent1.address, "Alpha", "momentum");
      await expect(registry.connect(owner).updateReputation(agent1.address, 50n))
        .to.emit(registry, "ReputationUpdated")
        .withArgs(agent1.address, 50n, 150n);
      expect((await registry.getAgent(agent1.address)).reputation).to.equal(150n);
    });

    it("applies a negative delta correctly", async function () {
      const { registry, owner, agent1 } = await loadFixture(deployFixture);
      await registry.connect(owner).register(agent1.address, "Alpha", "momentum");
      await registry.connect(owner).updateReputation(agent1.address, -30n);
      expect((await registry.getAgent(agent1.address)).reputation).to.equal(70n);
    });

    it("reverts for an unregistered agent", async function () {
      const { registry, owner, agent1 } = await loadFixture(deployFixture);
      await expect(registry.connect(owner).updateReputation(agent1.address, 10n))
        .to.be.revertedWith("Not registered");
    });

    it("reverts for non-owner", async function () {
      const { registry, owner, stranger, agent1 } = await loadFixture(deployFixture);
      await registry.connect(owner).register(agent1.address, "Alpha", "momentum");
      await expect(registry.connect(stranger).updateReputation(agent1.address, 10n))
        .to.be.revertedWith("Not owner");
    });
  });

  describe("incrementTrades(agent)", function () {
    it("increments the trade counter on each call", async function () {
      const { registry, owner, agent1 } = await loadFixture(deployFixture);
      await registry.connect(owner).register(agent1.address, "Alpha", "momentum");
      await registry.connect(owner).incrementTrades(agent1.address);
      await registry.connect(owner).incrementTrades(agent1.address);
      expect((await registry.getAgent(agent1.address)).tradesExecuted).to.equal(2n);
    });

    it("reverts for an unregistered agent", async function () {
      const { registry, owner, agent1 } = await loadFixture(deployFixture);
      await expect(registry.connect(owner).incrementTrades(agent1.address))
        .to.be.revertedWith("Not registered");
    });

    it("reverts for non-owner", async function () {
      const { registry, owner, stranger, agent1 } = await loadFixture(deployFixture);
      await registry.connect(owner).register(agent1.address, "Alpha", "momentum");
      await expect(registry.connect(stranger).incrementTrades(agent1.address))
        .to.be.revertedWith("Not owner");
    });
  });

  describe("view functions", function () {
    it("getAllAgents returns all registered addresses in insertion order", async function () {
      const { registry, owner, agent1, agent2 } = await loadFixture(deployFixture);
      await registry.connect(owner).register(agent1.address, "Alpha", "momentum");
      await registry.connect(owner).register(agent2.address, "Beta", "mean-rev");
      const all = await registry.getAllAgents();
      expect(all).to.deep.equal([agent1.address, agent2.address]);
    });

    it("isRegistered returns false before and true after registration", async function () {
      const { registry, owner, agent1 } = await loadFixture(deployFixture);
      expect(await registry.isRegistered(agent1.address)).to.be.false;
      await registry.connect(owner).register(agent1.address, "Alpha", "momentum");
      expect(await registry.isRegistered(agent1.address)).to.be.true;
    });

    it("getAgent returns zeroed struct for an unknown address", async function () {
      const { registry, agent1 } = await loadFixture(deployFixture);
      const info = await registry.getAgent(agent1.address);
      expect(info.wallet).to.equal(ethers.ZeroAddress);
      expect(info.active).to.be.false;
    });
  });
});
