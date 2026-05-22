import time
from collections import deque
from dataclasses import dataclass
from typing import Optional


@dataclass
class OHLCVBar:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class OHLCVBuilder:
    def __init__(self, bar_seconds: int = 5):
        self.bar_seconds = bar_seconds
        self._current_bar: Optional[OHLCVBar] = None
        self._bar_start: Optional[int] = None

    def tick(self, price: float, volume: float = 0) -> Optional[OHLCVBar]:
        now = int(time.time())
        bar_ts = (now // self.bar_seconds) * self.bar_seconds

        if self._bar_start is None or bar_ts > self._bar_start:
            completed = self._current_bar if self._bar_start is not None and bar_ts > self._bar_start else None
            self._bar_start = bar_ts
            self._current_bar = OHLCVBar(
                time=bar_ts, open=price, high=price, low=price, close=price, volume=volume
            )
            return completed

        bar = self._current_bar
        bar.high = max(bar.high, price)
        bar.low = min(bar.low, price)
        bar.close = price
        bar.volume += volume
        return None

    def current(self) -> Optional[OHLCVBar]:
        return self._current_bar


class ChainPriceTracker:
    """
    Tracks price from real on-chain TradeExecuted events.
    No simulation — price only moves when a real fill arrives.
    """

    def __init__(self, initial_price: float):
        self.price = initial_price
        self._ohlcv = OHLCVBuilder(bar_seconds=5)
        self.history: deque = deque(maxlen=500)

    def record_fill(self, price: float, volume: float) -> Optional[dict]:
        """Feed a fill in. Returns the completed bar dict if a bar just closed."""
        self.price = price
        completed = self._ohlcv.tick(price, volume)
        if completed:
            bar = self._bar_to_dict(completed)
            self.history.append(bar)
            return bar
        return None

    def get_current_bar(self) -> Optional[dict]:
        bar = self._ohlcv.current()
        return self._bar_to_dict(bar) if bar else None

    def get_recent_closes(self, n: int = 20) -> list[float]:
        return [b["close"] for b in list(self.history)[-n:]]

    @staticmethod
    def _bar_to_dict(bar: OHLCVBar) -> dict:
        return {
            "time": bar.time,
            "open": round(bar.open, 4),
            "high": round(bar.high, 4),
            "low": round(bar.low, 4),
            "close": round(bar.close, 4),
            "volume": round(bar.volume, 2),
        }
