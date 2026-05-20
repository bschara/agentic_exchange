import math
import random
import time
from collections import deque
from dataclasses import dataclass, field
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


class PriceEngine:
    def __init__(self, initial_price: float, volatility: float, drift: float):
        self.price = initial_price
        self.volatility = volatility
        self.drift = drift
        self._vol_multiplier = 1.0
        self._vol_multiplier_until = 0.0
        self._ohlcv = OHLCVBuilder(bar_seconds=5)
        self.history: deque = deque(maxlen=500)
        # Set to True once on-chain trades are available — price anchors to chain
        self.using_chain_price: bool = False

    def next_price(self) -> float:
        vol = self.volatility * self._effective_multiplier()
        dt = 1.0
        z = random.gauss(0, 1)
        ret = (self.drift - 0.5 * vol ** 2) * dt + vol * math.sqrt(dt) * z
        self.price *= math.exp(ret)
        self.price = max(0.01, self.price)

        volume = abs(z) * 50 + 10
        completed = self._ohlcv.tick(self.price, volume)
        if completed:
            self.history.append({
                "time": completed.time,
                "open": round(completed.open, 4),
                "high": round(completed.high, 4),
                "low": round(completed.low, 4),
                "close": round(completed.close, 4),
                "volume": round(completed.volume, 2),
            })

        return self.price

    def get_completed_bar(self) -> Optional[dict]:
        if self.history:
            return self.history[-1]
        return None

    def get_current_bar(self) -> Optional[dict]:
        bar = self._ohlcv.current()
        if bar:
            return {
                "time": bar.time,
                "open": round(bar.open, 4),
                "high": round(bar.high, 4),
                "low": round(bar.low, 4),
                "close": round(bar.close, 4),
                "volume": round(bar.volume, 2),
            }
        return None

    def set_volatility_multiplier(self, multiplier: float, duration_seconds: float):
        self._vol_multiplier = multiplier
        self._vol_multiplier_until = time.time() + duration_seconds

    def apply_price_shock(self, pct_change: float):
        self.price *= (1 + pct_change)
        self.price = max(0.01, self.price)

    def _effective_multiplier(self) -> float:
        if time.time() < self._vol_multiplier_until:
            return self._vol_multiplier
        return 1.0

    def get_recent_closes(self, n: int = 20) -> list[float]:
        bars = list(self.history)
        return [b["close"] for b in bars[-n:]]

    def set_chain_price(self, chain_price: float):
        """
        Called by the orchestrator when a real TradeExecuted event is seen.
        Anchors GBM to the on-chain price so the simulation stays coherent
        with actual matched trades.
        """
        if chain_price > 0:
            self.price = chain_price
            self.using_chain_price = True
            # Tick the OHLCV builder so the candle reflects the real price
            self._ohlcv.tick(chain_price, 0)
