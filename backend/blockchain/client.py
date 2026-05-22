import asyncio
import logging
from typing import Optional

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account
from config import settings

logger = logging.getLogger(__name__)

_web3: Optional[Web3] = None
_wallet_locks: dict[str, asyncio.Lock] = {}
_nonces: dict[str, int] = {}

GAS_PRICE = 6_000_000_000  # 6 gwei hardcoded for Somnia


def get_web3(rpc_url: str = "https://dream-rpc.somnia.network") -> Web3:
    global _web3
    if _web3 is None:
        _web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        _web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        logger.info(f"Web3 connected: {_web3.is_connected()}")
    return _web3


def get_wallet_lock(address: str) -> asyncio.Lock:
    if address not in _wallet_locks:
        _wallet_locks[address] = asyncio.Lock()
    return _wallet_locks[address]


async def send_transaction(
    private_key: str,
    to: str,
    data: bytes,
    value: int = 0,
    rpc_url: str = "https://dream-rpc.somnia.network",
) -> str:
    w3 = get_web3(rpc_url)
    account = Account.from_key(private_key)
    address = account.address
    lock = get_wallet_lock(address)

    async with lock:
        try:
            if address not in _nonces:
                _nonces[address] = w3.eth.get_transaction_count(address, "pending")

            tx = {
                "from": address,
                "to": Web3.to_checksum_address(to),
                "data": data,
                "value": value,
                "gas": 500_000,
                "gasPrice": GAS_PRICE,
                "nonce": _nonces[address],
                "chainId": settings.somnia_chain_id,
            }

            signed = w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            _nonces[address] += 1

            # Wait for receipt with 30s timeout
            loop = asyncio.get_running_loop()
            receipt = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30),
                ),
                timeout=35,
            )
            logger.info(f"Tx confirmed: {tx_hash.hex()} block={receipt.blockNumber}")
            return tx_hash.hex()

        except asyncio.TimeoutError:
            logger.warning(f"Tx timeout for {address}, continuing agent loop")
            return ""
        except Exception as e:
            logger.error(f"Tx failed for {address}: {e}")
            # Refresh nonce on failure
            try:
                _nonces[address] = w3.eth.get_transaction_count(address, "pending")
            except Exception:
                pass
            raise


def load_contract(w3: Web3, address: str, abi: list):
    return w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)


async def get_eth_balance(address: str, rpc_url: str = "https://dream-rpc.somnia.network") -> float:
    w3 = get_web3(rpc_url)
    loop = asyncio.get_running_loop()
    balance_wei = await loop.run_in_executor(
        None, lambda: w3.eth.get_balance(Web3.to_checksum_address(address))
    )
    return float(Web3.from_wei(balance_wei, "ether"))
