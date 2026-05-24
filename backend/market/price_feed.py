import logging

import httpx

logger = logging.getLogger(__name__)

_SOURCES = [
    (
        "coingecko",
        "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd",
        lambda d: int(d["ethereum"]["usd"]),
    ),
    (
        "binance",
        "https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT",
        lambda d: int(float(d["price"])),
    ),
]


async def fetch_eth_usd() -> int:
    """Fetch current ETH/USD price as a whole-USD integer (e.g. 3245).
    Tries CoinGecko first, falls back to Binance."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url, parse in _SOURCES:
            try:
                r = await client.get(url)
                r.raise_for_status()
                price = parse(r.json())
                logger.debug(f"ETH/USD from {name}: ${price}")
                return price
            except Exception as exc:
                logger.warning(f"Price source {name} failed: {exc}")
    raise RuntimeError("All price sources failed — cannot fetch ETH/USD")
