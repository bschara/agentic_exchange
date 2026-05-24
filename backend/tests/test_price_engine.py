import pytest
from unittest.mock import patch
from market.price_engine import OHLCVBuilder, ChainPriceTracker


# Helpers to set time for a tick
def tick_at(builder, t, price, volume=0.0):
    with patch("market.price_engine.time.time", return_value=float(t)):
        return builder.tick(price, volume)

def fill_at(tracker, t, price, volume=1.0):
    with patch("market.price_engine.time.time", return_value=float(t)):
        return tracker.record_fill(price, volume)


class TestOHLCVBuilder:
    def test_first_tick_returns_none_and_opens_bar(self):
        builder = OHLCVBuilder(bar_seconds=5)
        result = tick_at(builder, 100, 3500.0, 1.0)
        assert result is None
        bar = builder.current()
        assert bar is not None
        assert bar.open == bar.high == bar.low == bar.close == 3500.0
        assert bar.volume == 1.0

    def test_tick_in_same_window_updates_ohlcv(self):
        builder = OHLCVBuilder(bar_seconds=5)
        tick_at(builder, 100, 100.0, 1.0)
        tick_at(builder, 101, 120.0, 2.0)  # same window (100–104)
        tick_at(builder, 102, 80.0,  0.5)
        bar = builder.current()
        assert bar.high   == 120.0
        assert bar.low    == 80.0
        assert bar.close  == 80.0
        assert bar.volume == pytest.approx(3.5)

    def test_tick_in_new_window_completes_previous_bar(self):
        builder = OHLCVBuilder(bar_seconds=5)
        tick_at(builder, 100, 3500.0, 1.0)
        tick_at(builder, 102, 3520.0, 0.5)
        completed = tick_at(builder, 105, 3600.0, 2.0)  # new window

        assert completed is not None
        assert completed.open  == 3500.0
        assert completed.high  == 3520.0
        assert completed.low   == 3500.0
        assert completed.close == 3520.0
        assert completed.volume == pytest.approx(1.5)

    def test_new_bar_starts_correctly_after_completion(self):
        builder = OHLCVBuilder(bar_seconds=5)
        tick_at(builder, 100, 3500.0)
        tick_at(builder, 105, 3600.0)
        bar = builder.current()
        assert bar.open == 3600.0
        assert bar.time == 105

    def test_current_returns_none_before_first_tick(self):
        assert OHLCVBuilder().current() is None

    def test_consecutive_bar_completions(self):
        builder = OHLCVBuilder(bar_seconds=5)
        tick_at(builder, 100, 100.0)
        tick_at(builder, 105, 110.0)  # completes window 100
        tick_at(builder, 110, 120.0)  # completes window 105

        # Only the second completion is returned here; the first was captured inline
        second = tick_at(builder, 110, 120.0)
        # Within window 110, no completion
        assert second is None

    def test_bar_timestamp_snapped_to_window(self):
        builder = OHLCVBuilder(bar_seconds=5)
        tick_at(builder, 103, 100.0)  # snapped to 100
        assert builder.current().time == 100


class TestChainPriceTracker:
    def test_initial_price_stored(self):
        tracker = ChainPriceTracker(3500.0)
        assert tracker.price == 3500.0

    def test_record_fill_updates_price(self):
        tracker = ChainPriceTracker(3500.0)
        fill_at(tracker, 100, 3600.0)
        assert tracker.price == 3600.0

    def test_record_fill_returns_none_within_window(self):
        tracker = ChainPriceTracker(3500.0)
        assert fill_at(tracker, 100, 3500.0) is None
        assert fill_at(tracker, 101, 3510.0) is None

    def test_record_fill_returns_bar_dict_when_window_closes(self):
        tracker = ChainPriceTracker(3500.0)
        fill_at(tracker, 100, 3500.0, 1.0)
        completed = fill_at(tracker, 105, 3600.0, 2.0)

        assert completed is not None
        assert completed["open"]   == 3500.0
        assert completed["close"]  == 3500.0
        assert completed["volume"] == 1.0

    def test_completed_bar_appended_to_history(self):
        tracker = ChainPriceTracker(3500.0)
        fill_at(tracker, 100, 3500.0, 1.0)
        fill_at(tracker, 105, 3510.0, 1.0)  # closes window 100
        fill_at(tracker, 110, 3520.0, 1.0)  # closes window 105

        assert len(tracker.history) == 2
        assert tracker.history[0]["close"] == 3500.0
        assert tracker.history[1]["close"] == 3510.0

    def test_get_recent_closes_returns_last_n(self):
        tracker = ChainPriceTracker(3500.0)
        for i in range(4):
            fill_at(tracker, 100 + i * 5, float(3500 + i * 10), 1.0)
        # 3 completed bars (windows 100, 105, 110)
        closes = tracker.get_recent_closes(2)
        assert closes == [3510.0, 3520.0]

    def test_get_recent_closes_empty_when_no_history(self):
        tracker = ChainPriceTracker(3500.0)
        assert tracker.get_recent_closes() == []

    def test_get_current_bar_returns_dict_with_expected_keys(self):
        tracker = ChainPriceTracker(3500.0)
        fill_at(tracker, 100, 3500.0, 1.0)
        bar = tracker.get_current_bar()
        assert bar is not None
        assert set(bar.keys()) == {"time", "open", "high", "low", "close", "volume"}

    def test_get_current_bar_none_before_any_fill(self):
        assert ChainPriceTracker(3500.0).get_current_bar() is None

    def test_bar_values_rounded_correctly(self):
        tracker = ChainPriceTracker(3500.0)
        fill_at(tracker, 100, 3500.12345, 1.123456)
        bar = tracker.get_current_bar()
        assert bar["close"]  == round(3500.12345, 4)
        assert bar["volume"] == round(1.123456, 2)

    def test_history_capped_at_500_bars(self):
        tracker = ChainPriceTracker(100.0)
        for i in range(502):
            fill_at(tracker, 100 + i * 5, 100.0 + i, 1.0)
        assert len(tracker.history) == 500
