import pytest
from market.order_book import OrderBook, BookEntry


@pytest.fixture
def book():
    return OrderBook()


class TestAddOrder:
    def test_buy_order_goes_into_bids(self, book):
        book.add_order(1, True, 100.0, 1.0, "alpha")
        assert 1 in book._bids
        assert 1 not in book._asks

    def test_sell_order_goes_into_asks(self, book):
        book.add_order(2, False, 110.0, 1.0, "beta")
        assert 2 in book._asks
        assert 2 not in book._bids

    def test_stored_entry_fields(self, book):
        book.add_order(1, True, 99.5, 2.5, "gamma")
        entry = book._bids[1]
        assert entry.order_id == 1
        assert entry.price == 99.5
        assert entry.size == 2.5
        assert entry.agent == "gamma"
        assert entry.is_buy is True


class TestRemoveOrder:
    def test_removes_bid(self, book):
        book.add_order(1, True, 100.0, 1.0, "alpha")
        book.remove_order(1)
        assert 1 not in book._bids

    def test_removes_ask(self, book):
        book.add_order(2, False, 110.0, 1.0, "beta")
        book.remove_order(2)
        assert 2 not in book._asks

    def test_remove_nonexistent_is_silent(self, book):
        book.remove_order(999)  # must not raise


class TestBestBidAsk:
    def test_best_bid_returns_highest_price(self, book):
        book.add_order(1, True, 100.0, 1.0, "a")
        book.add_order(2, True, 105.0, 1.0, "b")
        book.add_order(3, True, 98.0,  1.0, "c")
        assert book.get_best_bid() == 105.0

    def test_best_ask_returns_lowest_price(self, book):
        book.add_order(4, False, 110.0, 1.0, "a")
        book.add_order(5, False, 108.0, 1.0, "b")
        book.add_order(6, False, 115.0, 1.0, "c")
        assert book.get_best_ask() == 108.0

    def test_best_bid_none_when_empty(self, book):
        assert book.get_best_bid() is None

    def test_best_ask_none_when_empty(self, book):
        assert book.get_best_ask() is None

    def test_best_bid_reflects_removal(self, book):
        book.add_order(1, True, 105.0, 1.0, "a")
        book.add_order(2, True, 100.0, 1.0, "b")
        book.remove_order(1)
        assert book.get_best_bid() == 100.0


class TestMidPrice:
    def test_mid_price_is_average_of_best_bid_and_ask(self, book):
        book.add_order(1, True,  100.0, 1.0, "a")
        book.add_order(2, False, 110.0, 1.0, "b")
        assert book.get_mid_price() == 105.0

    def test_mid_price_none_when_no_bids(self, book):
        book.add_order(1, False, 110.0, 1.0, "a")
        assert book.get_mid_price() is None

    def test_mid_price_none_when_no_asks(self, book):
        book.add_order(1, True, 100.0, 1.0, "a")
        assert book.get_mid_price() is None

    def test_mid_price_none_when_empty(self, book):
        assert book.get_mid_price() is None


class TestSpread:
    def test_spread_calculation(self, book):
        book.add_order(1, True,  100.0, 1.0, "a")
        book.add_order(2, False, 102.0, 1.0, "b")
        # (102 - 100) / 100 * 100 = 2.0%
        assert book.get_spread() == pytest.approx(2.0)

    def test_spread_zero_when_no_bids(self, book):
        book.add_order(1, False, 110.0, 1.0, "a")
        assert book.get_spread() == 0.0

    def test_spread_zero_when_no_asks(self, book):
        book.add_order(1, True, 100.0, 1.0, "a")
        assert book.get_spread() == 0.0

    def test_spread_zero_when_empty(self, book):
        assert book.get_spread() == 0.0


class TestDepth:
    def test_bids_sorted_descending(self, book):
        book.add_order(1, True, 95.0,  1.0, "a")
        book.add_order(2, True, 100.0, 1.0, "b")
        book.add_order(3, True, 98.0,  1.0, "c")
        depth = book.get_depth()
        prices = [e["price"] for e in depth["bids"]]
        assert prices == sorted(prices, reverse=True)

    def test_asks_sorted_ascending(self, book):
        book.add_order(4, False, 115.0, 1.0, "a")
        book.add_order(5, False, 108.0, 1.0, "b")
        book.add_order(6, False, 112.0, 1.0, "c")
        depth = book.get_depth()
        prices = [e["price"] for e in depth["asks"]]
        assert prices == sorted(prices)

    def test_depth_capped_at_levels(self, book):
        for i in range(20):
            book.add_order(i, True, float(100 + i), 1.0, "a")
        depth = book.get_depth(levels=5)
        assert len(depth["bids"]) == 5

    def test_depth_prices_rounded_to_4dp(self, book):
        book.add_order(1, True, 100.12345, 1.123456, "a")
        depth = book.get_depth()
        assert depth["bids"][0]["price"] == round(100.12345, 4)
        assert depth["bids"][0]["size"]  == round(1.123456, 4)

    def test_empty_book_returns_empty_lists(self, book):
        depth = book.get_depth()
        assert depth == {"bids": [], "asks": []}
