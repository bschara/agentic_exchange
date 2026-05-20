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
    deploy_path = Path(__file__).parent.parent.parent / "contracts" / "deployments" / "somnia-testnet.json"
    if deploy_path.exists():
        with open(deploy_path) as f:
            data = json.load(f)
        _ABIS = data.get("abis", {})
        return

    # Minimal ABI fallback — updated for real LOB + AgentCoordinator
    _ABIS["Exchange"] = [
        {"inputs": [{"name": "isBuy", "type": "bool"}, {"name": "price", "type": "uint256"}, {"name": "amount", "type": "uint256"}], "name": "placeOrder", "outputs": [{"name": "orderId", "type": "uint256"}], "stateMutability": "nonpayable", "type": "function"},
        {"inputs": [{"name": "orderId", "type": "uint256"}], "name": "cancelOrder", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
        {"inputs": [], "name": "getActiveOrders", "outputs": [{"name": "", "type": "uint256[]"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "getBestBid", "outputs": [{"name": "price", "type": "uint256"}, {"name": "exists", "type": "bool"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "getBestAsk", "outputs": [{"name": "price", "type": "uint256"}, {"name": "exists", "type": "bool"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "getLastTradePrice", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "hasTraded", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
        {"anonymous": False, "inputs": [{"indexed": True, "name": "tradeId", "type": "uint256"}, {"indexed": False, "name": "buyOrderId", "type": "uint256"}, {"indexed": False, "name": "sellOrderId", "type": "uint256"}, {"indexed": True, "name": "buyer", "type": "address"}, {"indexed": True, "name": "seller", "type": "address"}, {"indexed": False, "name": "price", "type": "uint256"}, {"indexed": False, "name": "amount", "type": "uint256"}], "name": "TradeExecuted", "type": "event"},
    ]
    _ABIS["Treasury"] = [
        {"inputs": [], "name": "deposit", "outputs": [], "stateMutability": "payable", "type": "function"},
        {"inputs": [{"name": "agent", "type": "address"}], "name": "getBalance", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    ]
    _ABIS["AgentRegistry"] = [
        {"inputs": [{"name": "agent", "type": "address"}], "name": "getAgent", "outputs": [{"components": [{"name": "wallet", "type": "address"}, {"name": "name", "type": "string"}, {"name": "strategy", "type": "string"}, {"name": "reputation", "type": "int256"}, {"name": "tradesExecuted", "type": "uint256"}, {"name": "registeredAt", "type": "uint256"}, {"name": "active", "type": "bool"}], "name": "", "type": "tuple"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "getAllAgents", "outputs": [{"name": "", "type": "address[]"}], "stateMutability": "view", "type": "function"},
    ]
    _ABIS["AgentCoordinator"] = [
        {"inputs": [{"name": "agentId", "type": "string"}], "name": "triggerAgentDecision", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
        {"inputs": [], "name": "getBalance", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
        {"anonymous": False, "inputs": [{"indexed": True, "name": "requestId", "type": "uint256"}, {"indexed": False, "name": "agentId", "type": "string"}], "name": "DecisionTriggered", "type": "event"},
        {"anonymous": False, "inputs": [{"indexed": True, "name": "llmRequestId", "type": "uint256"}, {"indexed": False, "name": "agentId", "type": "string"}, {"indexed": False, "name": "fetchedPrice", "type": "uint256"}], "name": "LLMRequestFired", "type": "event"},
        {"anonymous": False, "inputs": [{"indexed": True, "name": "requestId", "type": "uint256"}, {"indexed": False, "name": "agentId", "type": "string"}, {"indexed": False, "name": "decision", "type": "string"}, {"indexed": False, "name": "price", "type": "uint256"}, {"indexed": False, "name": "orderId", "type": "uint256"}], "name": "DecisionExecuted", "type": "event"},
        {"anonymous": False, "inputs": [{"indexed": True, "name": "requestId", "type": "uint256"}, {"indexed": False, "name": "agentId", "type": "string"}, {"indexed": False, "name": "reason", "type": "string"}], "name": "DecisionFailed", "type": "event"},
        {"anonymous": False, "inputs": [{"indexed": False, "name": "agentId", "type": "string"}, {"indexed": False, "name": "reason", "type": "string"}, {"indexed": False, "name": "balance", "type": "uint256"}], "name": "LoopStopped", "type": "event"},
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
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: self._contract.functions.getActiveOrders().call()
        )
        return [int(o) for o in result]

    async def get_best_bid(self) -> tuple[float, bool]:
        """Returns (price_float, exists). Price is 0.0 if no bids."""
        loop = asyncio.get_event_loop()
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
        loop = asyncio.get_event_loop()
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
        loop = asyncio.get_event_loop()
        try:
            price_wei = await loop.run_in_executor(
                None, lambda: self._contract.functions.getLastTradePrice().call()
            )
            return float(Web3.from_wei(price_wei, "ether"))
        except Exception as e:
            logger.debug(f"getLastTradePrice failed: {e}")
            return 0.0

    async def has_traded(self) -> bool:
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None, lambda: self._contract.functions.hasTraded().call()
            )
        except Exception:
            return False

    async def get_recent_trade_events(self, from_block: int, to_block: str = "latest") -> list[dict]:
        """Poll TradeExecuted events for on-chain price history."""
        loop = asyncio.get_event_loop()
        try:
            events = await loop.run_in_executor(
                None,
                lambda: self._contract.events.TradeExecuted.get_logs(
                    from_block=from_block, to_block=to_block
                ),
            )
            return [
                {
                    "price": float(Web3.from_wei(e["args"]["price"], "ether")),
                    "amount": float(Web3.from_wei(e["args"]["amount"], "ether")),
                    "block": e["blockNumber"],
                    "tx_hash": e["transactionHash"].hex(),
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
            loop = asyncio.get_event_loop()
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

    async def get_balance(self) -> float:
        loop = asyncio.get_event_loop()
        try:
            balance_wei = await loop.run_in_executor(
                None, lambda: self._contract.functions.getBalance().call()
            )
            return float(Web3.from_wei(balance_wei, "ether"))
        except Exception as e:
            logger.debug(f"AgentCoordinator.getBalance failed: {e}")
            return 0.0
