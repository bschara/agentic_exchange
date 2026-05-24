import { create } from 'zustand';
import { AgentState, ChainMetrics, Fill } from '@/lib/types';

const AGENT_DEFAULTS: { agent_id: AgentState['agent_id']; agent_name: string }[] = [
  { agent_id: 'market_maker',    agent_name: 'MM-Prime' },
  { agent_id: 'momentum_trader', agent_name: 'Momentum-Alpha' },
  { agent_id: 'arbitrage_agent', agent_name: 'Arb-Scanner' },
  { agent_id: 'risk_manager',    agent_name: 'Risk-Shield' },
  { agent_id: 'noise_trader',    agent_name: 'Noise-Bot' },
];

function makeDefaultAgent(agent_id: AgentState['agent_id'], agent_name: string): AgentState {
  return {
    agent_id,
    agent_name,
    decisions_total: 0,
    buy_count: 0,
    sell_count: 0,
    hold_count: 0,
    failures: 0,
    orders_placed: 0,
    treasury_balance: 0,
    last_decision: null,
    last_price: 0,
    last_fetched_price: 0,
    last_context: '',
    win_streak: 0,
    loop_stopped: false,
    loop_stopped_reason: null,
    last_order_id: null,
    trade_pnl: 0,
    total_buy_volume: 0,
    total_sell_volume: 0,
    avg_decision_latency_ms: 0,
    decision_latency_count: 0,
    net_position: 0,
    unrealized_pnl: 0,
    wallet_address: '',
  };
}

const initAgents: Record<string, AgentState> = {};
const initHistory: Record<string, string[]> = {};
for (const { agent_id, agent_name } of AGENT_DEFAULTS) {
  initAgents[agent_id] = makeDefaultAgent(agent_id, agent_name);
  initHistory[agent_id] = [];
}

interface AgentStore {
  agents: Record<string, AgentState>;
  decisionHistory: Record<string, string[]>;
  coordinatorBalance: number;
  totalLocked: number;
  loopStoppedAny: boolean;
  recentFills: Fill[];
  somniaBlockMs: number;

  updateFromChainMetrics: (metrics: ChainMetrics) => void;
}

export const useAgentStore = create<AgentStore>((set) => ({
  agents: initAgents,
  decisionHistory: initHistory,
  coordinatorBalance: 0,
  totalLocked: 0,
  loopStoppedAny: false,
  recentFills: [],
  somniaBlockMs: 0,

  updateFromChainMetrics: (metrics) =>
    set((s) => {
      const newAgents = { ...s.agents };
      const newHistory = { ...s.decisionHistory };

      for (const [id, agent] of Object.entries(metrics.agents)) {
        const prev = s.agents[id];
        newAgents[id] = agent as AgentState;

        if (prev && agent.decisions_total > prev.decisions_total && agent.last_decision) {
          const price = agent.last_price > 0 ? `$${agent.last_price.toFixed(2)}` : '—';
          const entry = `${agent.last_decision} @ ${price}`;
          newHistory[id] = [entry, ...(newHistory[id] || [])].slice(0, 20);
        } else if (!prev) {
          newHistory[id] = [];
        }
      }

      return {
        agents: newAgents,
        decisionHistory: newHistory,
        coordinatorBalance: metrics.coordinator_balance,
        totalLocked: metrics.total_locked,
        loopStoppedAny: metrics.loop_stopped_any,
        recentFills: metrics.recent_fills ?? s.recentFills,
        somniaBlockMs: metrics.somnia_block_ms ?? s.somniaBlockMs,
      };
    }),
}));
