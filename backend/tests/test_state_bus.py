import pytest
from unittest.mock import patch
from market.price_engine import ChainPriceTracker
from market.state_bus import MarketStateBus


# Patch both time references in one context: price_engine for OHLCV, state_bus for timestamps
def _patch_time(t):
    class _Ctx:
        def __enter__(self):
            self._p1 = patch("market.price_engine.time.time", return_value=float(t))
            self._p2 = patch("market.state_bus.time.time",   return_value=float(t))
            self._p1.__enter__()
            self._p2.__enter__()
            return self
        def __exit__(self, *a):
            self._p1.__exit__(*a)
            self._p2.__exit__(*a)
    return _Ctx()


@pytest.fixture
def tracker():
    return ChainPriceTracker(initial_price=3500.0)

@pytest.fixture
def bus(tracker):
    return MarketStateBus(tracker)


class TestRecordFill:
    async def test_increments_trade_counter(self, bus):
        with _patch_time(100):
            await bus.record_fill(3500.0, 1.0)
            await bus.record_fill(3600.0, 0.5)
        assert bus._trade_counter == 2

    async def test_appends_to_recent_trades_most_recent_first(self, bus):
        with _patch_time(100):
            await bus.record_fill(3500.0, 1.0, buyer_agent="alpha", seller_agent="beta")
            await bus.record_fill(3600.0, 0.5)
        trades = list(bus._recent_trades)
        assert trades[0].price == 3600.0   # most recent first (appendleft)
        assert trades[1].buyer_agent == "alpha"

    async def test_accumulates_volume_24h(self, bus):
        with _patch_time(100):
            await bus.record_fill(100.0, 2.0)   # 100 * 2 = 200
            await bus.record_fill(200.0, 1.0)   # 200 * 1 = 200
        assert bus._volume_24h == pytest.approx(400.0)

    async def test_returns_completed_bar_when_window_closes(self, bus):
        with _patch_time(100):
            await bus.record_fill(3500.0, 1.0)
        with _patch_time(105):
            bar = await bus.record_fill(3600.0, 2.0)
        assert bar is not None
        assert bar["open"] == 3500.0

    async def test_returns_none_within_same_window(self, bus):
        with _patch_time(100):
            r1 = await bus.record_fill(3500.0, 1.0)
            r2 = await bus.record_fill(3510.0, 0.5)
        assert r1 is None
        assert r2 is None

    async def test_updates_tracker_price(self, bus, tracker):
        with _patch_time(100):
            await bus.record_fill(3700.0, 1.0)
        assert tracker.price == 3700.0


class TestGetSnapshot:
    async def test_returns_expected_keys(self, bus):
        with _patch_time(100):
            snapshot = await bus.get_snapshot()
        assert {"price", "bid", "ask", "spread_pct", "volume_24h",
                "price_change_24h_pct", "order_book", "recent_trades"} <= snapshot.keys()

    async def test_price_reflects_latest_fill(self, bus):
        with _patch_time(100):
            await bus.record_fill(3600.0, 1.0)
            snapshot = await bus.get_snapshot()
        assert snapshot["price"] == 3600.0

    async def test_fallback_bid_ask_when_order_book_empty(self, bus):
        with _patch_time(100):
            snapshot = await bus.get_snapshot()
        assert snapshot["bid"] == round(3500.0 * 0.999, 4)
        assert snapshot["ask"] == round(3500.0 * 1.001, 4)

    async def test_bid_ask_from_order_book_when_populated(self, bus):
        bus.set_order_book(
            bids=[{"price": 3490.0, "amount": 1.0}],
            asks=[{"price": 3510.0, "amount": 1.0}],
        )
        with _patch_time(100):
            snapshot = await bus.get_snapshot()
        assert snapshot["bid"] == 3490.0
        assert snapshot["ask"] == 3510.0

    async def test_price_change_24h_pct(self, bus):
        with _patch_time(100):
            await bus.record_fill(3535.0, 1.0)
            snapshot = await bus.get_snapshot()
        expected = round((3535.0 - 3500.0) / 3500.0 * 100, 4)
        assert snapshot["price_change_24h_pct"] == expected

    async def test_recent_trades_included_in_snapshot(self, bus):
        with _patch_time(100):
            await bus.record_fill(3500.0, 1.0, buyer_agent="alpha")
            snapshot = await bus.get_snapshot()
        assert len(snapshot["recent_trades"]) == 1
        assert snapshot["recent_trades"][0]["buyer_agent"] == "alpha"


class TestGetMarketContext:
    async def test_context_contains_price_line(self, bus):
        with _patch_time(100):
            ctx = await bus.get_market_context("alpha")
        assert "Current price: $3500" in ctx

    async def test_context_flat_trend_with_no_history(self, bus):
        with _patch_time(100):
            ctx = await bus.get_market_context("alpha")
        assert "5-bar trend: FLAT" in ctx

    async def test_context_up_trend(self, bus):
        # Build 3 completed bars with rising closes: 100, 110, 120
        for i in range(4):
            with _patch_time(100 + i * 5):
                await bus.record_fill(float(100 + i * 10), 1.0)
        with _patch_time(120):
            ctx = await bus.get_market_context("alpha")
        assert "5-bar trend: UP" in ctx

    async def test_context_includes_warnings(self, bus):
        await bus.set_agent_warning("alpha", "high volatility detected")
        with _patch_time(100):
            ctx = await bus.get_market_context("alpha")
        assert "high volatility detected" in ctx

    async def test_context_includes_injected_events(self, bus):
        with _patch_time(100):
            await bus.inject_event("whale_buy", {"size": 100})
            ctx = await bus.get_market_context("alpha")
        assert "whale_buy" in ctx

    async def test_context_no_warnings_when_none_set(self, bus):
        with _patch_time(100):
            ctx = await bus.get_market_context("alpha")
        assert "Active warnings: none" in ctx


class TestWarnings:
    async def test_set_and_get_warning(self, bus):
        await bus.set_agent_warning("alpha", "spread too wide")
        warnings = await bus.get_active_warnings()
        assert "spread too wide" in warnings

    async def test_clear_warning(self, bus):
        await bus.set_agent_warning("alpha", "spread too wide")
        await bus.clear_agent_warning("alpha")
        assert await bus.get_active_warnings() == []

    async def test_clear_nonexistent_warning_is_silent(self, bus):
        await bus.clear_agent_warning("nobody")

    async def test_multiple_agents_warnings(self, bus):
        await bus.set_agent_warning("alpha", "msg1")
        await bus.set_agent_warning("beta",  "msg2")
        warnings = await bus.get_active_warnings()
        assert len(warnings) == 2


class TestInjectEvent:
    async def test_inject_event_stored(self, bus):
        with _patch_time(100):
            await bus.inject_event("whale_buy", {"size": 50})
        events = list(bus._injected_events)
        assert len(events) == 1
        assert events[0]["type"] == "whale_buy"
        assert events[0]["params"] == {"size": 50}

    async def test_get_injected_events_clears_queue(self, bus):
        with _patch_time(100):
            await bus.inject_event("volatility_spike", {})
        events = await bus.get_injected_events()
        assert len(events) == 1
        assert await bus.get_injected_events() == []

    async def test_injected_events_capped_at_10(self, bus):
        with _patch_time(100):
            for i in range(15):
                await bus.inject_event(f"event_{i}", {})
        assert len(bus._injected_events) == 10


class TestSetOrderBook:
    def test_rebuilds_order_book_from_dicts(self, bus):
        bus.set_order_book(
            bids=[{"price": 3490.0, "amount": 1.5}, {"price": 3480.0, "amount": 2.0}],
            asks=[{"price": 3510.0, "amount": 1.0}],
        )
        assert bus._order_book.get_best_bid() == 3490.0
        assert bus._order_book.get_best_ask() == 3510.0

    def test_replaces_previous_order_book(self, bus):
        bus.set_order_book(
            bids=[{"price": 3490.0, "amount": 1.0}],
            asks=[{"price": 3510.0, "amount": 1.0}],
        )
        bus.set_order_book(
            bids=[{"price": 3450.0, "amount": 1.0}],
            asks=[],
        )
        assert bus._order_book.get_best_bid() == 3450.0
        assert bus._order_book.get_best_ask() is None

    def test_empty_bids_and_asks(self, bus):
        bus.set_order_book(bids=[], asks=[])
        assert bus._order_book.get_best_bid() is None
        assert bus._order_book.get_best_ask() is None
