import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from market.order_book import OrderBook
from market.price_engine import PriceEngine


@dataclass
class RecentTrade:
    id: int
    price: float
    amount: float
    side: str
    timestamp: int


class MarketStateBus:
    def __init__(self, price_engine: PriceEngine):
        self._engine = price_engine
        self._lock = asyncio.Lock()
        self._order_book = OrderBook()
        self._recent_trades: deque = deque(maxlen=50)
        self._trade_counter = 0
        self._agent_warnings: dict[str, str] = {}
        self._injected_events: deque = deque(maxlen=10)
        self._volume_24h = 0.0
        self._price_open_24h = price_engine.price

    async def get_snapshot(self) -> dict:
        async with self._lock:
            price = self._engine.price
            depth = self._order_book.get_depth(10)
            bid = depth["bids"][0]["price"] if depth["bids"] else price * 0.999
            ask = depth["asks"][0]["price"] if depth["asks"] else price * 1.001
            spread_pct = self._order_book.get_spread() or round((ask - bid) / price * 100, 4)
            price_change = ((price - self._price_open_24h) / self._price_open_24h * 100) if self._price_open_24h else 0

            return {
                "price": round(price, 4),
                "bid": round(bid, 4),
                "ask": round(ask, 4),
                "spread_pct": round(spread_pct, 4),
                "volume_24h": round(self._volume_24h, 2),
                "price_change_24h_pct": round(price_change, 4),
                "order_book": depth,
                "recent_trades": [
                    {"id": t.id, "price": t.price, "amount": t.amount, "side": t.side, "timestamp": t.timestamp}
                    for t in list(self._recent_trades)
                ],
            }

    async def get_market_context(self, agent_id: str) -> str:
        async with self._lock:
            price = self._engine.price
            closes = self._engine.get_recent_closes(10)
            if len(closes) >= 2:
                trend = "UP" if closes[-1] > closes[0] else "DOWN" if closes[-1] < closes[0] else "FLAT"
            else:
                trend = "FLAT"

            import numpy as np
            if len(closes) >= 5:
                returns = [math.log(closes[i] / closes[i-1]) for i in range(1, len(closes))]
                vol = float(np.std(returns) * 100) if returns else 0.0
            else:
                vol = 0.0

            depth = self._order_book.get_depth(5)
            spread = self._order_book.get_spread()
            warnings = list(self._agent_warnings.values())
            events = list(self._injected_events)

            lines = [
                f"Current price: ${price:.4f}",
                f"5-bar trend: {trend}",
                f"Volatility: {vol:.2f}%",
                f"Bid-ask spread: {spread:.3f}%",
                f"Best bid: ${depth['bids'][0]['price'] if depth['bids'] else 'N/A'}",
                f"Best ask: ${depth['asks'][0]['price'] if depth['asks'] else 'N/A'}",
                f"Active warnings: {'; '.join(warnings) if warnings else 'none'}",
                f"Recent events: {'; '.join(e.get('type','') for e in events) if events else 'none'}",
                f"Volume 24h: ${self._volume_24h:.2f}",
            ]
            return "\n".join(lines)

    async def update_price(self, new_price: float):
        async with self._lock:
            pass  # Price is tracked directly in engine

    async def add_trade(self, trade: dict):
        async with self._lock:
            self._trade_counter += 1
            self._recent_trades.appendleft(RecentTrade(
                id=self._trade_counter,
                price=trade["price"],
                amount=trade["amount"],
                side=trade["side"],
                timestamp=int(time.time()),
            ))
            self._volume_24h += trade["price"] * trade["amount"]

    async def inject_event(self, event_type: str, params: dict):
        async with self._lock:
            self._injected_events.append({"type": event_type, "params": params, "time": time.time()})

    async def set_agent_warning(self, agent_id: str, message: str):
        async with self._lock:
            self._agent_warnings[agent_id] = message

    async def clear_agent_warning(self, agent_id: str):
        async with self._lock:
            self._agent_warnings.pop(agent_id, None)

    async def get_active_warnings(self) -> list[str]:
        async with self._lock:
            return list(self._agent_warnings.values())

    async def get_injected_events(self) -> list[dict]:
        async with self._lock:
            events = list(self._injected_events)
            self._injected_events.clear()
            return events

    def add_order_to_book(self, order_id: int, is_buy: bool, price: float, size: float, agent: str):
        self._order_book.add_order(order_id, is_buy, price, size, agent)

    def remove_order_from_book(self, order_id: int):
        self._order_book.remove_order(order_id)

    def synthesize_order_book(self, mid_price: float):
        """Generate synthetic order book depth around mid price for display."""
        self._order_book = OrderBook()
        for i in range(1, 11):
            bid_price = mid_price * (1 - 0.001 * i)
            ask_price = mid_price * (1 + 0.001 * i)
            import random
            size = 0.5 + random.random() * 3
            self._order_book.add_order(-i, True, round(bid_price, 4), round(size, 4), "market")
            self._order_book.add_order(-100 - i, False, round(ask_price, 4), round(size, 4), "market")


import math
