import asyncio
import json
import logging
from pathlib import Path

from web3 import Web3

from blockchain.client import get_web3, send_transaction

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
            _ABIS = data.get("abis", {})
            logger.info(f"Loaded ABIs from {candidate}")
            return

    # Minimal ABI fallback — updated for real LOB + AgentCoordinator
    _ABIS["Exchange"] = [
        {"inputs": [{"name": "isBuy", "type": "bool"}, {"name": "price", "type": "uint256"}, {"name": "amount", "type": "uint256"}], "name": "placeOrder", "outputs": [{"name": "orderId", "type": "uint256"}], "stateMutability": "nonpayable", "type": "function"},
        {"inputs": [{"name": "orderId", "type": "uint256"}], "name": "cancelOrder", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
        {"inputs": [], "name": "getActiveOrders", "outputs": [{"name": "", "type": "uint256[]"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "getActiveBuys", "outputs": [{"name": "", "type": "uint256[]"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "getActiveSells", "outputs": [{"name": "", "type": "uint256[]"}], "stateMutability": "view", "type": "function"},
        {"inputs": [{"name": "agent", "type": "address"}], "name": "getOrdersByAgent", "outputs": [{"name": "activeIds", "type": "uint256[]"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "getBestBid", "outputs": [{"name": "price", "type": "uint256"}, {"name": "exists", "type": "bool"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "getBestAsk", "outputs": [{"name": "price", "type": "uint256"}, {"name": "exists", "type": "bool"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "getLastTradePrice", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "hasTraded", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
        {"inputs": [{"name": "orderId", "type": "uint256"}], "name": "getOrder", "outputs": [{"components": [{"name": "id", "type": "uint256"}, {"name": "agent", "type": "address"}, {"name": "isBuy", "type": "bool"}, {"name": "price", "type": "uint256"}, {"name": "amount", "type": "uint256"}, {"name": "filled", "type": "uint256"}, {"name": "timestamp", "type": "uint256"}, {"name": "active", "type": "bool"}], "name": "", "type": "tuple"}], "stateMutability": "view", "type": "function"},
        {"anonymous": False, "inputs": [{"indexed": True, "name": "orderId", "type": "uint256"}, {"indexed": True, "name": "agent", "type": "address"}, {"indexed": False, "name": "isBuy", "type": "bool"}, {"indexed": False, "name": "price", "type": "uint256"}, {"indexed": False, "name": "amount", "type": "uint256"}], "name": "OrderPlaced", "type": "event"},
        {"anonymous": False, "inputs": [{"indexed": True, "name": "tradeId", "type": "uint256"}, {"indexed": False, "name": "buyOrderId", "type": "uint256"}, {"indexed": False, "name": "sellOrderId", "type": "uint256"}, {"indexed": True, "name": "buyer", "type": "address"}, {"indexed": True, "name": "seller", "type": "address"}, {"indexed": False, "name": "price", "type": "uint256"}, {"indexed": False, "name": "amount", "type": "uint256"}], "name": "TradeExecuted", "type": "event"},
    ]
    _ABIS["Treasury"] = [
        {"inputs": [], "name": "deposit", "outputs": [], "stateMutability": "payable", "type": "function"},
        {"inputs": [{"name": "agent", "type": "address"}], "name": "getBalance", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "totalLocked", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    ]
    _ABIS["AgentRegistry"] = [
        {"inputs": [{"name": "agent", "type": "address"}], "name": "getAgent", "outputs": [{"components": [{"name": "wallet", "type": "address"}, {"name": "name", "type": "string"}, {"name": "strategy", "type": "string"}, {"name": "reputation", "type": "int256"}, {"name": "tradesExecuted", "type": "uint256"}, {"name": "registeredAt", "type": "uint256"}, {"name": "active", "type": "bool"}], "name": "", "type": "tuple"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "getAllAgents", "outputs": [{"name": "", "type": "address[]"}], "stateMutability": "view", "type": "function"},
        {"inputs": [{"name": "agent", "type": "address"}], "name": "isRegistered", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
        {"inputs": [{"name": "agent", "type": "address"}], "name": "incrementTrades", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
        {"inputs": [{"name": "agent", "type": "address"}, {"name": "delta", "type": "int256"}], "name": "updateReputation", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    ]
    _ABIS["AgentCoordinator"] = [
        {"inputs": [{"name": "agentId", "type": "string"}], "name": "triggerAgentDecision", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
        {"inputs": [{"name": "agentId", "type": "string"}, {"name": "rawPrice", "type": "uint256"}], "name": "triggerWithPrice", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
        {"inputs": [], "name": "getBalance", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
        {"inputs": [{"name": "", "type": "string"}], "name": "winStreak", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
        {"inputs": [{"name": "", "type": "string"}], "name": "lastDecision", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
        {"anonymous": False, "inputs": [{"indexed": True, "name": "requestId", "type": "uint256"}, {"indexed": False, "name": "agentId", "type": "string"}], "name": "DecisionTriggered", "type": "event"},
        {"anonymous": False, "inputs": [{"indexed": True, "name": "llmRequestId", "type": "uint256"}, {"indexed": False, "name": "agentId", "type": "string"}, {"indexed": False, "name": "fetchedPrice", "type": "uint256"}, {"indexed": False, "name": "context", "type": "string"}], "name": "LLMRequestFired", "type": "event"},
        {"anonymous": False, "inputs": [{"indexed": True, "name": "requestId", "type": "uint256"}, {"indexed": False, "name": "agentId", "type": "string"}, {"indexed": False, "name": "decision", "type": "string"}, {"indexed": False, "name": "price", "type": "uint256"}, {"indexed": False, "name": "orderId", "type": "uint256"}, {"indexed": False, "name": "streak", "type": "uint256"}], "name": "DecisionExecuted", "type": "event"},
        {"anonymous": False, "inputs": [{"indexed": True, "name": "requestId", "type": "uint256"}, {"indexed": False, "name": "agentId", "type": "string"}, {"indexed": False, "name": "reason", "type": "string"}], "name": "DecisionFailed", "type": "event"},
        {"anonymous": False, "inputs": [{"indexed": False, "name": "agentId", "type": "string"}, {"indexed": False, "name": "reason", "type": "string"}, {"indexed": False, "name": "balance", "type": "uint256"}], "name": "LoopStopped", "type": "event"},
        {"anonymous": False, "inputs": [{"indexed": False, "name": "direction", "type": "string"}, {"indexed": False, "name": "agentCount", "type": "uint256"}, {"indexed": False, "name": "price", "type": "uint256"}, {"indexed": False, "name": "orderId", "type": "uint256"}], "name": "CoalitionFormed", "type": "event"},
    ]


_load_abis()


class ExchangeContract:
    def __init__(self, address: str, rpc_url: str):
        self.address = address
        self.rpc_url = rpc_url
        w3 = get_web3(rpc_url)
        self._contract = w3.eth.contract(
            address=Web3.to_checksum_address(address),
            abi=_ABIS.get("Exchange", []),
        )

    async def place_order(self, agent_pk: str, is_buy: bool, price: float, amount: float) -> dict:
        price_wei = int(price * 1e18)
        amount_wei = int(amount * 1e18)
        data = self._contract.encode_abi("placeOrder", args=[is_buy, price_wei, amount_wei])
        tx_hash = await send_transaction(agent_pk, self.address, bytes.fromhex(data[2:]), rpc_url=self.rpc_url)
        return {"tx_hash": tx_hash, "price": price, "amount": amount, "is_buy": is_buy}

    async def cancel_order(self, agent_pk: str, order_id: int) -> dict:
        data = self._contract.encode_abi("cancelOrder", args=[order_id])
        tx_hash = await send_transaction(agent_pk, self.address, bytes.fromhex(data[2:]), rpc_url=self.rpc_url)
        return {"tx_hash": tx_hash, "order_id": order_id}

    async def get_active_orders(self) -> list[int]:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: self._contract.functions.getActiveOrders().call()
        )
        return [int(o) for o in result]

    async def get_best_bid(self) -> tuple[float, bool]:
        """Returns (price_float, exists). Price is 0.0 if no bids."""
        loop = asyncio.get_running_loop()
        try:
            price_wei, exists = await loop.run_in_executor(
                None, lambda: self._contract.functions.getBestBid().call()
            )
            return (float(Web3.from_wei(price_wei, "ether")), exists)
        except Exception as e:
            logger.debug(f"getBestBid failed: {e}")
            return (0.0, False)

    async def get_best_ask(self) -> tuple[float, bool]:
        """Returns (price_float, exists). Price is 0.0 if no asks."""
        loop = asyncio.get_running_loop()
        try:
            price_wei, exists = await loop.run_in_executor(
                None, lambda: self._contract.functions.getBestAsk().call()
            )
            return (float(Web3.from_wei(price_wei, "ether")), exists)
        except Exception as e:
            logger.debug(f"getBestAsk failed: {e}")
            return (0.0, False)

    async def get_last_trade_price(self) -> float:
        """Returns last matched trade price as float, or 0.0 if no trades yet."""
        loop = asyncio.get_running_loop()
        try:
            price_wei = await loop.run_in_executor(
                None, lambda: self._contract.functions.getLastTradePrice().call()
            )
            return float(Web3.from_wei(price_wei, "ether"))
        except Exception as e:
            logger.debug(f"getLastTradePrice failed: {e}")
            return 0.0

    async def has_traded(self) -> bool:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None, lambda: self._contract.functions.hasTraded().call()
            )
        except Exception:
            return False

    async def get_order_book(self, n: int = 10) -> dict:
        """Returns real on-chain order book: top N bid/ask price levels from active orders."""
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

            buy_orders = await asyncio.gather(*[fetch_order(oid) for oid in buy_ids])
            sell_orders = await asyncio.gather(*[fetch_order(oid) for oid in sell_ids])

            def aggregate(raw_orders, is_buy: bool) -> list[dict]:
                levels: dict[float, float] = {}
                for o in raw_orders:
                    # tuple: (id, agent, isBuy, price, amount, filled, timestamp, active)
                    if not o[7]:  # active flag
                        continue
                    price = round(float(Web3.from_wei(o[3], "ether")), 4)
                    remaining = float(Web3.from_wei(o[4] - o[5], "ether"))
                    levels[price] = levels.get(price, 0.0) + remaining
                sorted_prices = sorted(levels.keys(), reverse=is_buy)[:n]
                return [{"price": p, "amount": round(levels[p], 4)} for p in sorted_prices]

            return {
                "bids": aggregate(buy_orders, True),
                "asks": aggregate(sell_orders, False),
            }
        except Exception as e:
            logger.debug(f"get_order_book failed: {e}")
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
            logger.debug(f"get_order_book_depth failed: {e}")
            return {"buy_count": 0, "sell_count": 0}

    async def get_order_placed_events(self, from_block: int) -> list[dict]:
        loop = asyncio.get_running_loop()
        try:
            events = await loop.run_in_executor(
                None,
                lambda: self._contract.events.OrderPlaced.get_logs(
                    from_block=from_block, to_block="latest"
                ),
            )
            return [
                {
                    "agent": e["args"]["agent"],
                    "order_id": int(e["args"]["orderId"]),
                    "is_buy": e["args"]["isBuy"],
                    "price": float(Web3.from_wei(e["args"]["price"], "ether")),
                    "amount": float(Web3.from_wei(e["args"]["amount"], "ether")),
                    "block": e["blockNumber"],
                }
                for e in events
            ]
        except Exception as e:
            logger.debug(f"OrderPlaced event poll failed: {e}")
            return []

    async def get_recent_trade_events(self, from_block: int, to_block: str = "latest") -> list[dict]:
        """Poll TradeExecuted events — includes buyer/seller addresses and order IDs for P&L attribution."""
        loop = asyncio.get_running_loop()
        try:
            events = await loop.run_in_executor(
                None,
                lambda: self._contract.events.TradeExecuted.get_logs(
                    from_block=from_block, to_block=to_block
                ),
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
        except Exception as e:
            logger.debug(f"TradeExecuted event poll failed: {e}")
            return []


class TreasuryContract:
    def __init__(self, address: str, rpc_url: str):
        self.address = address
        self.rpc_url = rpc_url
        w3 = get_web3(rpc_url)
        self._contract = w3.eth.contract(
            address=Web3.to_checksum_address(address),
            abi=_ABIS.get("Treasury", []),
        )

    async def get_balance(self, agent_address: str) -> float:
        try:
            loop = asyncio.get_running_loop()
            balance_wei = await loop.run_in_executor(
                None,
                lambda: self._contract.functions.getBalance(
                    Web3.to_checksum_address(agent_address)
                ).call(),
            )
            return float(Web3.from_wei(balance_wei, "ether"))
        except Exception as e:
            logger.warning(f"Treasury.getBalance failed: {e}")
            return 0.0

    async def get_total_locked(self) -> float:
        loop = asyncio.get_running_loop()
        try:
            balance_wei = await loop.run_in_executor(
                None, lambda: self._contract.functions.totalLocked().call()
            )
            return float(Web3.from_wei(balance_wei, "ether"))
        except Exception as e:
            logger.debug(f"Treasury.totalLocked failed: {e}")
            return 0.0


class AgentRegistryContract:
    """On-chain agent discovery and reputation tracking."""

    def __init__(self, address: str, rpc_url: str):
        self.address = address
        self.rpc_url = rpc_url
        w3 = get_web3(rpc_url)
        self._contract = w3.eth.contract(
            address=Web3.to_checksum_address(address),
            abi=_ABIS.get("AgentRegistry", []),
        )

    async def get_all_agents(self) -> list[str]:
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None, lambda: self._contract.functions.getAllAgents().call()
            )
            return [str(a) for a in result]
        except Exception as e:
            logger.debug(f"AgentRegistry.getAllAgents failed: {e}")
            return []

    async def get_agent(self, agent_address: str) -> dict:
        loop = asyncio.get_running_loop()
        try:
            raw = await loop.run_in_executor(
                None,
                lambda: self._contract.functions.getAgent(
                    Web3.to_checksum_address(agent_address)
                ).call(),
            )
            # tuple: (wallet, name, strategy, reputation, tradesExecuted, registeredAt, active)
            return {
                "wallet":         raw[0],
                "name":           raw[1],
                "strategy":       raw[2],
                "reputation":     raw[3],
                "tradesExecuted": raw[4],
                "registeredAt":   raw[5],
                "active":         raw[6],
            }
        except Exception as e:
            logger.debug(f"AgentRegistry.getAgent({agent_address}) failed: {e}")
            return {}

    async def increment_trades(self, deployer_pk: str, agent_address: str) -> None:
        try:
            data = self._contract.encode_abi(
                "incrementTrades", args=[Web3.to_checksum_address(agent_address)]
            )
            await send_transaction(deployer_pk, self.address, bytes.fromhex(data[2:]), rpc_url=self.rpc_url)
        except Exception as e:
            logger.debug(f"AgentRegistry.incrementTrades failed: {e}")

    async def update_reputation(self, deployer_pk: str, agent_address: str, delta: int) -> None:
        try:
            data = self._contract.encode_abi(
                "updateReputation", args=[Web3.to_checksum_address(agent_address), delta]
            )
            await send_transaction(deployer_pk, self.address, bytes.fromhex(data[2:]), rpc_url=self.rpc_url)
        except Exception as e:
            logger.debug(f"AgentRegistry.updateReputation failed: {e}")


class AgentCoordinatorContract:
    """
    Two-step autonomous agent pipeline:
      1. trigger_decision() → JSON API agent fetches real ETH price on-chain
      2. handlePriceData() callback → builds context → LLM Inference agent decides
      3. handleDecision() callback → validator consensus → Exchange.placeOrder()
    Python passes NO market data — everything is sourced on-chain.
    """

    def __init__(self, address: str, rpc_url: str):
        self.address = address
        self.rpc_url = rpc_url
        w3 = get_web3(rpc_url)
        self._contract = w3.eth.contract(
            address=Web3.to_checksum_address(address),
            abi=_ABIS.get("AgentCoordinator", []),
        )

    async def trigger_decision(self, agent_pk: str, agent_id: str) -> dict:
        """
        Calls AgentCoordinator.triggerAgentDecision(agentId).
        Fires the JSON API price fetch — the first step of the two-step on-chain chain.
        Returns immediately with tx_hash. Order placement is fully asynchronous.
        """
        data = self._contract.encode_abi("triggerAgentDecision", args=[agent_id])
        tx_hash = await send_transaction(
            agent_pk, self.address, bytes.fromhex(data[2:]), rpc_url=self.rpc_url
        )
        return {"tx_hash": tx_hash, "agent_id": agent_id}

    async def trigger_with_price(self, agent_pk: str, agent_id: str, price: int) -> dict:
        """
        Calls AgentCoordinator.triggerWithPrice(agentId, rawPrice).
        Backend supplies a live ETH/USD price (whole USD integer), skipping the
        Somnia JSON API agent step. Requires the deployer (owner) private key.
        """
        data = self._contract.encode_abi("triggerWithPrice", args=[agent_id, price])
        tx_hash = await send_transaction(
            agent_pk, self.address, bytes.fromhex(data[2:]), rpc_url=self.rpc_url
        )
        return {"tx_hash": tx_hash, "agent_id": agent_id, "price": price}

    async def get_balance(self) -> float:
        loop = asyncio.get_running_loop()
        try:
            balance_wei = await loop.run_in_executor(
                None, lambda: self._contract.functions.getBalance().call()
            )
            return float(Web3.from_wei(balance_wei, "ether"))
        except Exception as e:
            logger.debug(f"AgentCoordinator.getBalance failed: {e}")
            return 0.0

    async def get_win_streak(self, agent_id: str) -> int:
        """Returns the current consecutive-win streak for an agent."""
        loop = asyncio.get_running_loop()
        try:
            return int(await loop.run_in_executor(
                None, lambda: self._contract.functions.winStreak(agent_id).call()
            ))
        except Exception as e:
            logger.debug(f"AgentCoordinator.winStreak({agent_id}) failed: {e}")
            return 0

    async def get_last_decision(self, agent_id: str) -> str:
        """Returns the last recorded on-chain decision (BUY/SELL/HOLD) for an agent."""
        loop = asyncio.get_running_loop()
        try:
            return str(await loop.run_in_executor(
                None, lambda: self._contract.functions.lastDecision(agent_id).call()
            ))
        except Exception as e:
            logger.debug(f"AgentCoordinator.lastDecision({agent_id}) failed: {e}")
            return ""

    async def get_coordinator_events(self, from_block: int) -> list[dict]:
        """Poll all coordinator events in one pass. Returns events sorted by block."""
        loop = asyncio.get_running_loop()
        results = []

        event_types = [
            ("DecisionTriggered", self._contract.events.DecisionTriggered),
            ("DecisionExecuted",  self._contract.events.DecisionExecuted),
            ("DecisionFailed",    self._contract.events.DecisionFailed),
            ("LoopStopped",       self._contract.events.LoopStopped),
            ("LLMRequestFired",   self._contract.events.LLMRequestFired),
            ("CoalitionFormed",   self._contract.events.CoalitionFormed),
        ]

        for name, event_cls in event_types:
            try:
                events = await loop.run_in_executor(
                    None,
                    lambda ec=event_cls: ec.get_logs(from_block=from_block, to_block="latest"),
                )
                for e in events:
                    entry = {"event": name, "block": e["blockNumber"]}
                    entry.update(dict(e["args"]))
                    results.append(entry)
            except Exception as e:
                logger.debug(f"{name} event poll failed: {e}")

        results.sort(key=lambda x: x["block"])
        return results
