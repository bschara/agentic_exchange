import asyncio
import logging
import re

logger = logging.getLogger(__name__)

_TOPUP_THRESHOLD = 1_000.0
_TOPUP_AMOUNT = 10_000_000.0
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
        agents: dict,
        chain_metrics: dict,
    ):
        self._quote_token = quote_token
        self._agent_token = agent_token
        self._deployer_pk = deployer_pk
        self._coordinator_address = coordinator_address
        self._agents = agents
        self._chain_metrics = chain_metrics

    async def run(self) -> None:
        while True:
            try:
                await self._poll_and_replenish()
            except Exception as e:
                logger.error(f"Token replenisher error: {e}")
            await asyncio.sleep(30.0)

    async def _poll_and_replenish(self) -> None:
        metrics = self._chain_metrics

        # ── AgentToken balances ─────────────────────────────────────────────
        if self._agent_token:
            coordinator_agt = 0.0
            if _is_address(self._coordinator_address):
                coordinator_agt = await self._agent_token.get_balance(self._coordinator_address)
            for agent in self._agents.values():
                agent_id = agent["agent_id"]
                agent_data = metrics.get("agents", {}).get(agent_id)
                if not agent_data:
                    continue
                if agent_id == "noise_trader" and _is_address(agent.get("wallet_address", "")):
                    agent_data["agt_balance"] = await self._agent_token.get_balance(
                        agent["wallet_address"]
                    )
                else:
                    agent_data["agt_balance"] = coordinator_agt

        # ── QuoteToken balances + auto-replenishment ────────────────────────
        if not self._quote_token:
            return

        coordinator_quote = 0.0
        if _is_address(self._coordinator_address):
            coordinator_quote = await self._quote_token.get_balance(self._coordinator_address)

        for agent in self._agents.values():
            agent_id = agent["agent_id"]
            agent_data = metrics.get("agents", {}).get(agent_id)
            if not agent_data:
                continue
            if agent_id == "noise_trader" and _is_address(agent.get("wallet_address", "")):
                bal = await self._quote_token.get_balance(agent["wallet_address"])
            else:
                bal = coordinator_quote
            agent_data["quote_balance"] = bal
            if agent_data.get("initial_quote_balance") is None and bal > 0:
                agent_data["initial_quote_balance"] = bal

        if coordinator_quote < _TOPUP_THRESHOLD and _is_address(self._coordinator_address):
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

        noise_wallet = self._agents.get("noise_trader", {}).get("wallet_address", "")
        if _is_address(noise_wallet):
            noise_quote = (
                metrics.get("agents", {}).get("noise_trader", {}).get("quote_balance", 0.0)
            )
            if noise_quote < _TOPUP_THRESHOLD:
                logger.warning(
                    f"Noise trader QUOTE low ({noise_quote:.2f}) — minting {_TOPUP_AMOUNT:.0f}"
                )
                try:
                    res = await self._quote_token.mint(
                        self._deployer_pk, noise_wallet, _TOPUP_AMOUNT
                    )
                    logger.info(f"Noise trader QUOTE top-up tx: {res.get('tx_hash', '')[:16]}")
                except Exception as e:
                    logger.error(f"Noise trader QUOTE top-up failed: {e}")
