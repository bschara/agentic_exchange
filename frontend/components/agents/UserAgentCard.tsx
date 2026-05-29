'use client';

import { useState } from 'react';
import { UserAgentRecord, AgentState, AgentStatus } from '@/lib/types';
import { AgentStatusBadge } from './AgentStatusBadge';
import { PauseCircle, PlayCircle, Coins } from 'lucide-react';

const DECISION_COLORS: Record<string, string> = {
  BUY:  'text-emerald-400',
  SELL: 'text-red-400',
  HOLD: 'text-gray-500',
};

function agentStatus(metrics?: AgentState): AgentStatus {
  if (!metrics) return 'WAITING';
  if (metrics.loop_stopped) return 'STOPPED';
  if (metrics.decisions_total > 0 || metrics.orders_placed > 0) return 'ACTIVE';
  return 'WAITING';
}

interface Props {
  agent: UserAgentRecord;
  onPause: () => Promise<string>;
  onResume: () => Promise<string>;
  onFund: (amount: number) => Promise<string>;
}

export function UserAgentCard({ agent, onPause, onResume, onFund }: Props) {
  const m = agent.metrics;
  const status = agentStatus(m);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [fundAmount, setFundAmount] = useState('0.1');
  const [txMsg, setTxMsg] = useState<string | null>(null);

  const total      = m?.decisions_total || 1;
  const buyPct     = Math.round(((m?.buy_count  ?? 0) / total) * 100);
  const sellPct    = Math.round(((m?.sell_count ?? 0) / total) * 100);
  const holdPct    = Math.round(((m?.hold_count ?? 0) / total) * 100);
  const lastColor  = DECISION_COLORS[m?.last_decision ?? ''] ?? 'text-gray-600';
  const isPaused   = m?.loop_stopped && m?.loop_stopped_reason === 'paused';

  const handle = async (action: string, fn: () => Promise<string>) => {
    if (actionLoading) return;
    setActionLoading(action);
    setTxMsg(null);
    try {
      const tx = await fn();
      setTxMsg(`tx: ${tx.slice(0, 10)}…`);
    } catch (e: unknown) {
      setTxMsg(e instanceof Error ? e.message.slice(0, 60) : 'Error');
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className="flex flex-col gap-2 p-3 rounded-xl bg-black/40 backdrop-blur border border-cyan-500/30 hover:border-cyan-500/50 hover:shadow-[0_0_20px_rgba(6,182,212,0.08)] transition-all duration-300">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg">{agent.icon ?? '🤖'}</span>
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-bold text-white">{agent.name}</span>
              {(m?.win_streak ?? 0) > 0 && (
                <span className="text-[10px] font-bold px-1 py-0.5 rounded bg-orange-500/20 text-orange-400 border border-orange-500/40 animate-pulse">
                  🔥 {m!.win_streak}
                </span>
              )}
            </div>
            <div className="flex items-center gap-1">
              <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-cyan-500/20 text-cyan-300 border border-cyan-500/40">
                ⬡ USER AGENT
              </span>
              {agent.risk_level > 0 && (
                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border ${
                  agent.risk_level <= 2 ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' :
                  agent.risk_level === 3 ? 'bg-blue-500/10 text-blue-400 border-blue-500/30' :
                  agent.risk_level === 4 ? 'bg-orange-500/10 text-orange-400 border-orange-500/30' :
                  'bg-red-500/10 text-red-400 border-red-500/30'
                }`}>
                  RISK {agent.risk_level}/5
                </span>
              )}
            </div>
          </div>
        </div>
        <AgentStatusBadge status={status} />
      </div>

      {/* System prompt excerpt */}
      <p className="text-[10px] text-gray-500 leading-tight line-clamp-2" title={agent.metrics?.last_context || ''}>
        Strategy: <span className="text-gray-400 italic">AI-defined (on-chain)</span>
      </p>

      {/* Stats row */}
      {m && (
        <div className="grid grid-cols-4 gap-1.5 text-center">
          <div className="bg-white/5 rounded-lg px-1.5 py-1.5">
            <p className="text-[10px] text-gray-500">sETH</p>
            <p className="text-[10px] font-mono font-bold text-white">{(m.agt_balance ?? 0).toFixed(2)}</p>
          </div>
          <div className="bg-white/5 rounded-lg px-1.5 py-1.5">
            <p className="text-[10px] text-gray-500">Last</p>
            <p className={`text-[10px] font-mono font-bold ${lastColor}`}>{m.last_decision ?? '—'}</p>
          </div>
          <div className="bg-white/5 rounded-lg px-1.5 py-1.5">
            <p className="text-[10px] text-gray-500">Decisions</p>
            <p className="text-[10px] font-mono font-bold text-white">{m.decisions_total}</p>
          </div>
          <div className="bg-white/5 rounded-lg px-1.5 py-1.5">
            <p className="text-[10px] text-gray-500">P&L</p>
            <p className={`text-[10px] font-mono font-bold ${(m.trade_pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {(m.trade_pnl ?? 0) >= 0 ? '+' : ''}{(m.trade_pnl ?? 0).toFixed(4)}
            </p>
          </div>
        </div>
      )}

      {/* BUY/SELL/HOLD bar */}
      {m && m.decisions_total > 0 && (
        <div className="flex gap-1 text-[10px] font-mono text-center">
          <div className="bg-emerald-500/20 text-emerald-400 rounded px-1 py-0.5 flex-1">B {buyPct}%</div>
          <div className="bg-red-500/20 text-red-400 rounded px-1 py-0.5 flex-1">S {sellPct}%</div>
          <div className="bg-white/5 text-gray-500 rounded px-1 py-0.5 flex-1">H {holdPct}%</div>
        </div>
      )}

      {/* Owner controls */}
      <div className="flex items-center gap-2 pt-1 border-t border-white/5">
        {isPaused ? (
          <button
            onClick={() => handle('resume', onResume)}
            disabled={!!actionLoading}
            className="flex items-center gap-1 px-2 py-1 text-[10px] font-bold border border-emerald-500/40 text-emerald-400 rounded bg-emerald-500/10 hover:bg-emerald-500/20 disabled:opacity-40 transition-all"
          >
            <PlayCircle className="w-3 h-3" />
            {actionLoading === 'resume' ? '...' : 'RESUME'}
          </button>
        ) : (
          <button
            onClick={() => handle('pause', onPause)}
            disabled={!!actionLoading}
            className="flex items-center gap-1 px-2 py-1 text-[10px] font-bold border border-orange-500/40 text-orange-400 rounded bg-orange-500/10 hover:bg-orange-500/20 disabled:opacity-40 transition-all"
          >
            <PauseCircle className="w-3 h-3" />
            {actionLoading === 'pause' ? '...' : 'PAUSE'}
          </button>
        )}
        <div className="flex items-center gap-1 ml-auto">
          <input
            type="number"
            min="0.001"
            step="0.01"
            value={fundAmount}
            onChange={(e) => setFundAmount(e.target.value)}
            className="w-14 px-1.5 py-1 text-[10px] font-mono bg-black/40 border border-white/10 rounded text-white text-center"
          />
          <span className="text-[10px] text-gray-600">STT</span>
          <button
            onClick={() => handle('fund', () => onFund(parseFloat(fundAmount) || 0.1))}
            disabled={!!actionLoading}
            className="flex items-center gap-1 px-2 py-1 text-[10px] font-bold border border-blue-500/40 text-blue-400 rounded bg-blue-500/10 hover:bg-blue-500/20 disabled:opacity-40 transition-all"
          >
            <Coins className="w-3 h-3" />
            {actionLoading === 'fund' ? '...' : 'FUND'}
          </button>
        </div>
      </div>

      {/* Tx feedback */}
      {txMsg && (
        <p className="text-[10px] font-mono text-gray-500 truncate">{txMsg}</p>
      )}
    </div>
  );
}
