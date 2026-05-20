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
}

export interface AgentState {
  agent_id: 'market_maker' | 'momentum_trader' | 'arbitrage_agent' | 'risk_manager';
  agent_name: string;
  status: 'THINKING' | 'EXECUTING' | 'IDLE';
  balance_eth: number;
  position: number;
  position_side: 'LONG' | 'SHORT' | 'FLAT';
  pnl_session: number;
  active_orders: number;
  last_action: string;
  last_tx_hash: string | null;
  reasoning: string;
  reasoning_summary: string;
  loop_count: number;
  timestamp: number;
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
  category: 'order' | 'trade' | 'warning' | 'event' | 'system';
  timestamp: number;
}

export interface RiskWarning {
  from_agent: string;
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
  warning_type: string;
  message: string;
  timestamp: number;
}

export interface OnchainEvent {
  event: string;
  tx_hash: string;
  block_number: number;
  args: Record<string, unknown>;
}

export interface EventInjected {
  event_type: string;
  description: string;
  price_before: number;
  price_after: number;
  timestamp: number;
}

export type WSMessage =
  | { type: 'market_snapshot'; data: MarketSnapshot; timestamp: number }
  | { type: 'candle'; data: CandleData }
  | { type: 'agent_update'; data: AgentState }
  | { type: 'risk_warning'; data: RiskWarning }
  | { type: 'onchain_event'; data: OnchainEvent }
  | { type: 'event_injected'; data: EventInjected }
  | { type: 'activity_feed'; data: ActivityFeedItem }
  | { type: 'pong' };
