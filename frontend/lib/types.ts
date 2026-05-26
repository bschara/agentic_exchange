export interface CandleData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface OrderBookLevel {
  price: number;
  size: number;
}

export interface OrderBook {
  bids: OrderBookLevel[];
  asks: OrderBookLevel[];
}

export interface Trade {
  id: number;
  price: number;
  amount: number;
  side: 'buy' | 'sell';
  timestamp: number;
  buyer_agent?: string | null;
  seller_agent?: string | null;
}

export interface Fill {
  price: number;
  amount: number;
  buyer_agent: string;
  seller_agent: string;
  block: number;
  tx_hash?: string;
}

export interface AgentState {
  agent_id: 'market_maker' | 'momentum_trader' | 'arbitrage_agent' | 'risk_manager' | 'noise_trader';
  agent_name: string;
  decisions_total: number;
  buy_count: number;
  sell_count: number;
  hold_count: number;
  failures: number;
  orders_placed: number;
  treasury_balance: number;
  agt_balance: number;
  last_decision: 'BUY' | 'SELL' | 'HOLD' | null;
  last_price: number;
  last_fetched_price: number;
  last_context: string;       // full LLM prompt from last LLMRequestFired event
  win_streak: number;         // consecutive filled-order streak
  loop_stopped: boolean;
  loop_stopped_reason: string | null;
  last_order_id: number | null;
  trade_pnl: number;
  total_buy_volume: number;
  total_sell_volume: number;
  avg_decision_latency_ms: number;
  decision_latency_count: number;
  net_position: number;
  unrealized_pnl: number;
  wallet_address: string;
}

export interface CoalitionAlert {
  direction: string;
  agent_count: number;
  price: number;
  order_id: number;
  block: number;
  timestamp: number;
}

export interface ChainMetrics {
  coordinator_balance: number;
  total_locked: number;
  spread_pct: number;
  buy_depth: number;
  sell_depth: number;
  loop_stopped_any: boolean;
  agents: Record<string, AgentState>;
  recent_fills: Fill[];
  coalition_alert: CoalitionAlert | null;
  somnia_block_ms: number;
  last_update: number;
}

export interface MarketSnapshot {
  price: number;
  bid: number;
  ask: number;
  spread_pct: number;
  volume_24h: number;
  price_change_24h_pct: number;
  order_book: OrderBook;
  recent_trades: Trade[];
}

export interface ActivityFeedItem {
  id: string;
  agent_id: string;
  agent_name: string;
  message: string;
  category: 'order' | 'trade' | 'warning' | 'event' | 'system' | 'coalition';
  timestamp: number;
  tx_hash?: string;
}

export interface RiskWarning {
  from_agent: string;
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
  warning_type: string;
  message: string;
  timestamp: number;
}

export interface EventInjected {
  event_type: string;
  description: string;
  price_before: number;
  price_after: number;
  timestamp: number;
}

export type AgentStatus = 'ACTIVE' | 'WAITING' | 'STOPPED';

export type WSMessage =
  | { type: 'market_snapshot'; data: MarketSnapshot; timestamp: number }
  | { type: 'candle'; data: CandleData }
  | { type: 'chain_metrics'; data: ChainMetrics; timestamp: number }
  | { type: 'risk_warning'; data: RiskWarning }
  | { type: 'event_injected'; data: EventInjected }
  | { type: 'coalition_alert'; data: CoalitionAlert; timestamp: number }
  | { type: 'pong' };
