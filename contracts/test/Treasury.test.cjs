const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-network-helpers");

describe("Treasury", function () {
  async function deployFixture() {
    const [owner, agent1, agent2] = await ethers.getSigners();
    const treasury = await ethers.deployContract("Treasury");
    return { treasury, owner, agent1, agent2 };
  }

  describe("deposit()", function () {
    it("credits msg.sender and emits Deposited", async function () {
      const { treasury, agent1 } = await loadFixture(deployFixture);
      const amount = ethers.parseEther("1");
      await expect(treasury.connect(agent1).deposit({ value: amount }))
        .to.emit(treasury, "Deposited")
        .withArgs(agent1.address, amount);
      expect(await treasury.balances(agent1.address)).to.equal(amount);
    });

    it("reverts when msg.value is 0", async function () {
      const { treasury, agent1 } = await loadFixture(deployFixture);
      await expect(treasury.connect(agent1).deposit({ value: 0 }))
        .to.be.revertedWith("Must send ETH");
    });
  });

  describe("depositFor(agent)", function () {
    it("credits the specified agent and emits Deposited", async function () {
      const { treasury, owner, agent1 } = await loadFixture(deployFixture);
      const amount = ethers.parseEther("0.5");
      await expect(treasury.connect(owner).depositFor(agent1.address, { value: amount }))
        .to.emit(treasury, "Deposited")
        .withArgs(agent1.address, amount);
      expect(await treasury.balances(agent1.address)).to.equal(amount);
    });

    it("reverts when msg.value is 0", async function () {
      const { treasury, owner, agent1 } = await loadFixture(deployFixture);
      await expect(treasury.connect(owner).depositFor(agent1.address, { value: 0 }))
        .to.be.revertedWith("Must send ETH");
    });
  });

  describe("withdraw(amount)", function () {
    it("decrements balance, sends ETH to caller, and emits Withdrawn", async function () {
      const { treasury, agent1 } = await loadFixture(deployFixture);
      const amount = ethers.parseEther("1");
      await treasury.connect(agent1).deposit({ value: amount });

      const withdrawTx = treasury.connect(agent1).withdraw(amount);
      await expect(withdrawTx)
        .to.emit(treasury, "Withdrawn")
        .withArgs(agent1.address, amount);
      await expect(withdrawTx)
        .to.changeEtherBalance(agent1, amount);

      expect(await treasury.balances(agent1.address)).to.equal(0n);
    });

    it("allows partial withdrawal", async function () {
      const { treasury, agent1 } = await loadFixture(deployFixture);
      const deposit = ethers.parseEther("2");
      const withdraw = ethers.parseEther("1");
      await treasury.connect(agent1).deposit({ value: deposit });
      await treasury.connect(agent1).withdraw(withdraw);
      expect(await treasury.balances(agent1.address)).to.equal(deposit - withdraw);
    });

    it("reverts on insufficient balance", async function () {
      const { treasury, agent1 } = await loadFixture(deployFixture);
      await expect(treasury.connect(agent1).withdraw(1n))
        .to.be.revertedWith("Insufficient balance");
    });
  });

  describe("allocate(from, to, amount)", function () {
    it("shifts balance between accounts and emits Allocated", async function () {
      const { treasury, owner, agent1, agent2 } = await loadFixture(deployFixture);
      const amount = ethers.parseEther("1");
      await treasury.connect(agent1).deposit({ value: amount });

      await expect(treasury.connect(owner).allocate(agent1.address, agent2.address, amount))
        .to.emit(treasury, "Allocated")
        .withArgs(agent1.address, agent2.address, amount);

      expect(await treasury.balances(agent1.address)).to.equal(0n);
      expect(await treasury.balances(agent2.address)).to.equal(amount);
    });

    it("reverts on insufficient source balance", async function () {
      const { treasury, owner, agent1, agent2 } = await loadFixture(deployFixture);
      await expect(treasury.connect(owner).allocate(agent1.address, agent2.address, 1n))
        .to.be.revertedWith("Insufficient balance");
    });

    it("reverts for non-owner", async function () {
      const { treasury, agent1, agent2 } = await loadFixture(deployFixture);
      await expect(treasury.connect(agent1).allocate(agent1.address, agent2.address, 0n))
        .to.be.revertedWith("Not owner");
    });
  });

  describe("getBalance() / totalLocked()", function () {
    it("getBalance returns the credited balance for an agent", async function () {
      const { treasury, agent1 } = await loadFixture(deployFixture);
      await treasury.connect(agent1).deposit({ value: ethers.parseEther("2") });
      expect(await treasury.getBalance(agent1.address)).to.equal(ethers.parseEther("2"));
    });

    it("totalLocked returns the sum of all deposits", async function () {
      const { treasury, agent1, agent2 } = await loadFixture(deployFixture);
      await treasury.connect(agent1).deposit({ value: ethers.parseEther("1") });
      await treasury.connect(agent2).deposit({ value: ethers.parseEther("0.5") });
      expect(await treasury.totalLocked()).to.equal(ethers.parseEther("1.5"));
    });

    it("totalLocked decreases after withdrawal", async function () {
      const { treasury, agent1 } = await loadFixture(deployFixture);
      await treasury.connect(agent1).deposit({ value: ethers.parseEther("1") });
      await treasury.connect(agent1).withdraw(ethers.parseEther("0.4"));
      expect(await treasury.totalLocked()).to.equal(ethers.parseEther("0.6"));
    });
  });
});
