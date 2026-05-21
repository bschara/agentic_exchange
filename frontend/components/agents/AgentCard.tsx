'use client';

import { AgentState, AgentStatus } from '@/lib/types';
import { AgentStatusBadge } from './AgentStatusBadge';
import { ReasoningPanel } from './ReasoningPanel';
import { ExternalLink } from 'lucide-react';

const AGENT_ICONS: Record<string, string> = {
  market_maker:    '⚖️',
  momentum_trader: '📈',
  arbitrage_agent: '🔍',
  risk_manager:    '🛡️',
};

const AGENT_COLORS: Record<string, string> = {
  market_maker:    'border-blue-500/30',
  momentum_trader: 'border-emerald-500/30',
  arbitrage_agent: 'border-violet-500/30',
  risk_manager:    'border-yellow-500/30',
};

const AGENT_GLOW: Record<string, string> = {
  market_maker:    'hover:border-blue-500/50 hover:shadow-[0_0_20px_rgba(59,130,246,0.1)]',
  momentum_trader: 'hover:border-emerald-500/50 hover:shadow-[0_0_20px_rgba(16,185,129,0.1)]',
  arbitrage_agent: 'hover:border-violet-500/50 hover:shadow-[0_0_20px_rgba(139,92,246,0.1)]',
  risk_manager:    'hover:border-yellow-500/50 hover:shadow-[0_0_20px_rgba(234,179,8,0.1)]',
};

const DECISION_COLORS: Record<string, string> = {
  BUY:  'text-emerald-400',
  SELL: 'text-red-400',
  HOLD: 'text-gray-500',
};

const explorerBase =
  process.env.NEXT_PUBLIC_SOMNIA_EXPLORER || 'https://shannon-explorer.somnia.network';

function agentStatus(agent: AgentState): AgentStatus {
  if (agent.loop_stopped) return 'STOPPED';
  if (agent.decisions_total > 0) return 'ACTIVE';
  return 'WAITING';
}

export function AgentCard({ agent }: { agent: AgentState }) {
  const status = agentStatus(agent);
  const total = agent.decisions_total || 1;
  const buyPct  = Math.round((agent.buy_count  / total) * 100);
  const sellPct = Math.round((agent.sell_count / total) * 100);
  const holdPct = Math.round((agent.hold_count / total) * 100);
  const lastDecisionColor = DECISION_COLORS[agent.last_decision ?? ''] ?? 'text-gray-600';

  return (
    <div
      className={`flex flex-col gap-3 p-4 rounded-xl bg-black/40 backdrop-blur border transition-all duration-300 ${AGENT_COLORS[agent.agent_id]} ${AGENT_GLOW[agent.agent_id]}`}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg">{AGENT_ICONS[agent.agent_id]}</span>
          <div className="flex flex-col gap-0.5">
            <span className="text-sm font-bold text-white">{agent.agent_name}</span>
            <span
              title="Decisions made by Somnia's on-chain LLM validator consensus"
              className="text-[10px] font-semibold px-1.5 py-0.5 rounded w-fit bg-violet-500/20 text-violet-300 border border-violet-500/40"
            >
              ⬡ ON-CHAIN LLM
            </span>
          </div>
        </div>
        <AgentStatusBadge status={status} />
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="bg-white/5 rounded-lg px-2 py-1.5">
          <p className="text-xs text-gray-500">Treasury</p>
          <p className="text-xs font-mono font-bold text-white">
            {agent.treasury_balance.toFixed(3)} STT
          </p>
        </div>
        <div className="bg-white/5 rounded-lg px-2 py-1.5">
          <p className="text-xs text-gray-500">Last</p>
          <p className={`text-xs font-mono font-bold ${lastDecisionColor}`}>
            {agent.last_decision ?? '—'}
          </p>
        </div>
        <div className="bg-white/5 rounded-lg px-2 py-1.5">
          <p className="text-xs text-gray-500">Decisions</p>
          <p className="text-xs font-mono font-bold text-white">{agent.decisions_total}</p>
        </div>
      </div>

      {/* BUY/SELL/HOLD bar */}
      {agent.decisions_total > 0 && (
        <div className="flex gap-1 text-[10px] font-mono text-center">
          <div
            className="bg-emerald-500/20 text-emerald-400 rounded px-1 py-0.5 flex-1"
            title={`${agent.buy_count} BUY`}
          >
            B {buyPct}%
          </div>
          <div
            className="bg-red-500/20 text-red-400 rounded px-1 py-0.5 flex-1"
            title={`${agent.sell_count} SELL`}
          >
            S {sellPct}%
          </div>
          <div
            className="bg-white/5 text-gray-500 rounded px-1 py-0.5 flex-1"
            title={`${agent.hold_count} HOLD`}
          >
            H {holdPct}%
          </div>
        </div>
      )}

      {/* Decision history */}
      <div className="bg-black/30 rounded-lg p-2.5 border border-white/5 flex-1">
        <p className="text-xs text-gray-600 mb-1.5 font-semibold uppercase tracking-wider">
          Decision History
        </p>
        <ReasoningPanel agentId={agent.agent_id} />
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between text-xs text-gray-600">
        <span>
          {agent.orders_placed} orders · {agent.failures} failures
        </span>
        {agent.loop_stopped ? (
          <span className="text-red-500/70 truncate max-w-[120px]" title={agent.loop_stopped_reason ?? ''}>
            {agent.loop_stopped_reason ?? 'loop stopped'}
          </span>
        ) : agent.last_price > 0 ? (
          <a
            href={`${explorerBase}/address/${agent.agent_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-violet-400 hover:text-violet-300 transition-colors"
          >
            <span>${agent.last_price.toFixed(2)}</span>
            <ExternalLink className="w-3 h-3" />
          </a>
        ) : (
          <span className="text-gray-700">waiting…</span>
        )}
      </div>
    </div>
  );
}
