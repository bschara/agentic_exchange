import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

from web3 import Web3
from eth_account import Account

from blockchain.client import get_web3, send_transaction, GAS_PRICE

logger = logging.getLogger(__name__)

# Load ABIs from compiled artifacts or deployment file
_ABIS: dict = {}


def _load_abis():
    global _ABIS
    # Try deployments file first
    deploy_path = Path(__file__).parent.parent.parent / "contracts" / "deployments" / "somnia-testnet.json"
    if deploy_path.exists():
        with open(deploy_path) as f:
            data = json.load(f)
        _ABIS = data.get("abis", {})
        return

    # Minimal ABI fallback (just what agents need)
    _ABIS["Exchange"] = [
        {"inputs": [{"name": "isBuy", "type": "bool"}, {"name": "price", "type": "uint256"}, {"name": "amount", "type": "uint256"}], "name": "placeOrder", "outputs": [{"name": "orderId", "type": "uint256"}], "stateMutability": "nonpayable", "type": "function"},
        {"inputs": [{"name": "orderId", "type": "uint256"}], "name": "cancelOrder", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
        {"inputs": [{"name": "buyOrderId", "type": "uint256"}, {"name": "sellOrderId", "type": "uint256"}], "name": "executeTrade", "outputs": [{"name": "tradeId", "type": "uint256"}], "stateMutability": "nonpayable", "type": "function"},
        {"inputs": [], "name": "getActiveOrders", "outputs": [{"name": "", "type": "uint256[]"}], "stateMutability": "view", "type": "function"},
    ]
    _ABIS["Treasury"] = [
        {"inputs": [], "name": "deposit", "outputs": [], "stateMutability": "payable", "type": "function"},
        {"inputs": [{"name": "agent", "type": "address"}], "name": "getBalance", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    ]
    _ABIS["AgentRegistry"] = [
        {"inputs": [{"name": "agent", "type": "address"}], "name": "getAgent", "outputs": [{"components": [{"name": "wallet", "type": "address"}, {"name": "name", "type": "string"}, {"name": "strategy", "type": "string"}, {"name": "reputation", "type": "int256"}, {"name": "tradesExecuted", "type": "uint256"}, {"name": "registeredAt", "type": "uint256"}, {"name": "active", "type": "bool"}], "name": "", "type": "tuple"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "getAllAgents", "outputs": [{"name": "", "type": "address[]"}], "stateMutability": "view", "type": "function"},
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

    async def execute_trade(self, agent_pk: str, buy_order_id: int, sell_order_id: int) -> dict:
        data = self._contract.encode_abi("executeTrade", args=[buy_order_id, sell_order_id])
        tx_hash = await send_transaction(agent_pk, self.address, bytes.fromhex(data[2:]), rpc_url=self.rpc_url)
        return {"tx_hash": tx_hash, "buy_order_id": buy_order_id, "sell_order_id": sell_order_id}

    async def get_active_orders(self) -> list[int]:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: self._contract.functions.getActiveOrders().call()
        )
        return [int(o) for o in result]


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
