import { create } from 'zustand';
import { CandleData, OrderBook, Trade, MarketSnapshot } from '@/lib/types';
import { FAKE_CANDLES, FAKE_ORDER_BOOK, FAKE_TRADES } from '@/lib/fake-data';

interface MarketStore {
  candles: CandleData[];
  orderBook: OrderBook;
  recentTrades: Trade[];
  currentPrice: number;
  priceChange24h: number;
  volume24h: number;
  spreadPct: number;
  isConnected: boolean;

  addCandle: (candle: CandleData) => void;
  setOrderBook: (ob: OrderBook) => void;
  addTrade: (trade: Trade) => void;
  setMarketSnapshot: (snap: MarketSnapshot) => void;
  setConnected: (v: boolean) => void;
}

const initPrice = FAKE_CANDLES[FAKE_CANDLES.length - 1].close;

export const useMarketStore = create<MarketStore>((set) => ({
  candles: FAKE_CANDLES,
  orderBook: FAKE_ORDER_BOOK,
  recentTrades: FAKE_TRADES,
  currentPrice: initPrice,
  priceChange24h: 2.34,
  volume24h: 48230,
  spreadPct: 0.28,
  isConnected: false,

  addCandle: (candle) =>
    set((s) => {
      const candles = [...s.candles];
      const last = candles[candles.length - 1];
      if (last && last.time === candle.time) {
        candles[candles.length - 1] = candle;
      } else {
        candles.push(candle);
        if (candles.length > 200) candles.shift();
      }
      return { candles, currentPrice: candle.close };
    }),

  setOrderBook: (orderBook) => set({ orderBook }),

  addTrade: (trade) =>
    set((s) => {
      const trades = [trade, ...s.recentTrades].slice(0, 50);
      return { recentTrades: trades };
    }),

  setMarketSnapshot: (snap) =>
    set({
      currentPrice: snap.price,
      priceChange24h: snap.price_change_24h_pct,
      volume24h: snap.volume_24h,
      spreadPct: snap.spread_pct,
      orderBook: snap.order_book,
      recentTrades: snap.recent_trades,
    }),

  setConnected: (isConnected) => set({ isConnected }),
}));
