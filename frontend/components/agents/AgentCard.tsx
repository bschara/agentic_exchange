'use client';

import { AgentState } from '@/lib/types';
import { AgentStatusBadge } from './AgentStatusBadge';
import { ReasoningPanel } from './ReasoningPanel';
import { ExternalLink, TrendingUp, TrendingDown, Minus } from 'lucide-react';

const AGENT_ICONS: Record<string, string> = {
  market_maker: '⚖️',
  momentum_trader: '📈',
  arbitrage_agent: '🔍',
  risk_manager: '🛡️',
};

const AGENT_COLORS: Record<string, string> = {
  market_maker: 'border-blue-500/30',
  momentum_trader: 'border-emerald-500/30',
  arbitrage_agent: 'border-violet-500/30',
  risk_manager: 'border-yellow-500/30',
};

const AGENT_GLOW: Record<string, string> = {
  market_maker: 'hover:border-blue-500/50 hover:shadow-[0_0_20px_rgba(59,130,246,0.1)]',
  momentum_trader: 'hover:border-emerald-500/50 hover:shadow-[0_0_20px_rgba(16,185,129,0.1)]',
  arbitrage_agent: 'hover:border-violet-500/50 hover:shadow-[0_0_20px_rgba(139,92,246,0.1)]',
  risk_manager: 'hover:border-yellow-500/50 hover:shadow-[0_0_20px_rgba(234,179,8,0.1)]',
};

const explorerBase = process.env.NEXT_PUBLIC_SOMNIA_EXPLORER || 'https://shannon-explorer.somnia.network';

function truncateHash(h: string) {
  return h.slice(0, 6) + '...' + h.slice(-4);
}

function PositionIcon({ side }: { side: AgentState['position_side'] }) {
  if (side === 'LONG') return <TrendingUp className="w-3 h-3 text-emerald-400" />;
  if (side === 'SHORT') return <TrendingDown className="w-3 h-3 text-red-400" />;
  return <Minus className="w-3 h-3 text-gray-500" />;
}

export function AgentCard({ agent }: { agent: AgentState }) {
  const pnlUp = agent.pnl_session >= 0;

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
              className={`text-[10px] font-semibold px-1.5 py-0.5 rounded w-fit transition-colors ${
                agent.used_somnia_agent
                  ? 'bg-violet-500/20 text-violet-300 border border-violet-500/40'
                  : 'bg-white/5 text-gray-600 border border-white/10'
              }`}
            >
              {agent.used_somnia_agent ? '⬡ ON-CHAIN LLM' : '⬡ SOMNIA AGENT'}
            </span>
          </div>
        </div>
        <AgentStatusBadge status={agent.status} />
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="bg-white/5 rounded-lg px-2 py-1.5">
          <p className="text-xs text-gray-500">Balance</p>
          <p className="text-xs font-mono font-bold text-white">{agent.balance_eth.toFixed(3)} STT</p>
        </div>
        <div className="bg-white/5 rounded-lg px-2 py-1.5">
          <div className="flex items-center justify-center gap-1">
            <PositionIcon side={agent.position_side} />
            <p className="text-xs text-gray-500">Position</p>
          </div>
          <p className={`text-xs font-mono font-bold ${agent.position_side === 'LONG' ? 'text-emerald-400' : agent.position_side === 'SHORT' ? 'text-red-400' : 'text-gray-400'}`}>
            {agent.position === 0 ? 'FLAT' : `${agent.position > 0 ? '+' : ''}${agent.position.toFixed(3)}`}
          </p>
        </div>
        <div className="bg-white/5 rounded-lg px-2 py-1.5">
          <p className="text-xs text-gray-500">Session PnL</p>
          <p className={`text-xs font-mono font-bold ${pnlUp ? 'text-emerald-400' : 'text-red-400'}`}>
            {pnlUp ? '+' : ''}{(agent.pnl_session * 100).toFixed(3)}%
          </p>
        </div>
      </div>

      {/* Reasoning */}
      <div className="bg-black/30 rounded-lg p-2.5 border border-white/5 flex-1">
        <p className="text-xs text-gray-600 mb-1.5 font-semibold uppercase tracking-wider">Reasoning</p>
        <ReasoningPanel agentId={agent.agent_id} />
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between text-xs text-gray-600">
        <span>Loop #{agent.loop_count} · {agent.active_orders} orders</span>
        {agent.last_tx_hash ? (
          <a
            href={`${explorerBase}/tx/${agent.last_tx_hash}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-violet-400 hover:text-violet-300 transition-colors"
          >
            <span>{truncateHash(agent.last_tx_hash)}</span>
            <ExternalLink className="w-3 h-3" />
          </a>
        ) : (
          <span className="text-gray-700">no tx yet</span>
        )}
      </div>
    </div>
  );
}
