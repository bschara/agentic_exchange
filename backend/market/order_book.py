from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BookEntry:
    order_id: int
    price: float
    size: float
    agent: str
    is_buy: bool


class OrderBook:
    def __init__(self):
        self._bids: dict[int, BookEntry] = {}
        self._asks: dict[int, BookEntry] = {}

    def add_order(self, order_id: int, is_buy: bool, price: float, size: float, agent: str):
        entry = BookEntry(order_id=order_id, price=price, size=size, agent=agent, is_buy=is_buy)
        if is_buy:
            self._bids[order_id] = entry
        else:
            self._asks[order_id] = entry

    def remove_order(self, order_id: int):
        self._bids.pop(order_id, None)
        self._asks.pop(order_id, None)

    def get_best_bid(self) -> Optional[float]:
        if not self._bids:
            return None
        return max(e.price for e in self._bids.values())

    def get_best_ask(self) -> Optional[float]:
        if not self._asks:
            return None
        return min(e.price for e in self._asks.values())

    def get_mid_price(self) -> Optional[float]:
        bid = self.get_best_bid()
        ask = self.get_best_ask()
        if bid and ask:
            return (bid + ask) / 2
        return None

    def get_spread(self) -> float:
        bid = self.get_best_bid()
        ask = self.get_best_ask()
        if bid and ask and bid > 0:
            return (ask - bid) / bid * 100
        return 0.0

    def get_depth(self, levels: int = 10) -> dict:
        sorted_bids = sorted(self._bids.values(), key=lambda e: e.price, reverse=True)
        sorted_asks = sorted(self._asks.values(), key=lambda e: e.price)

        bids = [{"price": round(e.price, 4), "size": round(e.size, 4)} for e in sorted_bids[:levels]]
        asks = [{"price": round(e.price, 4), "size": round(e.size, 4)} for e in sorted_asks[:levels]]

        return {"bids": bids, "asks": asks}
