import asyncio
import logging
import re

logger = logging.getLogger(__name__)

_TOPUP_THRESHOLD = 1_000.0
_TOPUP_AMOUNT    = 10_000.0
_ZERO = "0x0000000000000000000000000000000000000000"


def _is_address(addr: str) -> bool:
    return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", addr)) and addr != _ZERO


class TokenReplenisher:
    """
    Polls QUOTE and AGT token balances every 30 s and auto-mints when balances
    fall below threshold. Runs independently of the 5 s metrics collector to
    reduce RPC call frequency.
    """

    def __init__(
        self,
        quote_token,
        agent_token,
        deployer_pk: str,
        coordinator_address: str,
    ):
        self._quote_token = quote_token
        self._agent_token = agent_token
        self._deployer_pk = deployer_pk
        self._coordinator_address = coordinator_address

    async def run(self) -> None:
        while True:
            try:
                await self._poll_and_replenish()
            except Exception as e:
                logger.error(f"Token replenisher error: {e}")
            await asyncio.sleep(30.0)

    async def _poll_and_replenish(self) -> None:
        # ── AgentToken (sETH) — top up coordinator pool when low ──────────────
        if self._agent_token and _is_address(self._coordinator_address):
            coordinator_agt = await self._agent_token.get_balance(self._coordinator_address)
            if coordinator_agt < _TOPUP_THRESHOLD:
                logger.warning(
                    f"Coordinator AGT low ({coordinator_agt:.2f}) — minting {_TOPUP_AMOUNT:.0f}"
                )
                try:
                    res = await self._agent_token.mint(
                        self._deployer_pk, self._coordinator_address, _TOPUP_AMOUNT
                    )
                    logger.info(f"Coordinator AGT top-up tx: {res.get('tx_hash', '')[:16]}")
                except Exception as e:
                    logger.error(f"Coordinator AGT top-up failed: {e}")

        # ── QuoteToken — top up coordinator pool when low ─────────────────────
        if self._quote_token and _is_address(self._coordinator_address):
            coordinator_quote = await self._quote_token.get_balance(self._coordinator_address)
            if coordinator_quote < _TOPUP_THRESHOLD:
                logger.warning(
                    f"Coordinator QUOTE low ({coordinator_quote:.2f}) — minting {_TOPUP_AMOUNT:.0f}"
                )
                try:
                    res = await self._quote_token.mint(
                        self._deployer_pk, self._coordinator_address, _TOPUP_AMOUNT
                    )
                    logger.info(f"Coordinator QUOTE top-up tx: {res.get('tx_hash', '')[:16]}")
                except Exception as e:
                    logger.error(f"Coordinator QUOTE top-up failed: {e}")
