import { CandleData, OrderBook, Trade, AgentState, ActivityFeedItem } from './types';

function gbmPrice(initial: number, count: number, vol = 0.02): number[] {
  const prices: number[] = [initial];
  for (let i = 1; i < count; i++) {
    const z = (Math.random() * 2 - 1) * Math.sqrt(3);
    const ret = (0.0002 - 0.5 * vol * vol) + vol * z;
    prices.push(prices[i - 1] * Math.exp(ret));
  }
  return prices;
}

function buildCandles(count = 120): CandleData[] {
  const prices = gbmPrice(100, count * 4 + 1, 0.015);
  const now = Math.floor(Date.now() / 1000);
  const candles: CandleData[] = [];
  for (let i = 0; i < count; i++) {
    const slice = prices.slice(i * 4, i * 4 + 5);
    const open = slice[0];
    const close = slice[4];
    const high = Math.max(...slice) * (1 + Math.random() * 0.003);
    const low = Math.min(...slice) * (1 - Math.random() * 0.003);
    candles.push({
      time: now - (count - i) * 5,
      open,
      high,
      low,
      close,
      volume: 50 + Math.random() * 300,
    });
  }
  return candles;
}

export const FAKE_CANDLES: CandleData[] = buildCandles(120);

const midPrice = FAKE_CANDLES[FAKE_CANDLES.length - 1].close;

export const FAKE_ORDER_BOOK: OrderBook = {
  bids: Array.from({ length: 10 }, (_, i) => ({
    price: +(midPrice * (1 - 0.001 * (i + 1))).toFixed(2),
    size: +(0.5 + Math.random() * 3).toFixed(3),
  })),
  asks: Array.from({ length: 10 }, (_, i) => ({
    price: +(midPrice * (1 + 0.001 * (i + 1))).toFixed(2),
    size: +(0.5 + Math.random() * 3).toFixed(3),
  })),
};

const now = Math.floor(Date.now() / 1000);

export const FAKE_TRADES: Trade[] = Array.from({ length: 20 }, (_, i) => ({
  id: 20 - i,
  price: +(midPrice * (1 + (Math.random() - 0.5) * 0.005)).toFixed(2),
  amount: +(0.1 + Math.random() * 1.5).toFixed(3),
  side: Math.random() > 0.5 ? 'buy' : 'sell',
  timestamp: now - i * 8,
}));

export const FAKE_AGENTS: AgentState[] = [
  {
    agent_id: 'market_maker',
    agent_name: 'MM-Prime',
    status: 'IDLE',
    balance_eth: 2.45,
    position: 0.0,
    position_side: 'FLAT',
    pnl_session: 0.0023,
    active_orders: 2,
    last_action: 'place_order',
    last_tx_hash: null,
    reasoning: 'Market conditions stable. Spread at 0.28%. Placing symmetric limit orders at ±0.15% from mid to capture flow. Volatility within normal range — maintaining standard spread.',
    reasoning_summary: 'Placed bid/ask around mid at standard spread',
    loop_count: 0,
    timestamp: now,
  },
  {
    agent_id: 'momentum_trader',
    agent_name: 'Momentum-Alpha',
    status: 'IDLE',
    balance_eth: 1.87,
    position: 0.5,
    position_side: 'LONG',
    pnl_session: -0.0012,
    active_orders: 1,
    last_action: 'place_order',
    last_tx_hash: null,
    reasoning: 'Detected 5-bar uptrend with increasing volume. Price broke above recent resistance. Entering long position with 0.5 ETH. Stop-loss mentally set at 1.5% below entry.',
    reasoning_summary: 'Long entry on 5-bar breakout with volume confirmation',
    loop_count: 0,
    timestamp: now,
  },
  {
    agent_id: 'arbitrage_agent',
    agent_name: 'Arb-Scanner',
    status: 'IDLE',
    balance_eth: 3.10,
    position: 0.0,
    position_side: 'FLAT',
    pnl_session: 0.0089,
    active_orders: 0,
    last_action: 'hold',
    last_tx_hash: null,
    reasoning: 'Current spread is 0.28% — below my 0.5% threshold for arbitrage. No inefficiency to exploit. Monitoring for spread widening or pricing gaps. Holding flat.',
    reasoning_summary: 'Spread too tight for arbitrage — monitoring',
    loop_count: 0,
    timestamp: now,
  },
  {
    agent_id: 'risk_manager',
    agent_name: 'Risk-Shield',
    status: 'IDLE',
    balance_eth: 1.95,
    position: -0.25,
    position_side: 'SHORT',
    pnl_session: 0.0041,
    active_orders: 1,
    last_action: 'place_order',
    last_tx_hash: null,
    reasoning: 'Portfolio exposure within safe limits. Total position value: 18% of treasury. Volatility at 1.9% — normal range. No warnings needed. Maintaining small short hedge position.',
    reasoning_summary: 'Exposure healthy — maintaining short hedge',
    loop_count: 0,
    timestamp: now,
  },
];

export const FAKE_FEED_ITEMS: ActivityFeedItem[] = [
  { id: '1', agent_id: 'market_maker', agent_name: 'MM-Prime', message: 'Placed bid at $' + (midPrice * 0.999).toFixed(2) + ' and ask at $' + (midPrice * 1.001).toFixed(2), category: 'order', timestamp: now - 5 },
  { id: '2', agent_id: 'momentum_trader', agent_name: 'Momentum-Alpha', message: 'Entered LONG 0.5 ETH on 5-bar breakout', category: 'trade', timestamp: now - 13 },
  { id: '3', agent_id: 'risk_manager', agent_name: 'Risk-Shield', message: 'Portfolio check: all exposure within limits', category: 'system', timestamp: now - 21 },
  { id: '4', agent_id: 'arbitrage_agent', agent_name: 'Arb-Scanner', message: 'Spread 0.28% — below arbitrage threshold, holding flat', category: 'order', timestamp: now - 29 },
  { id: '5', agent_id: 'market_maker', agent_name: 'MM-Prime', message: 'Cancelled stale bid from previous cycle', category: 'order', timestamp: now - 37 },
];
