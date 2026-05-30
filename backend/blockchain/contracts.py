import asyncio
import json
import logging
from pathlib import Path

from web3 import Web3

from blockchain.client import get_web3, send_transaction
from blockchain.abis import FALLBACK_ABIS

logger = logging.getLogger(__name__)

_ABIS: dict = {}


def _load_abis():
    global _ABIS
    deployments = Path(__file__).parent.parent.parent / "contracts" / "deployments"
    for candidate in ("somnia-testnet.json", "somnia-local.json"):
        deploy_path = deployments / candidate
        if deploy_path.exists():
            with open(deploy_path) as f:
                data = json.load(f)
            loaded = data.get("abis", {})
            if loaded:
                _ABIS = loaded
                logger.info(f"Loaded ABIs from {candidate}")
                return
    _ABIS = FALLBACK_ABIS
    logger.info("Using fallback ABIs")


_load_abis()


class _BaseContract:
    """Shared plumbing: contract binding, thread-safe reads, and transaction sends."""

    def __init__(self, address: str, rpc_url: str, abi_key: str):
        self.address = address
        self.rpc_url = rpc_url
        self._contract = get_web3(rpc_url).eth.contract(
            address=Web3.to_checksum_address(address),
            abi=_ABIS.get(abi_key, []),
        )

    async def _call(self, fn, *, default=None, name: str = "call"):
        """Run a read-only contract call in a thread executor."""
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, fn)
        except Exception as e:
            logger.debug(f"{name} failed: {e}")
            return default

    async def _tx(self, pk: str, fn_name: str, args: list, value: int = 0) -> str:
        """Encode and send a state-mutating transaction. Returns tx_hash."""
        data = self._contract.encode_abi(fn_name, args=args)
        return await send_transaction(
            pk, self.address, bytes.fromhex(data[2:]), value=value, rpc_url=self.rpc_url
        )


# ── Exchange ──────────────────────────────────────────────────────────────────

class ExchangeContract(_BaseContract):
    def __init__(self, address: str, rpc_url: str):
        super().__init__(address, rpc_url, "Exchange")

    async def place_order(self, agent_pk: str, is_buy: bool, price: float, amount: float) -> dict:
        tx_hash = await self._tx(
            agent_pk, "placeOrder",
            [is_buy, int(price * 1e18), int(amount * 1e18)],
        )
        return {"tx_hash": tx_hash, "price": price, "amount": amount, "is_buy": is_buy}

    async def cancel_order(self, agent_pk: str, order_id: int) -> dict:
        tx_hash = await self._tx(agent_pk, "cancelOrder", [order_id])
        return {"tx_hash": tx_hash, "order_id": order_id}

    async def get_best_bid(self) -> tuple[float, bool]:
        result = await self._call(
            lambda: self._contract.functions.getBestBid().call(),
            default=(0, False), name="Exchange.getBestBid",
        )
        price_wei, exists = result
        return (float(Web3.from_wei(price_wei, "ether")), exists)

    async def get_best_ask(self) -> tuple[float, bool]:
        result = await self._call(
            lambda: self._contract.functions.getBestAsk().call(),
            default=(0, False), name="Exchange.getBestAsk",
        )
        price_wei, exists = result
        return (float(Web3.from_wei(price_wei, "ether")), exists)

    async def get_last_trade_price(self) -> float:
        wei = await self._call(
            lambda: self._contract.functions.getLastTradePrice().call(),
            default=0, name="Exchange.getLastTradePrice",
        )
        return float(Web3.from_wei(wei, "ether"))

    async def get_order_book(self, n: int = 10) -> dict:
        """Returns top-N bid/ask price levels aggregated from active on-chain orders."""
        loop = asyncio.get_running_loop()
        try:
            buy_ids, sell_ids = await asyncio.gather(
                loop.run_in_executor(None, lambda: self._contract.functions.getActiveBuys().call()),
                loop.run_in_executor(None, lambda: self._contract.functions.getActiveSells().call()),
            )

            async def fetch_order(oid):
                return await loop.run_in_executor(
                    None, lambda o=oid: self._contract.functions.getOrder(o).call()
                )

            buy_orders, sell_orders = await asyncio.gather(
                asyncio.gather(*[fetch_order(oid) for oid in buy_ids]),
                asyncio.gather(*[fetch_order(oid) for oid in sell_ids]),
            )

            def aggregate(raw_orders, is_buy: bool) -> list[dict]:
                levels: dict[float, float] = {}
                for o in raw_orders:
                    # tuple: (id, agent, isBuy, price, amount, filled, timestamp, active)
                    if not o[7]:
                        continue
                    price = round(float(Web3.from_wei(o[3], "ether")), 4)
                    remaining = float(Web3.from_wei(o[4] - o[5], "ether"))
                    levels[price] = levels.get(price, 0.0) + remaining
                sorted_prices = sorted(levels.keys(), reverse=is_buy)[:n]
                return [{"price": p, "amount": round(levels[p], 4)} for p in sorted_prices]

            return {"bids": aggregate(buy_orders, True), "asks": aggregate(sell_orders, False)}
        except Exception as e:
            logger.debug(f"Exchange.get_order_book failed: {e}")
            return {"bids": [], "asks": []}

    async def get_order_book_depth(self) -> dict:
        loop = asyncio.get_running_loop()
        try:
            buys, sells = await asyncio.gather(
                loop.run_in_executor(None, lambda: self._contract.functions.getActiveBuys().call()),
                loop.run_in_executor(None, lambda: self._contract.functions.getActiveSells().call()),
            )
            return {"buy_count": len(buys), "sell_count": len(sells)}
        except Exception as e:
            logger.debug(f"Exchange.get_order_book_depth failed: {e}")
            return {"buy_count": 0, "sell_count": 0}

    async def get_order_placed_events(self, from_block: int) -> list[dict]:
        events = await self._call(
            lambda: self._contract.events.OrderPlaced.get_logs(
                from_block=from_block, to_block="latest"
            ),
            default=[], name="Exchange.OrderPlaced",
        )
        return [
            {
                "agent":    e["args"]["agent"],
                "order_id": int(e["args"]["orderId"]),
                "is_buy":   e["args"]["isBuy"],
                "price":    float(Web3.from_wei(e["args"]["price"], "ether")),
                "amount":   float(Web3.from_wei(e["args"]["amount"], "ether")),
                "block":    e["blockNumber"],
            }
            for e in events
        ]

    async def get_recent_trade_events(self, from_block: int, to_block: str = "latest") -> list[dict]:
        """Poll TradeExecuted events — includes buyer/seller addresses for P&L attribution."""
        events = await self._call(
            lambda: self._contract.events.TradeExecuted.get_logs(
                from_block=from_block, to_block=to_block
            ),
            default=[], name="Exchange.TradeExecuted",
        )
        return [
            {
                "trade_id":      int(e["args"]["tradeId"]),
                "buy_order_id":  int(e["args"]["buyOrderId"]),
                "sell_order_id": int(e["args"]["sellOrderId"]),
                "buyer":         e["args"]["buyer"],
                "seller":        e["args"]["seller"],
                "price":         float(Web3.from_wei(e["args"]["price"], "ether")),
                "amount":        float(Web3.from_wei(e["args"]["amount"], "ether")),
                "block":         e["blockNumber"],
                "tx_hash":       e["transactionHash"].hex(),
            }
            for e in events
        ]


# ── Treasury ──────────────────────────────────────────────────────────────────

class TreasuryContract(_BaseContract):
    def __init__(self, address: str, rpc_url: str):
        super().__init__(address, rpc_url, "Treasury")

    async def get_balance(self, agent_address: str) -> float:
        wei = await self._call(
            lambda: self._contract.functions.getBalance(
                Web3.to_checksum_address(agent_address)
            ).call(),
            default=0, name=f"Treasury.getBalance({agent_address})",
        )
        return float(Web3.from_wei(wei, "ether"))

    async def get_total_locked(self) -> float:
        wei = await self._call(
            lambda: self._contract.functions.totalLocked().call(),
            default=0, name="Treasury.totalLocked",
        )
        return float(Web3.from_wei(wei, "ether"))


# ── AgentRegistry ─────────────────────────────────────────────────────────────

class AgentRegistryContract(_BaseContract):
    """
    Unified string-ID agent registry.
    Handles system agents (owned by deployer) and user agents (owned by their wallets).
    """

    def __init__(self, address: str, rpc_url: str):
        super().__init__(address, rpc_url, "AgentRegistry")

    async def get_all_agent_ids(self) -> list[str]:
        result = await self._call(
            lambda: self._contract.functions.getAllAgentIds().call(),
            default=[], name="AgentRegistry.getAllAgentIds",
        )
        return [str(a) for a in result]

    async def get_agent(self, agent_id: str) -> dict:
        """Returns AgentInfo for a string agentId."""
        raw = await self._call(
            lambda: self._contract.functions.agents(agent_id).call(),
            default=None, name=f"AgentRegistry.agents({agent_id})",
        )
        if raw is None:
            return {}
        # tuple: (agentOwner, name, icon, riskLevel, createdAt, active)
        return {
            "agentOwner": raw[0],
            "name":       raw[1],
            "icon":       raw[2],
            "riskLevel":  raw[3],
            "createdAt":  raw[4],
            "active":     raw[5],
        }

    async def get_agent_registered_events(self, from_block: int) -> list[dict]:
        """Poll AgentRegistered events to discover newly registered agents."""
        events = await self._call(
            lambda: self._contract.events.AgentRegistered.get_logs(
                from_block=from_block, to_block="latest"
            ),
            default=[], name="AgentRegistry.AgentRegistered",
        )
        return [
            {
                "agentId":    e["args"]["agentId"],
                "agentOwner": e["args"]["agentOwner"],
                "name":       e["args"]["name"],
                "icon":       e["args"]["icon"],
                "riskLevel":  int(e["args"]["riskLevel"]),
                "block":      e["blockNumber"],
            }
            for e in events
        ]

    async def set_active(self, deployer_pk: str, agent_id: str, active: bool) -> None:
        """Toggle agent active flag via pauseAgent / resumeAgent."""
        fn = "resumeAgent" if active else "pauseAgent"
        try:
            await self._tx(deployer_pk, fn, [agent_id])
        except Exception as e:
            logger.debug(f"AgentRegistry.set_active({agent_id}, {active}) failed: {e}")


# ── QuoteToken ────────────────────────────────────────────────────────────────

class QuoteTokenContract(_BaseContract):
    """USDC-equivalent testnet stablecoin used for order escrow."""

    def __init__(self, address: str, rpc_url: str):
        super().__init__(address, rpc_url, "QuoteToken")

    async def get_balance(self, address: str) -> float:
        wei = await self._call(
            lambda: self._contract.functions.balanceOf(
                Web3.to_checksum_address(address)
            ).call(),
            default=0, name=f"QuoteToken.balanceOf({address})",
        )
        return float(Web3.from_wei(wei, "ether"))

    async def mint(self, owner_pk: str, to_address: str, amount_tokens: float) -> dict:
        """Owner-only: mint QUOTE to an address (used for auto-replenishment)."""
        tx_hash = await self._tx(
            owner_pk, "mint",
            [Web3.to_checksum_address(to_address), int(amount_tokens * 1e18)],
        )
        return {"tx_hash": tx_hash, "to": to_address, "amount": amount_tokens}


# ── AgentToken ────────────────────────────────────────────────────────────────

class AgentTokenContract(_BaseContract):
    """ERC20-like AgentToken — funds sell-side order escrow for agents."""

    def __init__(self, address: str, rpc_url: str):
        super().__init__(address, rpc_url, "AgentToken")

    async def mint(self, deployer_pk: str, agent_address: str, amount_tokens: float) -> dict:
        """Mint AGT to agent_address. Requires deployer (owner) key."""
        tx_hash = await self._tx(
            deployer_pk, "mint",
            [Web3.to_checksum_address(agent_address), int(amount_tokens * 1e18)],
        )
        return {"tx_hash": tx_hash, "agent_address": agent_address, "amount": amount_tokens}

    async def get_balance(self, agent_address: str) -> float:
        wei = await self._call(
            lambda: self._contract.functions.balanceOf(
                Web3.to_checksum_address(agent_address)
            ).call(),
            default=0, name=f"AgentToken.balanceOf({agent_address})",
        )
        return float(Web3.from_wei(wei, "ether"))


# ── AgentCoordinator ──────────────────────────────────────────────────────────

class AgentCoordinatorContract(_BaseContract):
    """
    Two-step autonomous agent pipeline:
      1. trigger_decision() → JSON API agent fetches live price on-chain
      2. handlePriceData() callback → LLM Inference agent decides BUY/SELL/HOLD
      3. handleDecision() callback → validator consensus → Exchange.placeOrder()
    Python passes NO market data — everything is sourced on-chain.
    """

    def __init__(self, address: str, rpc_url: str):
        super().__init__(address, rpc_url, "AgentCoordinator")

    async def trigger_decision(self, agent_pk: str, agent_id: str) -> dict:
        """
        Calls triggerAgentDecision(agentId) — first step of the on-chain pipeline.
        Returns immediately; order placement is fully asynchronous.
        """
        tx_hash = await self._tx(agent_pk, "triggerAgentDecision", [agent_id])
        return {"tx_hash": tx_hash, "agent_id": agent_id}

    async def trigger_with_price(self, agent_pk: str, agent_id: str, price: int) -> dict:
        """
        Calls triggerWithPrice(agentId, rawPrice) — skips the JSON API price step.
        Backend supplies a live ETH/USD price (whole USD integer). Requires owner key.
        """
        tx_hash = await self._tx(agent_pk, "triggerWithPrice", [agent_id, price])
        return {"tx_hash": tx_hash, "agent_id": agent_id, "price": price}

    async def get_balance(self) -> float:
        wei = await self._call(
            lambda: self._contract.functions.getBalance().call(),
            default=0, name="AgentCoordinator.getBalance",
        )
        return float(Web3.from_wei(wei, "ether"))

    async def pause_agent(self, deployer_pk: str, agent_id: str) -> dict:
        """Halt the on-chain self-retrigger loop for an agent."""
        tx_hash = await self._tx(deployer_pk, "pauseAgent", [agent_id])
        return {"tx_hash": tx_hash, "agent_id": agent_id}

    async def resume_agent(self, deployer_pk: str, agent_id: str) -> dict:
        """Clear the pause flag and allow the agent loop to restart."""
        tx_hash = await self._tx(deployer_pk, "resumeAgent", [agent_id])
        return {"tx_hash": tx_hash, "agent_id": agent_id}

    async def get_decision_executed_events(self, from_block: int) -> list[dict]:
        """Poll DecisionExecuted events — keeps _order_to_agent current for trade attribution."""
        events = await self._call(
            lambda: self._contract.events.DecisionExecuted.get_logs(
                from_block=from_block, to_block="latest"
            ),
            default=[], name="AgentCoordinator.DecisionExecuted",
        )
        return [
            {"event": "DecisionExecuted", "block": e["blockNumber"], **dict(e["args"])}
            for e in events
        ]

    async def get_coordinator_events(self, from_block: int) -> list[dict]:
        """Poll all coordinator events in one pass, sorted by block number."""
        loop = asyncio.get_running_loop()
        results = []

        event_types = [
            ("DecisionTriggered", self._contract.events.DecisionTriggered),
            ("DecisionExecuted",  self._contract.events.DecisionExecuted),
            ("DecisionFailed",    self._contract.events.DecisionFailed),
            ("LoopStopped",       self._contract.events.LoopStopped),
            ("LLMRequestFired",   self._contract.events.LLMRequestFired),
            ("CoalitionFormed",   self._contract.events.CoalitionFormed),
            ("AgentPaused",       self._contract.events.AgentPaused),
            ("AgentResumed",      self._contract.events.AgentResumed),
            ("AgentOwnerSet",     self._contract.events.AgentOwnerSet),
        ]

        for name, event_cls in event_types:
            try:
                events = await loop.run_in_executor(
                    None,
                    lambda ec=event_cls: ec.get_logs(from_block=from_block, to_block="latest"),
                )
                for e in events:
                    results.append({"event": name, "block": e["blockNumber"], **dict(e["args"])})
            except Exception as e:
                logger.debug(f"AgentCoordinator.{name} event poll failed: {e}")

        results.sort(key=lambda x: x["block"])
        return results
